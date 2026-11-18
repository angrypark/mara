"""Request history -> process review -> scoped knowledge -> explicit usage receipts."""
import copy,re
from collections import Counter
from .contracts import ContractError,validate,schema
from .decision_calibration import CalibrationError

VERSION='mara.research-learning/1.0'
INSTRUCTION='이전 요청 원장은 당시 과정의 근거이며 현재 시장의 독립 증거가 아니에요. 자료 접근/미추출/배정/계산 실패와 미래 가정의 불확실성을 구분하세요. 반복 공백·중복·우선순위·수용조건·계산/분석의 구체 사례를 request_ids에 연결해 research_learning을 작성하세요. 변화를 만들 이유가 없으면 no_change와 이유를 기록하세요. 역할의 결론이나 매수/보류 자체를 점수화하거나 반복을 독립 근거로 세지 마세요. 개선은 적용 조건과 검증 방법을 가져야 하고 도구/가이드 코드 변경은 자동 실행하지 않아요.'

def memory_feedback(session,outputs):
 rows=[]
 for receipt in outputs:
  event=session.get(receipt['output_id']);body=event['body'];inp=session.get(body['input_id'])
  for i,conflict in enumerate(body['output'].get('conflicts',[])):
   rows.append({'id':'memory-'+event['id']+'-'+str(i),'memory_output_id':event['id'],
    'reflection_output_id':inp['body']['payload'].get('reflection_id'),
    'recorded_at':event['recorded'],'as_of':event['effective'],'text':conflict})
 return {'conflicts':rows,'instruction':'기억 정리 역할이 남긴 이견·미해결 조건이에요. 시장 사실이나 독립 확인으로 승격하지 않아요. 리더와 검증은 각 ID를 memory_reviews로 반영/미해결/비관련 평가하고 결정 영향과 다음 확인을 남겨요. incorporated는 고려·반영이며 사실 해결이 아니에요. 선택의 사실·계산 공백은 decision_gaps에도 유지해요.'}


