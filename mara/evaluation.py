"""Independent, frozen-basis report quality evaluation; never edits the proposal."""
import copy
import hashlib
import json
from datetime import date
from .agents import Agents
from .registry import resource
from .domain import dumps
from .contracts import ContractError


def rubric():return json.loads(resource('resources/evaluation-rubric.json').read_text())


def pointer(value,path):
    if not any(path.startswith('/'+k+'/') for k in ('report','profile','market','role_outputs')):
        raise ContractError('Evaluation reference '+repr(path)+' must select a field below /report, /profile, /market or /role_outputs; use e.g. /profile/goal, not the whole /profile object')
    try:
        for part in path[1:].split('/'):
            part=part.replace('~1','/').replace('~0','~')
            value=value[int(part)] if isinstance(value,list) else value[part]
        return value
    except (ValueError,KeyError,IndexError,TypeError):raise ContractError('Unknown evaluation evidence path') from None


def score(output,payload):
    criteria=payload['rubric']['criteria'];rows=output['criteria']
    if len(rows)!=len(criteria) or {r['id'] for r in rows}!={c['id'] for c in criteria}:raise ContractError('Every criterion exactly once')
    for row in rows:
        if row['score'] and not row['evidence_paths']:raise ContractError('A score needs evidence')
        for path in row['evidence_paths']:pointer(payload,path)
    total=round(sum(next(r['score'] for r in rows if r['id']==c['id'])/4*c['weight'] for c in criteria),1)
    blocked=payload['report']['proposal']['eligibility']=='blocked'
    return {'total':total,'maximum':100,'band':'strong' if total>=80 else 'needs_improvement' if total>=60 else 'major_gaps',
        'proposal_blocked':blocked,'critical_findings':len(output['red_flags']),
        'assessment':'critical_review' if output['red_flags'] or blocked else 'quality_review',
        'scored_weight':sum(c['weight'] for c in criteria),
        'rule':'보고서 품질 점수이며 수익 예측·주문 승인·R4 거부 해제가 아니에요.'}


def evaluate_report(s,model,completed_id):
    event=s.get(completed_id)
    if event['kind']!='completed':raise ValueError('Completed report required')
    report=event['body'];run_id=event['run_id'];as_of=event['effective']
    r=rubric();rhash=hashlib.sha256(dumps(r).encode()).hexdigest()
    # Idempotent for this immutable result and rubric. A changed rubric is a new assessment.
    for old in s.events('report_evaluation'):
        if old['body']['completed_id']==completed_id and old['body']['rubric_hash']==rhash:
            s.append('evaluation_status',{'status':'completed','completed_id':completed_id,'rubric_hash':rhash},date.today().isoformat(),run_id)
            return old['body']
    market=copy.deepcopy(s.get(report['market_id'])['body'])
    extra=[e['body']['fact'] for e in s.events('research_evidence') if e['run_id']==run_id and e['seq']<=event['seq']]
    known={f['id'] for f in market['facts']}
    market['facts'].extend(f for f in extra if f['id'] not in known and f['known_at']<=as_of)
    outputs={}
    for e in s.events('agent_output'):
        if e['run_id']==run_id and e['seq']<=event['seq'] and e['body']['role'] in ('context','evidence'):
            outputs[e['body']['role']]=e['body']['output']
    payload={'as_of':as_of,'evaluated_at':date.today().isoformat(),'report':report,
        'profile':s.get(report['profile_id'])['body'],'market':market,'role_outputs':outputs,
        'rubric':r,'rubric_hash':rhash,'reference_guide':resource('guides/reference-reports.md').read_text(),
        'evaluation_scope':'frozen report quality; no hindsight returns or new market evidence'}
    payload['projection']={'version':'evaluation-input/1.1','deduplication':'perspective outputs, leader proposal, both R4 results and reflection are preserved once under report. R1/R2 under role_outputs. Original invocation events remain in the run.'}
    s.append('evaluation_status',{'status':'running','completed_id':completed_id,'rubric_hash':rhash},date.today().isoformat(),run_id)
    try:
        output,oid=Agents(s,model,as_of,run_id).call('evaluator',payload)
        result={'schema_version':'mara.evaluation/1.0.0','completed_id':completed_id,'run_id':run_id,
            'as_of':as_of,'evaluated_at':date.today().isoformat(),'rubric':r,'rubric_hash':rhash,
            'output_id':oid,'output':output,'score':score(output,payload),
            'independence':'separate invocation and frozen rubric; same configured model may be used'}
        from .contracts import validate,schema
        validate(result,schema('evaluation'))
        s.append('report_evaluation',result,date.today().isoformat(),run_id)
        s.append('evaluation_status',{'status':'completed','completed_id':completed_id},date.today().isoformat(),run_id)
        return result
    except Exception as exc:
        s.append('evaluation_status',{'status':'failed','completed_id':completed_id,'error_type':type(exc).__name__},date.today().isoformat(),run_id)
        raise
