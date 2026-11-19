"""Verified initial-perspective continuation, never regeneration of accepted prefixes."""
import copy,hashlib,os,subprocess
from pathlib import Path
from .domain import dumps
from . import history
from .registry import personas
from .agents import validate_output
from .contracts import validate
from .codex_model import ProviderSubmissionError

VERSION='mara.execution-continuation/1.0'
LEGACY_MESSAGE='Codex 분석 결과가 필요한 JSON 형식에 맞지 않아요. 다시 시도해주세요.'

def resource_fingerprint():
 root=Path(__file__).resolve().parent.parent
 return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for directory in ('guides','contracts') for p in sorted((root/directory).rglob('*')) if p.is_file() and (directory!='contracts' or p.suffix=='.json')}

def process_birth(pid):
 try:return subprocess.check_output(['ps','-p',str(pid),'-o','lstart='],text=True,stderr=subprocess.DEVNULL).strip()
 except (OSError,subprocess.CalledProcessError):return ''

def alive(body):
 return bool(body.get('pid') and body.get('process_birth') and process_birth(body['pid'])==body['process_birth'])

def prepare(session,model,failed_id,response_input_id,raw_response,resource_manifest=None,pending_dispatch=False,pending_repair=False):
 """Read-only eligibility, prefix and exact pending-input verification."""
 failure=session.get(failed_id);run=failure['run_id']
 coordinated=pending_dispatch or pending_repair
 if pending_dispatch and pending_repair:raise ValueError('Choose one continuation boundary')
 if pending_repair:
  from .codex_model import INPUT_LIMIT_MESSAGE
  if failure['kind']!='failed' or failure['body'].get('error_type')!='CodexError' or failure['body'].get('message')!=INPUT_LIMIT_MESSAGE:raise ValueError('Only the prepared input-limit repair boundary is supported')
 elif pending_dispatch:
  if failure['kind']!='failed' or failure['body'].get('error_type')!='RecoveryIncomplete' or failure['body'].get('recovery',{}).get('reason')!='historical_fact_collision':raise ValueError('Only interrupted historical delivery is supported')
 elif failure['kind']!='failed' or failure['body'].get('error_type')!='CodexError' or failure['body'].get('message')!=LEGACY_MESSAGE:
  raise ValueError('Continuation requires the known legacy provider-submission boundary failure')
 ev=[session.decode(r) for r in session.store.db.execute('SELECT * FROM events WHERE owner=? AND run_id=? ORDER BY seq',(session.owner,run))]
 if any(e['kind']=='completed' or e['kind']=='continuation_started' and (not coordinated or e['body'].get('source_failed_id')==failed_id) for e in ev):raise ValueError('Execution already completed or continuation already attempted')
 failures=[e for e in ev if e['kind']=='failed']
 if failures[-1]['id']!=failed_id or not coordinated and len(failures)!=1:raise ValueError('Ambiguous original failure sequence')
 if coordinated:
  for old in (e for e in ev if e['kind']=='continuation_started'):
   if not any(e['kind']=='continuation_failed' and e['body']['continuation_id']==old['id'] and e['seq']<failure['seq']+2 for e in ev):raise ValueError('Prior continuation is not terminal')
 starts=[e for e in ev if e['kind']=='run_started']
 if len(starts)!=1:raise ValueError('Exactly one original start required')
 start=starts[0];b=start['body']
 old_resources=next((e['body']['resources'] for e in ev if e['kind']=='continuation_started'),None)
 resources=b.get('runtime_resources') or old_resources or resource_manifest
 if not resources or resources!=resource_fingerprint():raise ValueError('Original guide/contract resource snapshot differs or is unavailable')
 if b['mode']!=model.mode or b['history_scope']!=history.scope(session):raise ValueError('Continuation owner mode/history changed')
 previous=history.latest(session,'completed',boundary=b['history_scope'])
 if (previous['id'] if previous else None)!=b['previous_id']:raise ValueError('A newer completed report exists')
 if b.get('amendment') or b.get('improvement') or b.get('external_review'):raise ValueError('Frozen/review branch continuation is unsupported')
 sensitive={'profile','actual','cashflow','history_reset','knowledge','user_persona','clarification_answer','quality_stability_result'}
 for kind in sensitive:
  if any(e['seq']>start['seq'] and (kind!='knowledge' or e['run_id']!=run or e['seq']>failure['seq']) for e in session.events(kind)):raise ValueError('Personal/history/knowledge state changed outside the verified prefix')
 if any(e['kind']=='evidence_feedback_dispatch' or not coordinated and e['kind'] in ('recovery_leader_input','recovery_research_dispatch') for e in ev):raise ValueError('Continuation after feedback or coordinated recovery is unsupported')
 if not coordinated and any(e['kind']=='agent_input' and e['body']['role'] in ('leader','validation') for e in ev):raise ValueError('Continuation after synthesis/validation is unsupported')
 inputs=[e for e in ev if e['kind']=='agent_input'];pending=inputs[-1];role=pending['body']['role']
 if pending_repair:
  if role!='leader' or pending['body']['payload']['analysis_stage']!='proposal_synthesis' or not pending['body']['payload'].get('output_feedback'):raise ValueError('Only an unfinished leader correction is supported')
  if any(e['kind']=='continuation_started' and e['body'].get('source_input_id')==pending['id'] for e in ev):raise ValueError('This pending correction was already continued')
 elif pending_dispatch:
  if role!='validation' or pending['body']['payload']['analysis_stage'] not in ('perspective_validation','final_validation'):raise ValueError('Only a pre-feedback validation dispatch is supported')
  if any(e['kind']=='continuation_started' and e['body'].get('source_input_id')==pending['id'] for e in ev):raise ValueError('This dispatch continuation was already attempted')
 else:
  if pending['id']!=response_input_id or role not in personas() or pending['seq']>=failure['seq']:raise ValueError('Response must belong to the first unfinished perspective input')
  if any(e['kind']=='agent_output' and e['body']['input_id']==pending['id'] for e in ev):raise ValueError('Pending input already has an output')
  if not isinstance(raw_response,str) or not raw_response or len(raw_response.encode())>524288:raise ValueError('Bounded original unverified response required')
 if any(pending['body']['payload'].get(k) for k in (('submission_repair','revision_instructions') if pending_repair else ('output_feedback','submission_repair','revision_instructions'))):raise ValueError('Only the supported submission boundary may continue; repair budget cannot reset')
 if pending['body']['provider']!=model.identity:raise ValueError('Provider identity changed')
 accepted=[];by_role={}
 for e in ev:
  if e['kind']!='agent_validation' or e['body']['status']!='accepted':continue
  out=session.get(e['body']['output_id']);inp=session.get(out['body']['input_id'])
  if any(x['owner']!=session.owner or x['run_id']!=run for x in (out,inp)) or not inp['seq']<out['seq']<e['seq']<failure['seq']:raise ValueError('Accepted prefix lineage mismatch')
  if out['body'].get('provider_failure'):raise ValueError('Unattested provider result cannot be reused')
  if hashlib.sha256(inp['body']['guide'].encode()).hexdigest()!=inp['body']['guide_hash']:raise ValueError('Original guide hash mismatch')
  validate(out['body']['output'],inp['body']['contract']);validate_output(out['body']['role'],out['body']['output'],inp['body']['payload'])
  accepted.append(out);by_role.setdefault(out['body']['role'],[]).append(out)
 final_dispatch=pending_dispatch and pending['body']['payload']['analysis_stage']=='final_validation';advanced=final_dispatch or pending_repair
 roles=list(personas());expected=set(roles)|({'validation','leader'} if advanced else {'validation'}) if coordinated else set(roles[:roles.index(role)])
 if {r for r in by_role if r in roles or coordinated and r in ('validation','leader')}!=expected or not {'context','evidence'}<=by_role.keys():raise ValueError('Accepted perspectives must be an uninterrupted prefix')
 if any(len(by_role.get(r,[]))!=1 for r in ({'context','evidence'} if advanced else expected|{'context','evidence'})):raise ValueError('Ambiguous accepted prefix')
 if by_role['context'][0]['body']['output']['missing']:raise ValueError('Context remains unresolved')
 audit=[e for e in ev if e['kind']=='pruning_audit']
 if len(audit)!=1:raise ValueError('Original knowledge pruning must be complete exactly once')
 h=[e for e in ev if e['kind']=='research_feedback_history'];scope=[e for e in ev if e['kind']=='decision_scope']
 if len(scope)!=1 or (previous and len(h)!=1):raise ValueError('Original scope/history snapshot unavailable')
 learning={'status':'no_predecessor','history_event_id':h[0]['id'] if h else None,'source_completed_id':b['previous_id'],
  'reflection_output_id':None,'memory_outputs':[],'applications':[]}
 reflection=None
 if previous:
  if len(by_role.get('reflection',[]))!=1 or not by_role.get('memory'):raise ValueError('Original learning prefix is incomplete')
  ref=by_role['reflection'][0];reflection=ref['body']['output']
  learning.update(status='reviewed',reflection_output_id=ref['id'],reflection_input_id=ref['body']['input_id'])
  for out in by_role['memory']:
   value=out['body']['output'];learning['memory_outputs'].append({'output_id':out['id'],'input_id':out['body']['input_id'],'learning_applications':value.get('learning_applications',[]),'conflicts':value.get('conflicts',[])})
   for i,op in enumerate(value['operations']):
    matches=[e for e in ev if e['kind']=='research_learning_application' and e['body']['memory_output_id']==out['id'] and e['body']['operation_index']==i]
    if len(matches)!=1:raise ValueError('Learning operation lacks exactly one original application')
    receipt=matches[0];knowledge=session.get(receipt['body']['knowledge_event_id'])
    if knowledge['run_id']!=run or knowledge['kind']!='knowledge' or knowledge['body']['action']!=op['action'] or not out['seq']<knowledge['seq']<receipt['seq']<audit[0]['seq']:raise ValueError('Learning application lineage mismatch')
    learning['applications'].append(dict(receipt['body'],event_id=receipt['id']))
 cache={r:(copy.deepcopy(by_role[r][-1]['body']['output']),by_role[r][-1]['id']) for r in ({'context','evidence'} if advanced else expected|{'context','evidence'})}
 plan={'version':VERSION,'kind':'prepared_repair' if pending_repair else 'historical_dispatch' if pending_dispatch else 'initial_submission','phase':'proposal_synthesis' if pending_repair else 'final_validation' if final_dispatch else 'perspective_validation' if pending_dispatch else 'initial_submission','failure':failure,'start':start,'pending':pending,'raw_response':raw_response or '','cache':cache,
  'decision_scope':scope[0]['body'],'research_history':h[0]['body'] if h else None,'learning_cycle':learning,'reflection':reflection,
  'pruning_audit_id':audit[0]['id'],'user_persona':pending['body']['payload']['user_persona'],
  'facts':[e['body']['fact'] for e in ev if e['kind']=='research_evidence'],
  'prefix_output_ids':[e['id'] for e in accepted],
  'resources':resources,'resource_provenance':'original_run_snapshot' if b.get('runtime_resources') else 'caller_provided_legacy_snapshot',
  'prefix_digest':hashlib.sha256(dumps([{k:e[k] for k in ('id','digest')} for e in ev if e['seq']<=failure['seq']]).encode()).hexdigest()}
 if pending_repair:
  from .submission_continuation import verify_repair
  plan['repair_submission']=verify_repair(session,model,plan,ev,by_role)
 elif final_dispatch:
  from .dispatch_continuation import verify_final_dispatch
  plan['final_dispatch']=verify_final_dispatch(session,plan,ev,by_role)
 elif pending_dispatch:plan['dispatch']=verify_dispatch(session,plan,ev,by_role)
 plan['source_failed_ids']=[e['id'] for e in failures]
 return plan

