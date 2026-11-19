"""Leader-mediated, bounded revision routing. Never approves a rejected submission."""
import copy,hashlib
from .contracts import validate,ContractError
from .domain import dumps
from .submission import TEXT

VERSION='mara.submission-recovery/1.0'
MAX_MODEL_CALLS=180
MAX_REVIEWS=8
MAX_CASE_ROUNDS=2

def same_observation(left,right):
 """Retrieval metadata may differ; observation and archived-source identity may not."""
 if left==right:return True
 lr,rr=left.get('raw_refs'),right.get('raw_refs')
 if not isinstance(lr,list) or not isinstance(rr,list) or len(lr)!=len(rr):return False
 for a,b in zip(lr,rr):
  if a==b:continue
  if not isinstance(a,dict) or not isinstance(b,dict) or any(k not in a or k not in b or a[k]!=b[k] for k in ('source','sha256','bytes')):return False
  from datetime import datetime
  for ref in (a,b):
   if 'retrieved_at' in ref:
    try:
     if datetime.fromisoformat(ref['retrieved_at']).tzinfo is None:return False
    except (TypeError,ValueError):return False
 def normalized(fact):
  value=copy.deepcopy(fact)
  if isinstance(value.get('raw_refs'),list):
   value['raw_refs']=[{k:v for k,v in r.items() if k not in ('cache_hit','retrieved_at')} if isinstance(r,dict) else r for r in value['raw_refs']]
  return value
 return normalized(left)==normalized(right)

def case_progress(case_id,item,sources,diagnostic):
 from .submission import pointer
 descriptor={k:item.get(k) for k in ('target_role','issue_path','kind','question_ids')}
 key=case_id+':'+hashlib.sha256(dumps(descriptor).encode()).hexdigest()
 if diagnostic:
  progress={'code':diagnostic.get('code'),'issues':[{k:r.get(k) for k in ('code','path')} for r in diagnostic.get('issues',[])], 'semantic':diagnostic.get('semantic_diagnostic')}
 else:progress={'source_excerpt':pointer(sources[item['target_role']]['output'],item['issue_path'])}
 return key,hashlib.sha256(dumps(progress).encode()).hexdigest()

def reference_scope(session,output_id):
 """Resolve local array paths against the author's immutable input, not a peer's."""
 out=session.get(output_id);inp=session.get(out['body']['input_id']);p=inp['body']['payload'];mappings=[]
 for path,rows in (('/research_feedback_history/requests',p.get('research_feedback_history',{}).get('requests',[])),('/evidence_feedback',p.get('evidence_feedback',[]))):
  for index,row in enumerate(rows):
   request_id=row['request_id'];response=row.get('response')
   if response and response.get('request_id')!=request_id:raise ValueError('Original response/request identity mismatch')
   mappings.append({'path':path+'/'+str(index),'request_id':request_id,'question_id':row.get('question_id'),
    'response_request_id':response.get('request_id') if response else None,
    'response_sha256':hashlib.sha256(dumps(response).encode()).hexdigest() if response else None})
 return {'source_input_id':inp['id'],'source_input_digest':inp['digest'],'mappings':mappings,
  'rule':'상대 배열 경로는 이 원 작성자 입력 기준이에요. 검증자/리더 입력의 같은 배열 번호로 해석하지 마세요. 안정 request_id와 원 응답 hash로 대조하세요. 수정 요청은 진단이며 확정된 오류나 시장 사실이 아니에요. 원 입력상 정확한 인용이면 이를 반박하고 원 위치와 안정 ID를 명시할 수 있어요.'}

class RecoveryIncomplete(ContractError):
 def __init__(self,reason):
  self.diagnostic={'kind':'system_incomplete','reason':reason,'investment_decision':False}
  super().__init__('Submission recovery incomplete: '+reason)
 @property
 def message(self):
  from .registry import agent
  role=self.diagnostic.get('role');name=agent(role)['label']+' ' if role else ''
  return name+'분석 복구를 완료하지 못했어요. 사유: '+self.diagnostic['reason']+'. 새 투자 판단은 채택하지 않았고 원 제출과 교정 이력은 보존했어요.'

