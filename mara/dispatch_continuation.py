"""Read-only restoration of an unexecuted pre-feedback final-validation routing."""
import copy
from .contracts import validate
from .registry import personas
from .submission_recovery import historical_catalog,historical_facts,routing_issues,contract,Coordinator
from . import history

def verify_final_dispatch(session,plan,events,by_role):
 start,failure,pending=plan['start'],plan['failure'],plan['pending'];run=start['run_id'];as_of=start['effective']
 final=by_role['validation'][-1];payload=pending['body']['payload']
 if final['body']['input_id']!=pending['id'] or not final['body']['output'].get('revision_requests'):raise ValueError('Final validation revision is unavailable')
 latest={role:by_role[role][-1] for role in personas()}
 if payload['perspectives']!={r:o['body']['output'] for r,o in latest.items()}:raise ValueError('Final perspectives do not match the last accepted authors')
 leader=by_role['leader'][-1]
 if payload['final_proposal']!=leader['body']['output']:raise ValueError('Final proposal does not match the last accepted synthesis')
 for role,out in dict(latest,leader=leader,evidence=by_role['evidence'][-1]).items():
  source=payload['submission_sources'].get(role)
  if not source or source['output_id']!=out['id'] or source['output']!=out['body']['output'] or out['seq']>=pending['seq']:raise ValueError('Final source lineage changed')
 perspective_reviews=[o for o in by_role['validation'] if session.get(o['body']['input_id'])['body']['payload']['analysis_stage']=='perspective_validation']
 if not perspective_reviews or perspective_reviews[-1]['body']['output'].get('revision_requests') or not perspective_reviews[-1]['seq']<leader['seq']<pending['seq']:raise ValueError('Perspective correction was not completed before synthesis')
 groups={}
 for e in events:
  if e['kind']=='recovery_leader_input':groups.setdefault(e['body']['payload']['budget']['reviews_used'],[]).append(e)
 if sorted(groups)!=list(range(1,len(groups)+1)) or not groups:raise ValueError('Recovery review sequence is incomplete')
 reviews=[];outputs={e['id']:e for e in events if e['kind']=='recovery_leader_output'}
 accepted=[e for e in events if e['kind']=='recovery_leader_validation' and e['body']['status']=='accepted']
 requested=[e for e in events if e['kind']=='submission_recovery' and e['body']['state']=='requested']
 if len(requested)!=len(groups):raise ValueError('Recovery requests differ from consumed reviews')
 for index,inputs in sorted(groups.items()):
  matches=[e for e in accepted if e['body']['input_id'] in {i['id'] for i in inputs}]
  if len(matches)!=1:raise ValueError('Ambiguous accepted routing')
  ver=matches[0];out=outputs[ver['body']['output_id']];inp=session.get(out['body']['input_id']);packet=inp['body']['payload']
  if out['body'].get('provider_failure'):raise ValueError('Unattested routing cannot be reused')
  if not inp['seq']<out['seq']<ver['seq']<failure['seq'] or inp['body']['provider']!=pending['body']['provider']:raise ValueError('Routing source/provider mismatch')
  validate(out['body']['output'],inp['body']['contract']);validate(out['body']['output'],contract(packet['work_items']))
  if out['body']['output']['decision']!='revise':raise ValueError('Blocked routing cannot be resumed')
  if requested[index-1]['body']['case_id']!=packet['case_id'] or requested[index-1]['body']['work_items']!=packet['work_items']:raise ValueError('Recovery case history changed')
  for role,source in packet['sources'].items():
   original=session.get(source['output_id'])
   if original['run_id']!=run or original['body']['role']!=role or source['output']!=original['body']['output'] or original['seq']>=inp['seq']:raise ValueError('Historical routing source changed')
  dis=[e for e in events if e['kind']=='submission_recovery' and e['body']['state']=='dispatched' and e['body']['leader_output_id']==out['id']]
  if len(dis)!=1 or dis[0]['body']['requests']!=out['body']['output']['requests']:raise ValueError('Routing dispatch receipt mismatch')
  reviews.append({'packet':packet,'output_id':out['id'],'input_id':inp['id'],'dispatch_event_id':dis[0]['id']})
 last=reviews[-1];packet=last['packet'];out=outputs[last['output_id']];inp=session.get(last['input_id']);routes=out['body']['output']['requests'];items=final['body']['output']['revision_requests']
 if packet['case_id']!='final_revision' or packet['work_items']!=items or inp['body']['payload'].get('repair') or len(groups[len(groups)])!=1:raise ValueError('No remaining first-routing correction at the final stage')
 if not final['seq']<inp['seq'] or {q['id'] for q in routes}!={q['id'] for q in items} or len(routes)!=len(items):raise ValueError('Final routing does not cover its validation')
 allowed={'recovery_leader_input','recovery_leader_output','recovery_leader_validation','submission_recovery','recovery_research_dispatch','failed','continuation_failed'}
 if any(e['seq']>=inp['seq'] and e['kind'] not in allowed for e in events):raise ValueError('Author/research work progressed after the pending routing')
 if any(e['kind']=='submission_recovery' and e['seq']>=inp['seq'] and e['body']['state'] not in ('dispatched','author_requested','diagnostic_context_added') for e in events):raise ValueError('Final routing already transitioned')
 current=history.market_input(session.get(start['body']['market_id'])['body'],start['body']['history_scope']);facts={f['id']:f for f in current['facts']}
 for f in plan['facts']:
  if f['id'] in facts and facts[f['id']]!=f:raise ValueError('Current fact collision')
  facts[f['id']]=f
 previous=session.get(start['body']['previous_id']);catalog=historical_catalog(session,previous,list(facts.values()),as_of)
 problems=routing_issues(out['body']['output'],dict(packet,historical_catalog=catalog))
 if not problems or any(x['code']!='historical_current_collision' for x in problems):raise ValueError('Only verified current/historical observation conflicts can be re-routed')
 authors=[];pending_dispatches=[]
 for q in routes:
  item=next(i for i in items if i['id']==q['id'])
  if q['needs_research'] or any(q[k]!=item[k] for k in ('target_role','source_output_id')):raise ValueError('Pending routing must have no new research')
  expected=dict(q,kind=item['kind'],issue_path=item['issue_path'],reason=item['reason'],question_ids=item.get('question_ids',[]),fact_ids=item.get('fact_ids',[]))
  req=[e for e in events if e['kind']=='submission_recovery' and e['body']['state']=='author_requested' and e['seq']>out['seq'] and e['body']['request']['id']==q['id']]
  if len(req)!=1 or req[0]['body']['request']!=expected:raise ValueError('Pending author request changed')
  authors.append(req[0])
  ds=[e for e in events if e['kind']=='recovery_research_dispatch' and e['body']['leader_output_id']==out['id'] and e['body']['request_id']==q['id']]
  if len(ds)!=(1 if q['historical_sources'] else 0):raise ValueError('Pending source dispatch changed')
  pending_dispatches+=ds
  for source in q['historical_sources']:
   for fact in historical_facts(session,source['completed_id'],source['fact_ids'],as_of,start['body']['history_scope'],start['body']['mode'],start['seq']):
    if fact['id'] not in facts:raise ValueError('Pending routing requires new material, outside this continuation')
 if len([e for e in events if e['kind']=='submission_recovery' and e['body']['state']=='author_requested' and e['seq']>out['seq']])!=len(authors):raise ValueError('Extra pending author request')
 all_dispatches=[e for e in events if e['kind']=='recovery_research_dispatch']
 pending_ids={e['id'] for e in pending_dispatches}
 if {e['id'] for e in all_dispatches if e['seq']>out['seq']}!=pending_ids:raise ValueError('Extra pending research dispatch')
 for d in all_dispatches:
  terminals=[e for e in events if e['kind'] in ('recovery_research_return','recovery_research_cancelled') and e['body']['dispatch_id']==d['id']]
  if len(terminals)!=(0 if d['id'] in pending_ids else 1):raise ValueError('Earlier dispatch completion is ambiguous')
 # Verify restoration now, before any write/model call; the real coordinator repeats it.
 check=Coordinator(session,None,as_of,run,'')
 for review in reviews:check.restore_review(review['packet'],review['output_id'])
 deliveries={}
 for role in latest:
  for out in by_role[role]:
   original=session.get(out['body']['input_id'])['body']['payload']
   delivered={f['id'] for f in original['market']['facts']}
   for q in original.get('revision_instructions',[]):
    ids=set(q.get('fact_ids',[]))
    if not ids<=delivered:raise ValueError('Accepted author correction omitted requested facts')
    deliveries.setdefault(role,set()).update(ids)
 return {'reviews':reviews,'packet':packet,'leader_output_id':last['output_id'],
  'author_requests':authors,'pending_dispatches':pending_dispatches,'issues':problems,
  'perspectives':{r:(copy.deepcopy(o['body']['output']),o['id']) for r,o in latest.items()},
  'role_fact_deliveries':{r:sorted(ids) for r,ids in deliveries.items()},'validation_output_id':final['id']}