def verify_dispatch(session,plan,events,by_role):
 """Only an unmodified first leader routing with already-delivered observations."""
 from .submission_recovery import historical_facts,same_observation,contract
 start=plan['start'];failure=plan['failure'];run=start['run_id'];as_of=start['effective']
 validators=by_role.get('validation',[])
 if len(validators)!=1 or validators[0]['body']['input_id']!=plan['pending']['id']:raise ValueError('Ambiguous source validation')
 revisions=validators[0]['body']['output'].get('revision_requests',[])
 inputs=[e for e in events if e['kind']=='recovery_leader_input'];outputs=[e for e in events if e['kind']=='recovery_leader_output']
 validations=[e for e in events if e['kind']=='recovery_leader_validation']
 if len(inputs)!=1 or len(outputs)!=1 or len(validations)!=1:raise ValueError('Only the first unambiguous leader dispatch is supported')
 inp,out,ver=inputs[0],outputs[0],validations[0];packet=inp['body']['payload'];routes=out['body']['output']
 if not validators[0]['seq']<inp['seq']<out['seq']<ver['seq']<failure['seq'] or out['body']['input_id']!=inp['id'] or ver['body'].get('output_id')!=out['id'] or ver['body']['status']!='accepted':raise ValueError('Leader dispatch lineage mismatch')
 if packet['case_id']!='perspective_revision' or packet['work_items']!=revisions or packet.get('diagnostic') or packet['budget']['reviews_used']!=1 or packet['budget']['case_round']!=1:raise ValueError('Coordinator state is outside the supported first review')
 if inp['body']['provider']!=session.get(plan['pending']['id'])['body']['provider']:raise ValueError('Routing provider changed')
 validate(routes,inp['body']['contract']);validate(routes,contract(revisions))
 if routes['decision']!='revise' or {q['id'] for q in routes['requests']}!={q['id'] for q in revisions} or len(routes['requests'])!=len(revisions):raise ValueError('Incomplete original routing')
 author_events=[e for e in events if e['kind']=='submission_recovery' and e['body']['state']=='author_requested']
 dispatch_events=[e for e in events if e['kind']=='recovery_research_dispatch']
 if len(author_events)!=len(routes['requests']) or len(dispatch_events)!=len(routes['requests']):raise ValueError('Extra or missing original author dispatch')
 if any(e['kind']=='recovery_research_return' and e['body']['dispatch_id'] not in {d['id'] for d in dispatch_events} for e in events):raise ValueError('Unlinked recovery return')
 for role,source in packet['sources'].items():
  original=by_role.get(role,[])
  if len(original)!=1 or source['output_id']!=original[0]['id'] or source['output']!=original[0]['body']['output']:raise ValueError('Routing source differs from accepted author')
 dis=[e for e in events if e['kind']=='submission_recovery' and e['body']['state']=='dispatched']
 if len(dis)!=1 or dis[0]['body']['leader_output_id']!=out['id'] or dis[0]['body']['requests']!=routes['requests']:raise ValueError('Routing receipt mismatch')
 allowed={'recovery_leader_input','recovery_leader_output','recovery_leader_validation','submission_recovery','recovery_research_dispatch','recovery_research_return','failed','continuation_failed'}
 if any(e['seq']>=inp['seq'] and e['kind'] not in allowed for e in events):raise ValueError('Work already progressed beyond the pending dispatch')
 if any(e['kind']=='submission_recovery' and e['seq']>=inp['seq'] and e['body']['state'] not in ('dispatched','author_requested','diagnostic_context_added') for e in events):raise ValueError('Unexpected coordinated recovery transition')
 m=history.market_input(session.get(start['body']['market_id'])['body'],start['body']['history_scope'])
 facts={f['id']:f for f in m['facts']}
 for f in plan['facts']:
  if f['id'] in facts and facts[f['id']]!=f:raise ValueError('Current observation collision')
  facts[f['id']]=f
 receipts={};difference=False;pending_count=0
 for q in routes['requests']:
  item=next(i for i in revisions if i['id']==q['id'])
  if q['needs_research'] or not q['historical_sources'] or any(q[k]!=item[k] for k in ('target_role','source_output_id')):raise ValueError('Only existing-observation author routing is supported')
  expected=dict(q,kind=item['kind'],issue_path=item['issue_path'],reason=item['reason'],question_ids=item.get('question_ids',[]),fact_ids=item.get('fact_ids',[]))
  requested=[e for e in events if e['kind']=='submission_recovery' and e['body']['state']=='author_requested' and e['body']['request']['id']==q['id']]
  dispatches=[e for e in events if e['kind']=='recovery_research_dispatch' and e['body']['request_id']==q['id']]
  if len(requested)!=1 or len(dispatches)!=1:raise ValueError('Ambiguous author request or research dispatch')
  req,dispatch=requested[0],dispatches[0]
  if req['body']['request']!=expected or dispatch['body']!={'leader_output_id':out['id'],'request_id':q['id'],'target_role':q['target_role']} or not dis[0]['seq']<req['seq']<dispatch['seq']:raise ValueError('Original request/dispatch mismatch')
  fact_ids=set(expected['fact_ids'])
  for source in q['historical_sources']:
   if source['completed_id'] not in {x['completed_id'] for x in packet['historical_catalog']}:raise ValueError('Historical source was not offered')
   for fact in historical_facts(session,source['completed_id'],source['fact_ids'],as_of,start['body']['history_scope'],start['body']['mode'],start['seq']):
    current=facts.get(fact['id'])
    if current is None or not same_observation(current,fact):raise ValueError('Historical observation differs or needs new research')
    difference=difference or current!=fact;fact_ids.add(fact['id'])
  returns=[e for e in events if e['kind']=='recovery_research_return' and e['body']['dispatch_id']==dispatch['id']]
  if len(returns)>1:raise ValueError('Duplicate original return')
  expected_return={'dispatch_id':dispatch['id'],'request_id':q['id'],'fact_ids':sorted(fact_ids)}
  if returns and (returns[0]['body']!=expected_return or returns[0]['seq']<=dispatch['seq']):raise ValueError('Original return differs from verified facts')
  if not returns:pending_count+=1
  receipts[q['id']]={'request_event_id':req['id'],'dispatch_id':dispatch['id'],'return_id':returns[0]['id'] if returns else None,'expected_instruction':expected}
 if not difference or pending_count!=1:raise ValueError('No single archival-pointer delivery interruption')
 return {'packet':packet,'leader_output_id':out['id'],'routes':routes['requests'],'receipts':receipts,'validation_output_id':validators[0]['id']}