def process_failures(session,completed,as_of,before_seq):
 """Bounded process-only snapshot. Never copy failed investment outputs."""
 events=[e for kind in ('run_started','completed','failed') for e in session.events(kind,as_of) if e['seq']<before_seq]
 starts={e['run_id']:e for e in events if e['kind']=='run_started'}
 finished={e['run_id'] for e in events if e['kind']=='completed'}
 boundary=completed['body'].get('history_scope',{}).get('after_seq',0)
 failed=[]
 for e in events:
  start=starts.get(e['run_id'])
  if e['kind']!='failed' or e['seq']<=completed['seq'] or not start or e['run_id'] in finished:continue
  b=start['body']
  if b.get('previous_id')==completed['id'] and b.get('mode')==completed['body'].get('mode') and b.get('history_scope',{}).get('after_seq',0)==boundary:failed.append(e)
 # A recovered completed execution may reuse a prefix of a failed run.
 # Carry only that terminal diagnostic; replayed rejection events already
 # belong to the completed run and must not become independent duplicates.
 recovered={};carry_links={}
 failures_by_id={e['id']:e for e in events if e['kind']=='failed'}
 completed_start=starts.get(completed['run_id'])
 for receipt in session.events('execution_prefix_reuse',as_of):
  if receipt['run_id']!=completed['run_id'] or receipt['seq']>=completed['seq'] or not completed_start:continue
  e=failures_by_id.get(receipt['body'].get('source_failed_id'));source=starts.get(e['run_id']) if e else None
  if not e or not source or not (e['seq']<completed_start['seq']<receipt['seq']) or e['run_id'] in finished:continue
  b=source['body'];current=completed_start['body']
  if (b.get('previous_id') in {item['id'] for item in events if item['kind']=='completed'}
      and receipt['body'].get('source_run_id')==e['run_id']
      and b.get('previous_id')==current.get('previous_id')==completed['body'].get('previous_id')
      and b.get('mode')==current.get('mode')==completed['body'].get('mode')
      and b.get('history_scope',{}).get('after_seq',0)==current.get('history_scope',{}).get('after_seq',0)==boundary):
   recovered[e['id']]=e
   carry_links.setdefault(e['id'],{'receipt_id':receipt['id'],'completed_id':completed['id'],
    'source_status':'failed','continuation_status':'completed','scope':'Original failure remains failed; its prefix was reused by this completed execution. No root cause or benefit inferred.'})
 runs={completed['run_id']}|{e['run_id'] for e in failed}
 query='SELECT * FROM events WHERE owner=? AND seq<? AND effective<=? AND kind IN (\'agent_input\',\'agent_validation\') AND run_id IN ('+','.join('?' for _ in runs)+') ORDER BY seq'
 events += [session.decode(row) for row in session.store.db.execute(query,(session.owner,before_seq,as_of,*sorted(runs)))]
 rejected=[e for e in events if e['run_id'] in runs and e['kind']=='agent_validation' and e['body']['status']=='rejected']
 by_output={e['body']['output_id']:e for e in rejected}
 corrections={e['body']['payload'].get('output_feedback',{}).get('rejected_output_id'):e for e in events if e['kind']=='agent_input' and e['run_id'] in runs}
 accepted={e['body']['input_id'] for e in events if e['kind']=='agent_validation' and e['body']['status']=='accepted'}
 rejected_inputs={e['body']['input_id'] for e in rejected}
 rows=[]
 for e in rejected:
  b=e['body'];inp=session.get(b['input_id']);correction=corrections.get(b['output_id']);feedback=correction['body']['payload']['output_feedback'] if correction else {}
  prior=by_output.get(inp['body']['payload'].get('output_feedback',{}).get('rejected_output_id'))
  stored_detail=b.get('subtype')
  detail=stored_detail or feedback.get('decision_policy_error',{}).get('code') or feedback.get('question_error',{}).get('reason_code')
  if not detail and isinstance(feedback.get('evidence_feedback_error'),dict) and {'required_response_ids','pending_request_ids'}<=set(feedback['evidence_feedback_error']):detail='evidence_assessment_coverage'
  if not isinstance(detail,str) or not re.fullmatch('[a-z_]{1,80}',detail):detail=None
  rows.append({'failure_id':e['id'],'case_id':prior['id'] if prior else e['id'],'kind':'output_rejection','role':b['role'],
   'stage':inp['body']['payload'].get('analysis_stage'),'code':b['code'],'subtype':detail,
   'diagnostic_input_id':correction['id'] if detail and correction and not stored_detail else None,
   'diagnostic_source_id':e['id'] if stored_detail else correction['id'] if detail and correction else None,'recorded_at':e['recorded'],'as_of':e['effective'],
   'run_state':'failed' if e['run_id']!=completed['run_id'] else 'completed',
   'correction_status':'accepted' if correction and correction['id'] in accepted else 'rejected' if correction and correction['id'] in rejected_inputs else 'not_completed' if correction else 'not_recorded'})
 for e in {e['id']:e for e in failed+list(recovered.values())}.values():
  rows.append({'failure_id':e['id'],'case_id':e['id'],'kind':'execution_failure','role':'runtime','stage':'runtime',
   'code':e['body']['error_type'],'subtype':None,'recorded_at':e['recorded'],'as_of':e['effective'],'run_state':'failed','correction_status':'not_completed'})
 for row in rows:
  if row['failure_id'] in carry_links:row['recovery']=carry_links[row['failure_id']]
 # Independent post-run findings are separate process observations, not model
 # failures, market facts, new model judgments, or changed investment decisions.
 from .report_audit import findings as audit_findings
 for finding in audit_findings(session,completed,before_seq):
  rows.append({'failure_id':finding['event_id'],'case_id':finding['event_id'],'kind':'independent_post_run_review',
   'role':finding['role'],'stage':'post_run_review','code':'independent_audit','subtype':finding['code'],
   'recorded_at':finding['recorded_at'],'as_of':completed['effective'],'run_state':'completed','correction_status':'documented_independently',
   'source_completed_id':completed['id'],'source_output_id':finding['source_output_id'],
   'review_summary':finding['review_summary'],
   'review_detail':{key:copy.deepcopy(finding[key]) for key in ('classification','correction_or_review','source_path','source_body_sha256','original_sha256','fact_hashes','verification','reviewer','limits') if key in finding},
   'review_scope':'Process review only; not a market fact, independent financial confirmation, model self-correction, changed decision or investment performance.'})
 # Terminal failures first, then most recent diagnostics. Originals stay in DB.
 selected=sorted(rows,key=lambda r:(r['kind']=='execution_failure',r['recorded_at']),reverse=True)[:60]
 return {'items':selected,'available':len(rows),'selected':len(selected),'omitted':len(rows)-len(selected),
  'selection':'Terminal failures, then recent rejection diagnostics; maximum 60. Same case_id is one failure with repair, not independent confirmations.',
  'scope':'Previous completed run, its verified recovered terminal failure, and later terminal failed runs linked to it; same owner/history/mode, before the new run start. Process evidence only; no failed investment judgment.'}


