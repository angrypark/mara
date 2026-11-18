"""Request history -> process review -> scoped knowledge -> explicit usage receipts."""
import copy
from collections import Counter
from .contracts import ContractError,validate,schema
from .decision_calibration import CalibrationError

VERSION='mara.research-learning/1.0'
INSTRUCTION='이전 요청 원장은 당시 과정의 근거이며 현재 시장의 독립 증거가 아니에요. 자료 접근/미추출/배정/계산 실패와 미래 가정의 불확실성을 구분하세요. 반복 공백·중복·우선순위·수용조건·계산/분석의 구체 사례를 request_ids에 연결해 research_learning을 작성하세요. 변화를 만들 이유가 없으면 no_change와 이유를 기록하세요. 역할의 결론이나 매수/보류 자체를 점수화하거나 반복을 독립 근거로 세지 마세요. 개선은 적용 조건과 검증 방법을 가져야 하고 도구/가이드 코드 변경은 자동 실행하지 않아요.'


def history(session,completed):
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
 return {'schema_version':VERSION,'source_completed_id':completed['id'],'as_of':completed['effective'],
  'final_action':body['proposal']['action'],'requests':rows,'tool_failures':failures,
  'status_counts':dict(Counter(x['status'] for x in rows)),'instruction':INSTRUCTION,
  'source_scope':'Complete immediate-predecessor request records; older originals remain in their completed events. Process observations are not additional market facts or independent investment confirmations.'}


def for_role(value,role):
 result=copy.deepcopy(value)
 if role in ('buffett','marks','bogle','wood'):
  result['requests']=[r for r in result['requests'] if r['requester']==role]
  result['tool_failures']=[r for r in result['tool_failures'] if r['role']==role]
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
 if rows and not reviews:raise CalibrationError('learning_review','Read the request history and record at least one evidenced proposal or no_change judgment')
 available={r['request_id'] for r in rows}
 for review in reviews:
  if not set(review['request_ids'])<=available:raise CalibrationError('learning_sources','Learning cites an unknown prior request')
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
