"""Verified pre-feedback continuation of an undelivered second leader submission."""
import copy
from .contracts import validate
from .registry import personas
from .submission_recovery import Coordinator,contract
from .codex_model import build_prompt

def review_state(session,events,pending):
 groups={};run=pending['run_id']
 for e in events:
  if e['kind']=='recovery_leader_input':groups.setdefault(e['body']['payload']['budget']['reviews_used'],[]).append(e)
 if sorted(groups)!=list(range(1,len(groups)+1)):raise ValueError('Recovery review sequence changed')
 requests=[e for e in events if e['kind']=='submission_recovery' and e['body']['state']=='requested']
 if len(requests)!=len(groups):raise ValueError('Recovery review count changed')
 reviews=[]
 for index,inputs in sorted(groups.items()):
  first=inputs[0]['body']['payload'];ids={i['id'] for i in inputs}
  accepted=[e for e in events if e['kind']=='recovery_leader_validation' and e['body']['status']=='accepted' and e['body']['input_id'] in ids]
  if not accepted:raise ValueError('Unfinished routing review')
  chosen=accepted[-1];out=session.get(chosen['body']['output_id']);inp=session.get(out['body']['input_id']);packet=inp['body']['payload']
  for item in inputs:
   if item['body']['provider']!=pending['body']['provider'] or item['seq']>=pending['seq']:raise ValueError('Routing provider or sequence changed')
   if any(item['body']['payload'][k]!=first[k] for k in ('case_id','work_items','sources','budget','diagnostic')):raise ValueError('Routing correction changed review identity')
  for check in accepted:
   original=session.get(check['body']['output_id']);source=session.get(original['body']['input_id'])
   if original['body'].get('provider_failure') or not source['seq']<original['seq']<check['seq']<pending['seq']:raise ValueError('Unattested routing source')
   validate(original['body']['output'],source['body']['contract']);validate(original['body']['output'],contract(first['work_items']))
   if original['body']['output']['decision']!='revise':raise ValueError('Blocked routing cannot continue')
  if requests[index-1]['body']['case_id']!=packet['case_id'] or requests[index-1]['body']['work_items']!=packet['work_items']:raise ValueError('Review request changed')
  dispatches=[e for e in events if e['kind']=='submission_recovery' and e['body']['state']=='dispatched' and e['body']['leader_output_id']==out['id']]
  if len(dispatches)!=1 or dispatches[0]['body']['requests']!=out['body']['output']['requests']:raise ValueError('Effective routing dispatch changed')
  for prior in accepted[:-1]:
   oid=prior['body']['output_id']
   corrections=[e for e in events if e['kind']=='submission_recovery' and e['body']['state']=='routing_corrected' and e['body']['accepted_output_id']==out['id'] and oid in e['body']['source_output_ids']]
   rejected=[e for e in events if e['kind']=='submission_recovery' and e['body']['state']=='routing_rejected' and e['body']['leader_output_id']==oid]
   if len(corrections)!=1 or len(rejected)!=1 or dispatches[0]['body'].get('supersedes_leader_output_id')!=oid:raise ValueError('Prior accepted routing lacks explicit supersession')
   if not prior['seq']<rejected[0]['seq']<inp['seq']<chosen['seq']<corrections[0]['seq']<pending['seq']:raise ValueError('Routing supersession order changed')
  for role,source in packet['sources'].items():
   original=session.get(source['output_id'])
   if original['run_id']!=run or original['body']['role']!=role or original['body']['output']!=source['output'] or original['seq']>=inp['seq']:raise ValueError('Review source lineage changed')
  reviews.append({'packet':packet,'output_id':out['id']})
 check=Coordinator(session,None,pending['effective'],run,'')
 for review in reviews:check.restore_review(review['packet'],review['output_id'])
 return reviews

