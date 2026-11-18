"""Deterministic reader document; preserves judgments, never makes new ones."""
import copy
import hashlib
import json
import math
from .domain import dumps

VERSION='mara.final-report/1.0'
RULE='final-decision-first/1'


def digest(value):return hashlib.sha256(dumps(value).encode()).hexdigest()


def input_hash(report,facts):
    body={k:v for k,v in report.items() if k not in {'final_report','proposal_id','event_id','improvement','external_review','revision_reason'}}
    return digest({'report':body,'facts':sorted(facts,key=lambda f:f['id'])})


def resolve(report,path):
    if not isinstance(path,str) or not path.startswith(('/analysis/','/funding/','/valuation/','/proposal/')):raise ValueError('Unsupported calculation path')
    value=report
    for part in path[1:].split('/'):
        part=part.replace('~1','/').replace('~0','~');value=value[int(part)] if isinstance(value,list) else value[part]
    if value is None or value=={} or value==[] or value=='':raise ValueError('Empty calculation')
    return value


def read_scope(fact):
    try:v=json.loads(fact['text'])
    except (ValueError,TypeError):return {'kind':'supplied_fact','limits':fact.get('uncertainty')}
    if not isinstance(v,dict):return {'kind':'supplied_fact','limits':fact.get('uncertainty')}
    tool=fact.get('research_tool');out={'kind':tool or 'supplied_fact'}
    if tool in {'company_filing_search','company_filing_read'}:
        out.update(filing=copy.deepcopy(v.get('filing')),raw_sha256=v.get('raw_ref',{}).get('sha256'),
            extraction_version=v.get('extraction_version'),text_length=v.get('text_length'),
            ranges=[{k:row.get(k) for k in ('start','end','pages') if k in row} for row in v.get('hits',[])] if tool=='company_filing_search' else [{k:v.get(k) for k in ('start','end','pages') if k in v}])
        out['limits']='이 범위만 읽은 기록이며 공시 전체를 검토했다는 뜻은 아니에요.'
    elif tool=='company_xbrl_read':
        out.update(**{k:copy.deepcopy(v.get(k)) for k in ('namespace','tag','unit','dossier_version')},
            observations=len(v.get('observations',[])),raw_sha256=v.get('raw_ref',{}).get('sha256'),
            limits='선택한 항목의 관측치예요. 경제적 의미·기간 통합·정상화는 별도 판단이 필요해요.')
    elif tool=='company_valuation':
        out.update(source_ids=v.get('assumptions',{}).get('source_ids',[]),limits='원자료가 아니라 분석 가정에 따른 계산이에요.')
    else:out['limits']=fact.get('uncertainty')
    return out