def begin(session,plan):
 run=plan['start']['run_id'];as_of=plan['start']['effective'];pending=plan['pending']
 receipt={k:plan[k] for k in ('version','prefix_output_ids','prefix_digest','resources','resource_provenance')}
 receipt.update(kind=plan['kind'],phase=plan['phase'],source_failed_ids=plan['source_failed_ids'],source_failed_id=plan['failure']['id'],source_input_id=pending['id'],pid=os.getpid(),process_birth=process_birth(os.getpid()),
  source_status='failed',status='running',raw_response_sha256=hashlib.sha256(plan['raw_response'].encode()).hexdigest(),
  rule='Same original run and frozen submission; no accepted model regeneration, knowledge reapplication, budget reset or acceptance of the unverified response')
 cid=session.append('continuation_started',receipt,as_of,run)
 session.append('recovery',{'status':'resuming','continuation_id':cid,'pid':receipt['pid'],'process_birth':receipt['process_birth'],'source_failed_id':plan['failure']['id']},as_of,run)
 plan['receipt_id']=cid
 if plan['kind']!='initial_submission':return plan
 error=ProviderSubmissionError('legacy_completion_unverified',plan['raw_response'],{'root_cause':'unknown; original CLI trace unavailable'})
 oid=session.append('agent_output',{'role':pending['body']['role'],'input_id':pending['id'],'output':error.output,'provider_failure':error.diagnostic,
  'raw_provider_response':plan['raw_response'],'continuation_id':cid,'origin':'Preserved caller-supplied response paired with original unfinished input; never provider-attested'},as_of,run)
 from .submission import diagnostics
 diag=diagnostics(pending['body']['role'],error.output,pending['body']['payload'],error)
 session.append('agent_validation',{'role':pending['body']['role'],'input_id':pending['id'],'output_id':oid,'status':'rejected','code':'provider_submission','subtype':None,'attempt':1,'diagnostic':diag},as_of,run)
 plan['receipt_id']=cid;plan['feedback']={'code':'provider_submission','rejected_output_id':oid,'previous_output':error.output,'submission_diagnostic':diag,
  'instruction':'원 응답은 CLI 완료 확인이 없어 미수용 상태예요. 사실·계산·반론을 유지하며 원 계약에 맞는 전체 JSON을 새로 제출하세요. 이전 내용이 검증된 사실이라고 가정하지 않아요.'}
 return plan
