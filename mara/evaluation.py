"""Independent, frozen-basis report quality evaluation; never edits the proposal."""
import copy
import hashlib
import json
from datetime import date
from .agents import Agents
from .history import profile_input,market_input
from .registry import resource
from .domain import dumps
from .contracts import ContractError


def rubric():return json.loads(resource('resources/evaluation-rubric.json').read_text())


def raw_reference_paths(payload):
    """Exact raw-evidence pointers; hashes identify captures, not claim truth."""
    market=payload.get('market',{});result=[]
    for prefix,rows in [('/market/facts',market.get('facts',[])),
                        ('/market/research/calls',market.get('research',{}).get('calls',[]))]:
        for i,row in enumerate(rows):
            for j,ref in enumerate(row.get('raw_refs',[])):
                if isinstance(ref,dict) and ref.get('sha256'):
                    result.append(f'{prefix}/{i}/raw_refs/{j}/sha256')
    return result


def pointer(value,path):
    if not any(path.startswith('/'+k+'/') for k in ('report','profile','market','role_outputs')):
        raise ContractError('Evaluation reference '+repr(path)+' must select a field below /report, /profile, /market or /role_outputs; use e.g. /profile/goal, not the whole /profile object')
    try:
        for part in path[1:].split('/'):
            part=part.replace('~1','/').replace('~0','~')
            value=value[int(part)] if isinstance(value,list) else value[part]
        return value
    except (ValueError,KeyError,IndexError,TypeError):raise ContractError('Unknown evaluation evidence path: '+path) from None


def score(output,payload):
    criteria=payload['rubric']['criteria'];rows=output['criteria']
    if len(rows)!=len(criteria) or {r['id'] for r in rows}!={c['id'] for c in criteria}:raise ContractError('Every criterion exactly once')
    errors=[]
    for row in rows:
        if row['score'] and not row['evidence_paths']:errors.append(row['id']+': a score needs evidence')
        for path in row['evidence_paths']:
            try:pointer(payload,path)
            except ContractError as exc:errors.append(row['id']+': '+str(exc))
    strict=None
    if payload['rubric']['version'].startswith('2.'):
        from .strict_evaluation import compute
        try:strict=compute(output,payload,pointer)
        except ContractError as exc:errors.append(str(exc))
    if errors:raise ContractError('\n'.join(errors))
    total=round(sum(next(r['score'] for r in rows if r['id']==c['id'])/4*c['weight'] for c in criteria),1)
    blocked=payload['report']['proposal']['eligibility']=='blocked'
    result={'total':total,'maximum':100,'band':'strong' if total>=80 else 'needs_improvement' if total>=60 else 'major_gaps',
        'proposal_blocked':blocked,'critical_findings':len(output['red_flags']),
        'assessment':'critical_review' if output['red_flags'] or blocked else 'quality_review',
        'scored_weight':sum(c['weight'] for c in criteria),
        'rule':'보고서 품질 점수이며 수익 예측·주문 승인·R4 거부 해제가 아니에요.'}
    if strict:
        result.update(strict)
        if not strict['strict_pass'] and result['band']=='strong':result['band']='needs_improvement'
    return result


def evaluator_fingerprint(s,model,as_of,guide_text=None):
    r=rubric();evaluator=Agents(s,model,as_of,None)
    from .analysis_skills import for_role
    specification={'rubric_hash':hashlib.sha256(dumps(r).encode()).hexdigest(),'guide':hashlib.sha256((guide_text if guide_text is not None else evaluator.guide('evaluator')).encode()).hexdigest(),
        'skills':for_role('evaluator'),'model':model.identity,
        'implementation':{p:hashlib.sha256(resource(p).read_bytes()).hexdigest() for p in ('mara/evaluation.py','mara/codex_model.py','mara/model_wire.py','mara/strict_evaluation.py','mara/quantitative_verifier.py','mara/coverage.py','mara/decision.py','mara/agents.py','mara/contracts.py','contracts/agent-evaluator.schema.json')},
        'appended_guide_dependencies':{p:hashlib.sha256(resource(p).read_bytes()).hexdigest() for p in ('guides/roles/allocation-mandate.md','guides/roles/research-tools.md','guides/roles/analysis-exhibits.md','guides/roles/judgment-report.md','mara/judgment_reports.py','contracts/judgment-report.schema.json')},
        'reference_guide':hashlib.sha256(resource('guides/portfolio-report-benchmarks.md' if r['version'].startswith('2.') else 'guides/reference-reports.md').read_bytes()).hexdigest()}
    return hashlib.sha256(dumps(specification).encode()).hexdigest()