def history(session,completed,as_of=None,before_seq=None):
 body=completed['body'];rows=copy.deepcopy(body.get('evidence_feedback',{}).get('exchanges',[]))
 assessments=[e for e in session.events('evidence_feedback_assessment') if e['run_id']==completed['run_id'] and e['seq']<=completed['seq']]
 for row in rows:
  row['assessment_history']=[{'event_id':e['id'],'recorded_at':e['recorded'],**copy.deepcopy(e['body'])} for e in assessments if e['body']['request_id']==row['request_id']]
  row.setdefault('recipient','evidence')
  source=session.get(row['source_output_id']);row.setdefault('requested_at',source['recorded'])
  if row.get('request_event_id'):row['queued_at']=session.get(row['request_event_id'])['recorded']
  if row.get('response_event_id'):
   ret=session.get(row['response_event_id']);row['responded_at']=ret['recorded']
   row['supplier_input_id']=ret['body']['supplier_input_id'];row['tool_event_ids']=ret['body']['tool_event_ids']
  if row.get('assessment_event_id'):
   assess=session.get(row['assessment_event_id']);row['assessed_at']=assess['recorded'];row['requester_input_id']=assess['body']['requester_input_id'];row['requester_output_id']=assess['body']['requester_output_id']
 failures=[]
 for e in session.events('research_tool_failure'):
  if e['run_id']==completed['run_id'] and e['seq']<=completed['seq']:
   result=e['body'].get('result',{})
   failures.append({'event_id':e['id'],'role':e['body']['role'],'tool':e['body'].get('call',{}).get('tool'),'status':result.get('status'),'reason':result.get('reason')})
 diagnostics=process_failures(session,completed,as_of or completed['effective'],before_seq or completed['seq']+1)
 return {'schema_version':VERSION,'source_completed_id':completed['id'],'as_of':completed['effective'],'process_failures':diagnostics,
  'final_action':body['proposal']['action'],'requests':rows,'tool_failures':failures,
  'status_counts':dict(Counter(x['status'] for x in rows)),'instruction':INSTRUCTION,
  'source_scope':'Complete immediate-predecessor request records; older originals remain in their completed events. Process observations are not additional market facts or independent investment confirmations.'}


def for_role(value,role):
 result=copy.deepcopy(value)
 if role in ('buffett','marks','bogle','wood'):
  result['requests']=[r for r in result['requests'] if r['requester']==role]
  result['tool_failures']=[r for r in result['tool_failures'] if r['role']==role]
  if result.get('process_failures'):
   result['process_failures']['items']=[r for r in result['process_failures']['items'] if r['role'] in (role,'runtime')]
   result['process_failures']['projection']='Own rejection diagnostics and runtime failure types only; counts describe the original snapshot.'
  result['projection']='Own prior requests and process counts; other investors\' assessments are omitted.'
 elif role=='evidence':
  for r in result['requests']:
   r.pop('assessment',None);r.pop('assessment_history',None);r.pop('final_decision',None)
  result['projection']='Research needs and supplier results, without peer investment assessments.'
 return result

def reflection_for_role(value,role):
 result=copy.deepcopy(value)
 if result and role in ('buffett','marks','bogle','wood'):
  result['perspective_review']={role:result.get('perspective_review',{}).get(role)}
  result['projection']='Own perspective review plus shared retrospective process lessons; never independent current-market confirmation.'
 return result