def guard(session,run_id,as_of):
 kinds=('agent_input','research_plan_input','recovery_leader_input','report_editor_input')
 n=session.store.db.execute('SELECT count(*) FROM events WHERE owner=? AND run_id=? AND kind IN (?,?,?,?)',(session.owner,run_id,*kinds)).fetchone()[0]
 if n>=MAX_MODEL_CALLS:
  session.append('submission_recovery',{'version':VERSION,'state':'blocked','reason':'global_model_call_budget','calls':n},as_of,run_id)
  raise RecoveryIncomplete('global_model_call_budget')

def contract(work_items):
 request={'type':'object','additionalProperties':False,'properties':{
  'id':dict(TEXT,enum=[r['id'] for r in work_items]),'target_role':dict(TEXT,enum=sorted({r['target_role'] for r in work_items})),
  'source_output_id':dict(TEXT,enum=sorted({r['source_output_id'] for r in work_items})),
  'instruction':TEXT,'acceptance':TEXT,'needs_research':{'type':'boolean'},
  'historical_sources':{'type':'array','maxItems':3,'items':{'type':'object','additionalProperties':False,'properties':{
   'completed_id':dict(TEXT,maxLength=80),'fact_ids':{'type':'array','minItems':1,'maxItems':10,'items':dict(TEXT,maxLength=120)}},'required':['completed_id','fact_ids']}}},
  'required':['id','target_role','source_output_id','instruction','acceptance','needs_research','historical_sources']}
 return {'$id':'urn:mara:recovery-review:1.0','type':'object','additionalProperties':False,'properties':{
  'decision':{'type':'string','enum':['revise','blocked']},'reason':TEXT,
  'requests':{'type':'array','maxItems':4,'items':request}},'required':['decision','reason','requests']}