def evaluate_report(s,model,completed_id,*,learn_role=False):
    event=s.get(completed_id)
    if event['kind']!='completed':raise ValueError('Completed report required')
    report=copy.deepcopy(event['body']);run_id=event['run_id'];as_of=event['effective']
    report.pop('improvement',None)  # reviewer never receives earlier scores or authoring feedback
    report.pop('revision_reason',None)
    report.pop('leader_mandate',None)  # internal authoring plan; judge the submitted report
    r=rubric();rhash=hashlib.sha256(dumps(r).encode()).hexdigest()
    evaluator=Agents(s,model,as_of,run_id)
    spec_hash=evaluator_fingerprint(s,model,as_of,evaluator.guide('evaluator'))
    evaluated_at=date.today().isoformat()
    knowledge=None
    own=[]
    if learn_role and model.mode=='live':
        from .history import scope,belongs
        boundary=scope(s,evaluated_at)
        if belongs(s,event,boundary):
            from .knowledge import Knowledge
            knowledge=Knowledge(s,after_seq=boundary['after_seq'])
            own=[item for item in knowledge.retrieve(evaluated_at,'evaluator')['items']
                 if item.get('owner_role')=='evaluator']
            from .role_knowledge import POLICY
            spec_hash=hashlib.sha256(dumps([spec_hash,POLICY,own]).encode()).hexdigest()
    # Idempotent for this immutable result and exact evaluator specification.
    # A changed rubric, guide, model or scoring implementation is a new assessment.
    for old in s.events('report_evaluation'):
        if old['body']['completed_id']==completed_id and old['body']['rubric_hash']==rhash and old['body'].get('evaluator_spec_hash')==spec_hash:
            s.append('evaluation_status',{'status':'completed','completed_id':completed_id,'rubric_hash':rhash},date.today().isoformat(),run_id)
            return old['body']
    market=market_input(s.get(report['market_id'])['body'],report.get('history_scope',{}))
    market.pop('fund_constituents',None)
    # Q1 receives actual monthly inputs as well as an independent calculator receipt.
    # Hiding them made historical claims impossible to verify from the assessment packet.
    extra=[e['body']['fact'] for e in s.events('research_evidence') if e['run_id']==run_id and e['seq']<=event['seq']]
    known={f['id'] for f in market['facts']}
    market['facts'].extend(f for f in extra if f['id'] not in known and f['known_at']<=as_of)
    outputs={}
    for e in s.events('agent_output'):
        if e['run_id']==run_id and e['seq']<=event['seq'] and e['body']['role'] in ('context','evidence'):
            outputs[e['body']['role']]=e['body']['output']
    from .quantitative_verifier import verify
    outputs['quantitative_verifier']=verify(report,market)
    payload={'as_of':as_of,'evaluated_at':date.today().isoformat(),'report':report,
        'profile':profile_input(s.get(report['profile_id'])['body'],report.get('history_scope',{'after_seq':0,'reset_id':None})),'market':market,'role_outputs':outputs,
        'rubric':r,'rubric_hash':rhash,'reference_guide':resource('guides/portfolio-report-benchmarks.md').read_text() if r['version'].startswith('2.') else resource('guides/reference-reports.md').read_text(),
        'evaluation_scope':'frozen report quality; no hindsight returns or new market evidence'}
    payload['projection']={'version':'evaluation-input/1.1','deduplication':'perspective outputs, leader proposal, both R4 results and reflection are preserved once under report. R1/R2 under role_outputs. Original invocation events remain in the run.'}
    if report.get('persona_id'):
        from .persona import snapshot
        payload['user_persona']=snapshot(s.get(report['persona_id']))
    if knowledge is not None:
        payload['knowledge']={'items':own,'scope':'Reusable evaluator process only. The fixed rubric defines the score. No new investment evidence.'}
        payload['allow_role_knowledge_update']=True
    s.append('evaluation_status',{'status':'running','completed_id':completed_id,'rubric_hash':rhash},date.today().isoformat(),run_id)
    try:
        output,oid=evaluator.call('evaluator',payload)
        result={'schema_version':'mara.evaluation/2.0.0' if r['version'].startswith('2.') else 'mara.evaluation/1.0.0','completed_id':completed_id,'run_id':run_id,
            'as_of':as_of,'evaluated_at':date.today().isoformat(),'rubric':r,'rubric_hash':rhash,
            'evaluator_spec_hash':spec_hash,'output_id':oid,'output':output,'score':score(output,payload),
            'independence':'separate invocation and frozen rubric; same configured model may be used'}
        from .contracts import validate,schema
        validate(result,schema('evaluation'))
        with s.store.transaction():
            if knowledge is not None:
                from .role_knowledge import record
                record(knowledge,max(as_of,evaluated_at),run_id,[oid])
            s.append('report_evaluation',result,evaluated_at,run_id)
        s.append('evaluation_status',{'status':'completed','completed_id':completed_id},date.today().isoformat(),run_id)
        return result
    except Exception as exc:
        s.append('evaluation_status',{'status':'failed','completed_id':completed_id,'error_type':type(exc).__name__},date.today().isoformat(),run_id)
        raise