def validate_reflection(out,payload):
 if not payload.get('decision_policy'):return
 hist=payload.get('research_feedback_history') or {};rows=hist.get('requests',[])
 reviews=out.get('research_learning',[]);ids=[r['id'] for r in reviews]
 if len(ids)!=len(set(ids)):raise CalibrationError('learning_ids','Research learning review IDs must be unique')
 failures={r['failure_id'] for r in hist.get('process_failures',{}).get('items',[])}
 if (rows or failures) and not reviews:raise CalibrationError('learning_review','Read the process history and record at least one evidenced proposal or no_change judgment')
 available={r['request_id'] for r in rows}
 for review in reviews:
  if not set(review['request_ids'])<=available:raise CalibrationError('learning_sources','Learning cites an unknown prior request')
  if not set(review.get('failure_ids',[]))<=failures or not (review['request_ids'] or review.get('failure_ids')):raise CalibrationError('learning_sources','Learning requires supplied request or process-failure evidence')
  if review['category'] in ('duplicate_request','repeated_gap') and sum(r['request_id'] in review['request_ids'] for r in rows)<2:
   raise CalibrationError('learning_repetition','Repeated/duplicate finding requires multiple request records')


def validate_memory(out,payload):
 ops=out.get('operations',[])
 items=payload.get('review_items',[])+payload.get('knowledge',{}).get('items',[])
 if 'allowed_refs' in payload:
  items=payload.get('review_items',[])+payload.get('knowledge',{}).get('items',[])
  keys={r['key'] for r in items};refs=set(payload['allowed_refs'])
  for item in items:refs.update(item.get('refs',[]));refs.add(item.get('event_id'))
  for op in ops:
   validate(op,schema('knowledge-operation'))
   if op['action']=='restore':raise ContractError('Model memory cannot restore an unreviewed historic version')
   if op['action']!='add' and op['key'] not in keys:raise ContractError('Memory operation targets knowledge not supplied for review')
   if not set(op.get('refs',[])+op.get('invalidating_refs',[]))<=refs:raise ContractError('Memory operation cites an event outside allowed_refs/reviewed provenance')
 if not payload.get('decision_policy'):return
 proposals={r['id']:r for r in payload.get('learning_proposals',[])}
 rows=out.get('learning_applications',[]);ids=[r['review_id'] for r in rows]
 if len(ids)!=len(set(ids)) or set(ids)!=set(proposals):raise CalibrationError('learning_disposition','Explicitly apply, merge, defer or reject every learning_proposals ID once')
 for row in rows:
  ix=row['operation_indices'];applied=row['disposition'] in ('apply','merge_existing')
  if applied!=bool(ix) or any(i>=len(ops) for i in ix):raise CalibrationError('learning_operation','Applied lessons must link real operation indices; deferred/rejected lessons have none')
  for i in ix:
   op=ops[i]
   if op['action'] not in ('add','revise','merge'):raise CalibrationError('learning_operation','A learning application must add/revise/merge conditional knowledge')
   if payload.get('reflection_id') not in op.get('refs',[]):raise CalibrationError('learning_provenance','Applied process knowledge must cite the actual reflection output event')
   effective=next((dict(item) for item in items if item['key']==op.get('key')),{})
   effective.update(op)
   if effective.get('category') not in ('lesson','hypothesis'):raise CalibrationError('learning_category','Process review cannot promote an investment fact or immutable principle')
   if proposals[row['review_id']]['status']=='no_change':raise CalibrationError('learning_no_change','A no_change review must be deferred/rejected with a reason, not applied as a new lesson')
   if proposals[row['review_id']]['status']=='needs_test' and (effective.get('category')!='hypothesis' or not effective.get('valid_until')):
    raise CalibrationError('untested_learning','An untested proposal can only be stored as an expiring hypothesis')


def usage_receipts(session,run_id):
 result=[]
 for e in session.events('agent_validation'):
  if e['run_id']!=run_id or e['body']['status']!='accepted':continue
  out=session.get(e['body']['output_id'])['body']['output'];inp=session.get(e['body']['input_id'])
  for row in out.get('knowledge_feedback',[]):
   result.append({'role':e['body']['role'],'input_id':inp['id'],'output_id':e['body']['output_id'],
    'knowledge_event_id':row['knowledge_event_id'],'status':row['status'],'effect':row['effect'],'fact_ids':row['fact_ids'],
    'scope':'Model-reported use linked to delivered knowledge, not proof of improved investment outcomes.'})
 for e in session.events('research_plan_accepted'):
  if e['run_id']!=run_id:continue
  for row in e['body'].get('knowledge_feedback',[]):
   result.append({'role':e['body']['role'],'stage':'research_plan','input_id':e['body']['input_id'],'output_id':e['body']['output_id'],**copy.deepcopy(row),
    'scope':'Planner-reported use linked to delivered knowledge and planned calls; not evidence of improved investment performance.'})
 return result
