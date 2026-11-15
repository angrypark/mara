"""Versioned, read-only projection of completed and partial immutable runs."""
import copy
from .registry import catalogue
from .contracts import validate_workbench, validate, schema, output_schema, ContractError
from .reporting import present
from .agents import validate_output
from .output_validation import issue_code, REASONS

LABELS={'summary':'판단 요약','constraints':'이번 판단의 제약','missing':'추가로 확인할 맥락',
 'facts':'사용한 근거','drivers':'핵심 시장 요인','changes':'지난 평가 이후 변화',
 'portfolio_implications':'내 포트폴리오에 미치는 의미','uncertainties':'불확실성과 자료 공백',
 'thesis':'이 관점의 결론','weights':'제안 비중','decision_basis':'판단 근거','changes_since_previous':'이전 판단과의 차이',
 'assumptions':'핵심 가정','risks':'위험과 반대 근거','falsifiers':'판단을 바꿀 조건','next_checks':'다음 확인',
 'issues':'발견한 문제','unsupported_claims':'근거가 부족한 주장','qualitative_pass':'정성 검증 충족','reason':'검증 근거',
 'action':'제안 행동','rationale':'종합 이유','dissent':'남은 의견 차이','premise_changes':'전제의 변화',
 'validation_response':'검증 지적에 대한 응답','investment_outcome':'투자 결과 회고','process_evaluation':'판단 과정 평가',
 'perspective_review':'관점별 분석 평가','lessons':'다음 판단에 남길 교훈','guide_change_proposals':'가이드 개선 제안',
 'operations':'지식 갱신 제안','conflicts':'미해결 모순','numeric':'관점별 수치 검증','final_numeric':'최종 수치 검증',
 'pruning':'정기 지식 점검','coverage':'자료 준비 상태'}


def run_events(s,run_id):
    # Owner is always the authenticated session. Shared source records do not grant run access.
    rows=s.store.db.execute('SELECT * FROM events WHERE owner=? AND run_id=? ORDER BY seq',(s.owner,run_id)).fetchall()
    events=[s.decode(r) for r in rows]
    if not any(e['kind'] in ('run_started','completed') for e in events):raise PermissionError('Run unavailable')
    return events


def runs(s):
    starts={e['run_id']:e for e in s.events('run_started')}
    for e in s.events('completed'):starts.setdefault(e['run_id'],e)
    result=[]
    for run_id,start in sorted(starts.items(),key=lambda pair:pair[1]['seq'],reverse=True)[:40]:
        ev=run_events(s,run_id);done=next((e for e in reversed(ev) if e['kind']=='completed'),None)
        state=run_state(ev,s)
        result.append({'id':run_id,'as_of':start['effective'],'status':state,'mode':start['body']['mode'],
            'report_id':done['id'] if done else None,'revision_of':start['body'].get('revision_of')})
    return result


def run_state(events,session=None):
    if any(e['kind']=='completed' for e in events):return 'completed'
    failures=[e for e in events if e['kind']=='failed']
    if failures:
        if failures[-1]['body'].get('error_type')=='ContextNeedsInput':return 'needs_input'
        # Onboarding already validated and classified this legacy R1 failure.
        # Follow its explicit output reference instead of rewriting the old event.
        if session and failures[-1]['body'].get('error_type')=='ValueError':
            context_ids={e['id'] for e in events if e['kind']=='agent_output' and e['body'].get('role')=='context'}
            if any(j['body'].get('status')=='needs_input' and j['body'].get('context_output_id') in context_ids for j in session.events('onboarding_job')):
                return 'needs_input'
        return 'failed'
    if any(e['kind']=='recovery' for e in events):return 'interrupted'
    return 'running'


def blocks(output):
    result=[]
    for key,value in (output or {}).items():
        if key=='evidence_ids':continue
        kind='weights' if key=='weights' else 'text' if isinstance(value,str) else 'list' if isinstance(value,list) and all(isinstance(x,str) for x in value) else 'object'
        result.append({'key':key,'title':LABELS.get(key,key),'kind':kind,'value':value})
    return result