def assemble(report,facts):
    p=report.get('proposal',{});a=report.get('analysis',{});v=report.get('validation',{})
    review=v.get('final_critique',{});case=p.get('investment_case',{});funding=report.get('funding',{})
    issues=[]
    def issue(code,path):issues.append({'code':code,'path':path})
    def origin(role,stage,path):
        delivered=[x for x in report.get('evidence_delivery',[]) if x.get('role')==role and x.get('stage')==stage]
        return {'role':role,'stage':stage,'output_id':delivered[-1]['output_id'] if delivered else None,'path':path}
    leader=lambda path:origin('leader','proposal_synthesis',path)
    validator=lambda path:origin('validation','final_validation',path)
    for key in ('action','eligibility','decision_status','weights'):
        if key not in p:issue('missing_final_field','/proposal/'+key)
    for key in ('key_points','claims','alternatives','monitoring','scope_limits'):
        if not case.get(key):issue('missing_author_reasoning','/proposal/investment_case/'+key)
    if not review:issue('missing_final_review','/validation/final_critique')
    weights=p.get('weights',{});capital=funding.get('proposal_capital');monthly=p.get('monthly_allocation',{})
    currency=monthly.get('currency') or a.get('household',{}).get('base_currency')
    cadence=copy.deepcopy(report.get('contribution_basis')) or {'schedule':'calendar_month' if monthly.get('schedule')=='monthly' else 'every_n_days',
        'amount_per_payment':monthly.get('amount'),'monthly_amount':a.get('household',{}).get('monthly_contribution'),
        'every_days':None,'method':'당시 납입 조건으로 환산한 월평균이에요. 정확한 납입 간격은 원래 개인 설정에서 확인해요.'}
    rows=[{'symbol':s,'weight':w,'planned_amount':capital*w if capital is not None else None,
           'monthly_amount':monthly.get('amounts',{}).get(s),'actual_weight':report['valuation']['weights'].get(s,0) if 'weights' in report.get('valuation',{}) else None}
          for s,w in sorted(weights.items(),key=lambda x:(-x[1],x[0]))]
    selected=a.get('selected_weights')
    if selected is not None and weights!=selected:issue('final_analysis_weights_mismatch','/analysis/selected_weights')
    for row in rows:
        if monthly.get('amount') is not None and (row['monthly_amount'] is None or not math.isclose(row['monthly_amount'],monthly['amount']*row['weight'],rel_tol=0,abs_tol=1e-6)):
            issue('monthly_amount_mismatch','/proposal/monthly_allocation/amounts/'+row['symbol'])
    if weights and not math.isclose(sum(weights.values()),1,rel_tol=0,abs_tol=1e-9):issue('weight_sum_mismatch','/proposal/weights')
    claims=[{'claim':copy.deepcopy(c),'origin':leader('/proposal/investment_case/claims/'+str(i)),
             'status_scope':'leader_judgment','final_review_pass':review.get('qualitative_pass')}
            for i,c in enumerate(case.get('claims',[]))]
    questions=[]
    for q in report.get('research_questions',{}).get('questions',[]):
        questions.append({k:copy.deepcopy(q.get(k)) for k in ('id','target','owner','question','acceptance','state','review','fact_ids')})
    scope_ids={q['id'] for q in report.get('decision_scope',{}).get('questions',[])}
    if scope_ids!={q['id'] for q in questions}:issue('question_scope_mismatch','/research_questions/questions')
    requested=set(p.get('evidence_ids',[]));requested.update(review.get('judgment_report',{}).get('evidence_ids',[]));paths=set()
    for c in case.get('claims',[]):requested.update(c.get('fact_ids',[]));paths.update(c.get('calculation_paths',[]))
    for q in questions:
        requested.update(q.get('fact_ids') or [])
        if q.get('review'):paths.update(q['review'].get('calculation_paths',[]))
    for alt in case.get('alternatives',[]):
        if alt.get('comparison_path'):paths.add(alt['comparison_path'])
    lookup={f['id']:f for f in facts};refs=[]
    # Keep derived valuation -> observed-source edges visible, without treating
    # those underlying citations as new independent evidence.
    pending=list(sorted(requested));seen=set()
    while pending:
        fid=pending.pop(0)
        if fid in seen:continue
        seen.add(fid);fact=lookup.get(fid)
        if fact is None:issue('missing_cited_fact','/facts/'+fid);refs.append({'fact_id':fid,'available':False});continue
        current=fact.get('known_at','9999')<=report['as_of'] and fact.get('published_at','9999')<=report['as_of']<=fact.get('valid_until','')
        if not current:issue('cited_fact_outside_time','/facts/'+fid)
        scope=read_scope(fact);pending.extend(scope.get('source_ids',[]))
        refs.append({'fact_id':fid,'available':True,'current':current,'title':fact.get('topic',fid),
                     'source':fact.get('source'),'published_at':fact.get('published_at'),'known_at':fact.get('known_at'),
                     'valid_until':fact.get('valid_until'),'uncertainty':fact.get('uncertainty'),'read_scope':scope})
    calculations=[]
    for path in sorted(paths):
        try:value=resolve(report,path);calculations.append({'path':path,'available':True,'sha256':digest(value)})
        except (ValueError,KeyError,TypeError,IndexError):issue('missing_calculation',path);calculations.append({'path':path,'available':False})
    from .report_references import errors
    for error in errors(p,a,funding,report.get('valuation',{})):issue('author_reference_mismatch',error.get('path'))
    document={'schema_version':VERSION,'assembly_status':'incomplete' if issues else 'complete',
        'assembly_scope':'필드·참조·수치 연결을 확인한 구성 검사예요. 논증의 의미·투자 과제 완결·개인 적합성·실행 승인을 판정하지 않아요.',
        'provenance':{'rule_version':RULE,'input_sha256':input_hash(report,facts),'as_of':report['as_of'],
                      'run_id':report['run_id'],'persona_id':report.get('persona_id'),'persona_hash':report.get('persona_hash')},
        'decision':{'action':p.get('action'),'eligibility':p.get('eligibility'),'decision_status':copy.deepcopy(p.get('decision_status')),
                    'rationale':p.get('rationale'),'rationale_origin':leader('/proposal/rationale'),
                    'funding':copy.deepcopy(funding),'currency':currency,'risk_budget':copy.deepcopy(report.get('risk_budget'))},
        'allocation':{'weights':copy.deepcopy(weights),'rows':rows,'currency':currency,'proposal_capital':capital,
                      'actual_nav':report.get('valuation',{}).get('nav'),'monthly_plan':copy.deepcopy(monthly),
                      'contribution_basis':cadence,
                      'scope':'비중은 제안 기준액에 대한 계획이에요. 실제 보유·입금액·주문과 구분해요.'},
        'reasons':{'key_points':copy.deepcopy(case.get('key_points',[])),'key_points_origin':leader('/proposal/investment_case/key_points'),
                   'claims':claims,'final_review':copy.deepcopy(review),'final_review_origin':validator('/validation/final_critique'),
                   'scope_limits':copy.deepcopy(case.get('scope_limits',[]))},
        'alternatives':[{'alternative':copy.deepcopy(alt),'origin':leader('/proposal/investment_case/alternatives/'+str(i))}
                        for i,alt in enumerate(case.get('alternatives',[]))],
        'open_issues':{'questions':questions,'final_review_issues':copy.deepcopy(review.get('issues',[])),
                       'unsupported_claims':copy.deepcopy(review.get('unsupported_claims',[])),
                       'risks':copy.deepcopy(p.get('risks',[])),'dissent':copy.deepcopy(p.get('dissent',[])),
                       'numeric_blockers':copy.deepcopy(p.get('decision_status',{}).get('numeric_blockers',[]))},
        'next_review':{'monitoring':copy.deepcopy(case.get('monitoring',[])),'next_checks':copy.deepcopy(p.get('next_checks',[])),
                       'implementation':copy.deepcopy(case.get('implementation',[])),
                       'next_evaluation':report.get('next_evaluation'),'next_rebalance':report.get('next_rebalance'),
                       'origin':leader('/proposal/investment_case/monitoring')},
        'references':{'facts':sorted(refs,key=lambda x:x['fact_id']),'calculations':calculations},'assembly_issues':issues}
    document['provenance']['document_sha256']=digest(document)
    from .contracts import validate,schema
    validate(document,schema('final-report'))
    return document


def safe_assemble(report,facts):
    try:return assemble(report,facts)
    except (ValueError,KeyError,TypeError,IndexError,OverflowError) as error:
        return {'schema_version':VERSION,'assembly_status':'incomplete','assembly_issues':[{'code':'assembly_failed','error_type':type(error).__name__}],
                'decision':copy.deepcopy(report.get('proposal',{})),
                'assembly_scope':'보고서를 구성하지 못했어요. 원래 분석 기록과 확인된 최종 상태를 보존했어요.'}


def verified(document,report,facts):
    if not isinstance(document,dict) or document.get('schema_version')!=VERSION or not isinstance(document.get('provenance'),dict):return False
    try:
        from .contracts import validate,schema
        validate(document,schema('final-report'))
        original=copy.deepcopy(document);expected=original['provenance'].pop('document_sha256',None)
        if not (isinstance(expected,str) and digest(original)==expected and document['provenance'].get('input_sha256')==input_hash(report,facts)):return False
        # A self-consistent hash alone does not bind the document's values to
        # the engine result. Reassemble under this version's deterministic rule.
        return document==assemble(report,facts)
    except (ValueError,KeyError,TypeError,OverflowError):return False