class Coordinator:
 def __init__(self,session,model,as_of,run_id,guide):
  self.s,self.model,self.as_of,self.run_id,self.guide=session,model,as_of,run_id,guide
  self.rounds={};self.signatures={};self.reviews=0;self.latest={};self.last_leader_id=None
 def event(self,state,**data):
  return self.s.append('submission_recovery',dict(version=VERSION,state=state,**copy.deepcopy(data)),self.as_of,self.run_id)
 def accepted(self,role,stage,output_id):
  key=(role,stage);prior=self.latest.get(key)
  self.latest[key]=output_id
  self.event('accepted',target_role=role,stage=stage,output_id=output_id,supersedes=prior)
 def sources(self,roles):
  result={}
  for (role,stage),oid in self.latest.items():
   if role in roles and (role not in result or self.s.get(oid)['seq']>self.s.get(result[role]['output_id'])['seq']):
    result[role]={'output_id':oid,'stage':stage,'output':copy.deepcopy(self.s.get(oid)['body']['output']),'reference_scope':reference_scope(self.s,oid)}
  return result
 def restore_review(self,packet,output_id):
  """Restore a verified already-dispatched review without resetting its budget."""
  if self.reviews or self.rounds:raise ValueError('Recovery state already initialized')
  if packet['budget']['reviews_used']!=1 or packet['budget']['case_round']!=1:raise ValueError('Only the first dispatched review is supported')
  self.reviews=1;self.last_leader_id=output_id
  for item in packet['work_items']:
   key,signature=case_progress(packet['case_id'],item,packet['sources'],packet.get('diagnostic'))
   self.rounds[key]=self.rounds.get(key,0)+1;self.signatures[key]=signature
 def review(self,case_id,work_items,sources,diagnostic=None,historical_catalog=None):
  if not work_items or len(work_items)>4:raise RecoveryIncomplete('invalid_work_item_count')
  case_keys=[];repeated=False;over_limit=False
  for item in work_items:
   key,signature=case_progress(case_id,item,sources,diagnostic)
   case_keys.append(key);self.rounds[key]=self.rounds.get(key,0)+1
   repeated=repeated or self.signatures.get(key)==signature
   self.signatures[key]=signature;over_limit=over_limit or self.rounds[key]>MAX_CASE_ROUNDS
  if self.reviews>=MAX_REVIEWS or over_limit or repeated:
   reason='no_diagnostic_progress' if repeated else 'leader_recovery_budget'
   self.event('blocked',case_id=case_id,reason=reason,work_items=work_items)
   raise RecoveryIncomplete(reason)
  self.reviews+=1
  packet={'analysis_stage':'submission_review','version':VERSION,'case_id':case_id,'work_items':work_items,
   'sources':sources,'diagnostic':diagnostic,'historical_catalog':historical_catalog or [],
   'budget':{'reviews_used':self.reviews,'reviews_max':MAX_REVIEWS,'case_round':max(self.rounds[k] for k in case_keys),'case_max':MAX_CASE_ROUNDS,'model_call_max':MAX_MODEL_CALLS},
   'boundary':'Process coordination, not portfolio synthesis. Sources may be rejected and must not become approved analyses. Send only author-specific defect and acceptance instructions; no peer allocation preferences. Missing evidence can be researched; future scenarios and economic disagreement are not errors. Do not guess IDs or relax checks.'}
  spec=contract(work_items);guide=self.guide+'\n이 호출은 제출/최종검증 복구 조정이에요. 투자 종합 대신 주어진 작은 계약만 반환하세요. 각 work item을 원 작성자에게 구체적으로 재요청하고 수용 조건을 정하세요. 잘못된 ID는 정확한 전달 목록을 복사하거나 근거 없는 주장을 미확인으로 고쳐야 해요. 다른 관점의 의견·비중을 지시에 섞지 마세요. 자료가 필요하면 needs_research로 담당 자료 조사를 요청하세요.'
  if len(dumps(packet))>180000:raise RecoveryIncomplete('leader_review_input_budget')
  self.event('requested',case_id=case_id,work_items=work_items)
  for attempt in (1,2):
   guard(self.s,self.run_id,self.as_of)
   iid=self.s.append('recovery_leader_input',{'role':'leader','payload':packet,'contract':spec,'guide':guide,'provider':self.model.identity},self.as_of,self.run_id)
   out=self.model.complete('leader',guide,packet,spec)
   oid=self.s.append('recovery_leader_output',{'input_id':iid,'output':out},self.as_of,self.run_id)
   try:
    validate(out,spec)
    if out['decision']=='revise':
     if len(out['requests'])!=len(work_items) or {r['id'] for r in out['requests']}!={r['id'] for r in work_items}:raise ContractError('Route each work item exactly once')
     for r in out['requests']:
      original=next(x for x in work_items if x['id']==r['id'])
      if any(r[k]!=original[k] for k in ('target_role','source_output_id')):raise ContractError('Cannot change source author or output')
      if any(h['completed_id'] not in {x['completed_id'] for x in packet['historical_catalog']} for h in r['historical_sources']):raise ContractError('Historical source was not supplied')
   except (ValueError,KeyError,TypeError) as exc:
    self.s.append('recovery_leader_validation',{'input_id':iid,'output_id':oid,'status':'rejected','reason':str(exc)[:2000]},self.as_of,self.run_id)
    if attempt==2:raise RecoveryIncomplete('leader_routing_contract') from None
    packet=dict(packet,repair={'reason':str(exc)[:2000],'previous_output':out});continue
   self.s.append('recovery_leader_validation',{'input_id':iid,'output_id':oid,'status':'accepted'},self.as_of,self.run_id)
   if out['decision']=='blocked':
    self.event('blocked',case_id=case_id,reason=out['reason'],leader_output_id=oid)
    raise RecoveryIncomplete('leader_cannot_resolve: '+out['reason'])
   self.event('dispatched',case_id=case_id,leader_output_id=oid,requests=out['requests'])
   self.last_leader_id=oid
   return out['requests']

def historical_facts(session,completed_id,fact_ids,as_of,boundary,mode,before_seq):
 """Explicit verified re-delivery, never a cross-owner lookup or judgment promotion."""
 from . import history
 from .fact_catalog import authoritative_facts
 source=session.get(completed_id)
 if source['owner']!=session.owner or source['kind']!='completed' or source['seq']>=before_seq or not history.belongs(session,source,boundary) or source['body']['mode']!=mode:raise RecoveryIncomplete('historical_source_scope')
 catalog={f['id']:f for f in authoritative_facts(session,source)}
 if len(set(fact_ids))!=len(fact_ids) or not set(fact_ids)<=catalog.keys():raise RecoveryIncomplete('historical_fact_not_in_source')
 result=[]
 for fid in fact_ids:
  f=catalog[fid]
  if not f['published_at']<=f['known_at']<=as_of<=f['valid_until']:raise RecoveryIncomplete('historical_fact_expired_or_future')
  if f.get('research_tool') in ('company_valuation','company_normalize_earnings'):raise RecoveryIncomplete('historical_assumptions_require_new_analysis')
  result.append(copy.deepcopy(f))
 return result