def project(s,run_id):
    ev=run_events(s,run_id)
    start=next((e for e in ev if e['kind']=='run_started'),None)
    completed=next((e for e in reversed(ev) if e['kind']=='completed'),None)
    basis=(start or completed)['body'];as_of=basis['as_of'];state=run_state(ev,s)
    market=s.get(basis['market_id'])['body'];profile=s.get(basis['profile_id'])['body']
    registry=basis.get('agent_registry') or catalogue()
    inputs={};outputs={};records={}
    for e in ev:
        b=e['body'];role=b.get('role')
        if e['kind']=='agent_input':inputs[role]=e
        if e['kind']=='agent_output':
            outputs[role]=e
            inp=s.get(b['input_id'])
            records.setdefault(role,[]).append({'input_id':inp['id'],'output_id':e['id'],
                'guide_hash':inp['body']['guide_hash'],'provider':inp['body']['provider'],
                'recorded_at':e['recorded']})
    # Older immutable reports may have no per-call events. Preserve their recorded analysis.
    fallback=completed['body']['perspectives'] if completed else {}
    report=present(s,completed) if completed else None
    corrections=[]
    if report:
        # Project legacy eligibility coherently without rewriting the source event.
        targets=[report['body']['proposal']]
        if report['view']['previous']:targets.append(report['view']['previous']['proposal'])
        for proposal in targets:
            if proposal['action']=='defer' and proposal.get('eligibility')!='blocked':
                corrections.append({'field':'proposal.eligibility','original':proposal.get('eligibility'),'projected':'blocked','reason':'defer is never an actionable proposal'})
                proposal['eligibility']='blocked'
    sources=[dict({k:f.get(k,'') for k in ('id','topic','text','source','published_at','known_at','valid_until','uncertainty')},active=f['valid_until']>=as_of) for f in market['facts']]
    source_ids={f['id'] for f in sources}
    active_role=next((e['body']['role'] for e in reversed(ev) if e['kind']=='agent_input'),None)
    components=[]
    for meta in registry:
        role=meta['id'];inp=inputs.get(role);out=outputs.get(role)
        value=copy.deepcopy(out['body']['output']) if out else copy.deepcopy(fallback.get(role))
        if value is None and completed:
            if role=='leader':value={k:v for k,v in completed['body']['proposal'].items() if k in output_schema('leader')['properties']}
            elif role=='reflection':value=copy.deepcopy(completed['body']['reflection'])
            elif role=='validation':value=copy.deepcopy(completed['body']['validation']['final_critique'])
        status='completed' if value is not None else 'pending'
        if completed and value is None:status='skipped'
        if role==active_role and state in ('failed','interrupted'):status='failed'
        if role==active_role and state=='running' and (not out or inp['seq']>out['seq']):status='running'
        if role=='context' and isinstance(value,dict) and value.get('missing'):status='needs_input'
        if role=='validation' and isinstance(value,dict) and value.get('qualitative_pass') is False:status='blocked'
        if role=='leader' and isinstance(value,dict) and value.get('action')=='defer':status='blocked'
        if completed and role in ('leader','validation') and completed['body']['proposal']['eligibility']=='blocked':status='blocked'
        rejected=None;rejection_code=None
        contract_name='agent-'+meta['kind']
        if value is not None or out:
            strict=bool(inp and inp['body'].get('contract',{}).get('$schema'))
            if not strict and meta['kind'] in ('evidence','perspective','leader'):contract_name='legacy-'+contract_name
            try:
                validate(value,schema(contract_name))
                # Validate against the original input paired with this output, even
                # while a later repair request is in flight.
                if strict and out:validate_output(role,value,s.get(out['body']['input_id'])['body']['payload'])
            except (ValueError,TypeError,KeyError) as exc:
                rejected=value;value=None;rejection_code=issue_code(exc)
                status='running' if role==active_role and state=='running' and inp and out and inp['seq']>out['seq'] else 'failed'
        summary=next((value[k] for k in ('summary','thesis','rationale','reason','process_evaluation') if value and isinstance(value.get(k),str)), '')
        if not summary:summary={'skipped':'이번 실행에서는 아직 필요하지 않은 역할이에요.','pending':'아직 실행되지 않았어요.','running':'분석 중이에요.'}.get(status,'기록된 출력에서 확인해주세요.')
        rendered=blocks(value)
        if rejection_code is not None:
            summary=REASONS[rejection_code]+(' 응답을 교정하고 있어요.' if status=='running' else ' 이 응답은 채택되지 않았어요.')
            rendered=[{'key':'contract_error','title':'출력 검증 실패','kind':'text','value':summary}]
        if role=='leader' and completed:
            final=report['body']['proposal']
            rendered.insert(0,{'key':'final_decision','title':'최종 검증을 반영한 결과 · 에이전트 초안과 구분','kind':'object',
                'value':{'action':final['action'],'eligibility':final['eligibility'],'risks':final['risks']}})
        if role=='evidence':rendered.insert(0,{'key':'coverage','title':'이 실행에서 확인한 자료 범위','kind':'object','value':market.get('coverage',{'status':'not_recorded','message':'이전 실행에는 자료 범위 표가 없어요. 각 원본의 한계를 확인해요.'})})
        if role=='validation' and completed:
            for key in ('numeric','final_numeric'):rendered.append({'key':key,'title':LABELS[key],'kind':'object','value':completed['body']['validation'][key]})
        if role=='memory' and completed:rendered.append({'key':'pruning','title':LABELS['pruning'],'kind':'object','value':report['view']['pruning']})
        refs=[x for x in (value or {}).get('evidence_ids',(value or {}).get('facts',[])) if x in source_ids]
        payload=inp['body']['payload'] if inp else {'profile':profile,'market_id':basis['market_id'],'note':'역할별 입력 기록 없음. 이 실행의 공통 맥락만 표시해요.'}
        components.append(dict(id=role,role=meta['role'],kind=meta['kind'],label=meta['label'],description=meta['description'],
            status=status,summary=summary,blocks=rendered,inputs=payload,output=value,source_ids=refs,
            records=records.get(role,[]),contract='/api/contracts/'+contract_name,
            extensions=dict({'final_proposal':report['body']['proposal']} if role=='leader' and completed else {},
                output_validation=[dict(e['body'],event_id=e['id']) for e in ev if e['kind']=='agent_validation' and e['body'].get('role')==role])))
    ids={c['id'] for c in components};edges=[]
    def edge(a,b,label):
        if a in ids and b in ids:edges.append({'from':a,'to':b,'label':label})
    edge('context','evidence','목표와 제약')
    for c in components:
        if c['kind']=='perspective':
            edge('context',c['id'],'개인 맥락');edge('evidence',c['id'],'공통 시장 근거');edge(c['id'],'validation','독립 제안');edge(c['id'],'leader','근거와 반론')
    edge('validation','leader','검증');edge('leader','validation','최종 재검증');edge('reflection','memory','결과와 교훈');edge('memory','context','다음 판단의 활성 지식')
    portfolio=None
    if report:
        r=report['body'];v=report['view']
        portfolio={'actual':r['valuation'],'proposal':r['proposal'],'previous':v['previous'],
            'funding':r.get('funding'),'validation':r['validation'],'performance':r['performance'],
            'base_currency':v['base_currency'],'next_evaluation':r['next_evaluation'],'next_rebalance':r['next_rebalance'],
            'criteria':v['criteria'],'prices':v['prices']}
    message={'completed':'저장된 판단을 탐색해요. 대화는 원래 제안을 바꾸지 않아요.',
             'needs_input':'개인 맥락에 추가 확인이 필요해요. 질문을 확인하고 투자 설정에서 답을 반영해주세요.',
             'failed':'분석이 중간에 멈췄어요. 완료한 단계의 근거는 보존돼요.',
             'interrupted':'서비스 재시작으로 중단됐어요. 자동 재실행하지 않았어요.',
             'running':'완료한 역할부터 확인할 수 있어요.'}[state]
    if state=='failed':
        rejected_component=next((c for c in components if c['id']==active_role and c['status']=='failed'
            and any(b['key']=='contract_error' for b in c['blocks'])),None)
        failed_input,failed_output=inputs.get(active_role),outputs.get(active_role)
        waiting_for_output=failed_input and (not failed_output or failed_input['seq']>failed_output['seq'])
        if waiting_for_output:
            label=next(c['label'] for c in components if c['id']==active_role)
            repair=bool(failed_input['body']['payload'].get('output_feedback'))
            message=label+(' 교정' if repair else '')+' 응답을 받는 중 실행이 중단됐어요.'
            if repair:message+=' 앞선 응답은 검증을 통과하지 못해 채택되지 않았어요.'
        elif rejected_component:message=rejected_component['label']+' 응답 검증 실패: '+rejected_component['summary']
    return validate_workbench({'schema_version':'mara.workbench/1.0.0',
        'run':{'id':run_id,'as_of':as_of,'status':state,'mode':basis['mode'],'report_id':completed['id'] if completed else None,
            'previous_id':basis.get('previous_id'),'revision_of':basis.get('revision_of'),'message':message},
        'components':components,'edges':edges,'sources':sources,'portfolio':portfolio,'extensions':{'projection_corrections':corrections}})