def verify_repair(session,model,plan,events,by_role):
 pending=plan['pending'];p=pending['body']['payload'];run=pending['run_id'];failure=plan['failure']
 if any(e['seq']>pending['seq'] and e['kind'] not in ('failed','continuation_failed') for e in events):raise ValueError('Pending submission already progressed')
 feedback=p['output_feedback'];rejected=session.get(feedback['rejected_output_id']);source=session.get(rejected['body']['input_id'])
 validations=[e for e in events if e['kind']=='agent_validation' and e['body']['output_id']==rejected['id']]
 if len(validations)!=1:raise ValueError('Original rejection is ambiguous')
 rejection=validations[0]
 if rejected['run_id']!=run or source['run_id']!=run or rejected['body']['role']!='leader' or not source['seq']<rejected['seq']<rejection['seq']<pending['seq']<failure['seq']:raise ValueError('Original rejection lineage changed')
 if rejection['body']['status']!='rejected' or rejection['body']['attempt']!=1 or rejection['body']['code']!='provider_submission' or rejected['body'].get('provider_failure',{}).get('reason')!='output_budget':raise ValueError('Only an original first-attempt output-budget rejection may resume')
 if source['body']['payload'].get('output_feedback') or source['body']['payload'].get('submission_repair'):raise ValueError('Local correction budget was already consumed')
 if feedback['previous_output']!=rejected['body']['output'] or feedback['submission_diagnostic']!=rejection['body']['diagnostic'] or feedback['code']!=rejection['body']['code']:raise ValueError('Rejection feedback changed')
 if {k:v for k,v in p.items() if k!='output_feedback'}!=source['body']['payload']:raise ValueError('Pending correction changed the original input')
 for key in ('role','guide','guide_hash','skills','provider','contract'):
  if pending['body'].get(key)!=source['body'].get(key):raise ValueError('Prepared submission envelope changed')
 last=by_role['leader'][-1];ref=p.get('reference_feedback',{})
 if ref.get('previous_output')!=last['body']['output']:raise ValueError('Prepared correction does not reference the last provisional draft')
 checks=[e for e in events if e['kind']=='proposal_reference_validation' and e['body']['output_id']==last['id']]
 if len(checks)!=1:raise ValueError('Provisional reference check unavailable')
 reference=checks[0];b=reference['body']
 if b['status']!='failed' or not b['errors'] or b['errors']!=ref['errors'] or not last['seq']<reference['seq']<source['seq'] or b['attempt']%3==0:raise ValueError('Only a pending local reference correction may continue')
 latest={r:by_role[r][-1] for r in personas()}
 validator=by_role['validation'][-1];vp=session.get(validator['body']['input_id'])['body']['payload']
 if vp['analysis_stage']!='perspective_validation' or validator['body']['output'].get('revision_requests') or validator['seq']>=last['seq']:raise ValueError('Latest perspective validation is not final for synthesis')
 if p['perspectives']!={r:o['body']['output'] for r,o in latest.items()} or p['validation']!=validator['body']['output']:raise ValueError('Prepared perspectives or validation changed')
 for role,out in latest.items():
  info=vp['submission_sources'][role]
  if info['output_id']!=out['id'] or info['output']!=out['body']['output']:raise ValueError('Perspective source identity changed')
 accepted_ids={o['id'] for group in by_role.values() for o in group}
 withdrawals={e['body']['source_request_event_id']:e for e in events if e['kind']=='submission_recovery' and e['body']['state']=='author_request_withdrawn'}
 for e in events:
  if e['kind']=='recovery_research_dispatch':
   ends=[x for x in events if x['kind'] in ('recovery_research_return','recovery_research_cancelled') and x['body']['dispatch_id']==e['id']]
   if len(ends)!=1 or not e['seq']<ends[0]['seq']<pending['seq']:raise ValueError('Research dispatch remains unfinished')
  if e['kind']!='submission_recovery' or e['body']['state']!='author_requested':continue
  q=e['body']['request']
  if e['id'] in withdrawals:
   withdrawal=withdrawals[e['id']]
   replacements=[x for x in events if x['kind']=='submission_recovery' and x['body']['state']=='author_requested' and x['body'].get('replaces_request_event_id')==e['id']]
   if len(replacements)!=1 or not e['seq']<withdrawal['seq']<replacements[0]['seq']<pending['seq']:raise ValueError('Withdrawn request lacks one replacement')
   if any(replacements[0]['body']['request'][k]!=q[k] for k in ('id','target_role','source_output_id','issue_path')):raise ValueError('Replacement changed original work item')
   continue
  received=False
  for oid in accepted_ids:
   out=session.get(oid);inp=session.get(out['body']['input_id'])
   if out['body']['role']==q['target_role'] and e['seq']<inp['seq']<out['seq']<pending['seq']:
    received|=any(all(x.get(k)==q[k] for k in ('id','target_role','source_output_id','issue_path','instruction','acceptance')) for x in inp['body']['payload'].get('revision_instructions',[]))
  if not received:raise ValueError('Author request has no accepted revision')
 reviews=review_state(session,events,pending)
 deliveries={}
 for role,outputs in by_role.items():
  for out in outputs:
   original=session.get(out['body']['input_id'])['body']['payload'];facts={f['id'] for f in original.get('market',{}).get('facts',[])}
   for q in original.get('revision_instructions',[]):
    ids=set(q.get('fact_ids',[]))
    if not ids<=facts:raise ValueError('Accepted revision omitted delivered facts')
    deliveries.setdefault(role,set()).update(ids)
 prompt=build_prompt(model,'leader',pending['body']['guide'],p,pending['body']['contract'])
 if len(prompt)>1048576:raise ValueError('Full provider prompt still exceeds its original limit')
 plan['cache'].update({r:(copy.deepcopy(o['body']['output']),o['id']) for r,o in (('validation',validator),('leader',last))})
 return {'reviews':reviews,'reference_event':reference,'pending_input_id':pending['id'],'original_rejected_output_id':rejected['id'],
  'prompt_characters':len(prompt),'perspectives':{r:(copy.deepcopy(o['body']['output']),o['id']) for r,o in latest.items()},
  'role_fact_deliveries':{r:sorted(ids) for r,ids in deliveries.items()},'provisional_leader_output_id':last['id']}
