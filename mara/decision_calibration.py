"""A conditional decision contract; facts and numerical constraints never relax."""
import copy
from .contracts import ContractError
from .registry import agent

VERSION='mara.decision-calibration/1.0'
ANALYSTS={'buffett','marks','bogle','wood','leader','validation'}
POLICY={
 'schema_version':VERSION,
 'rule':'확인 가능한 사실(주식수·기간·단위·분할 기준·출처)과 계산 무결성, 개인 조건·손실 기준은 유지해요. 미래 성장·정상화·확신은 사실로 바꾸지 않고 시나리오·비중·반증·재검토 조건으로 다뤄요. 미래 불확실성의 완전 소멸을 편입의 필수 조건으로 요구하지 않으며 매수도 강제하지 않아요.',
 'gaps':'decision_gaps에 결정에 중요한 공백을 사실 확인/계산 연결/미래 판단으로 구별하고 구체적 해제 조건을 적어요. 접근 실패·미추출·배정 한도는 투자 부적합의 증거가 아니에요. unresolved 사실·계산을 managed_by_scenario로 숨기지 않아요. affects_selected는 최종 선택의 근거 자체에 영향을 주는지예요. 미래 가정을 resolved 사실처럼 표시하지 않아요.',
 'choice':'decision_resolution의 choices는 investment_case.alternatives의 실제 comparison_path와 연결해 현금 대기·소규모 참여·더 높은 비중을 같은 자금·시점·비용·위험 기준으로 비교해요. 각 대안에 adverse/base/favorable 가정, 기회비용, 그 비중의 이유, 반증·재검토 조건과 시점을 적어요. 현금도 무근거 기본값이 아니며 기회비용과 유한한 대기 조건을 설명해요. 가정은 검증된 관측과 분리하세요.',
 'knowledge':'knowledge_feedback는 전달된 지식의 실제 적용/검토/미적용/재검증과 영향을 기록해요. 이전 의견·반복 횟수는 독립 시장 근거가 아니에요. needs_revalidation=true를 현재 유효 사실로 적용하지 마세요.',
}

class CalibrationError(ContractError):
 def __init__(self,code,detail):
  self.diagnostic={'code':code,'detail':detail,'instruction':'원래 사실·계산·위험 조건을 유지하고 해당 필드와 판단 범위를 교정하세요. 무관한 인용이나 매수/보류 강제로 통과시키지 마세요.'}
  super().__init__('Decision policy '+code+': '+detail)

def enabled(model):return getattr(model,'decision_policy_version',None)==VERSION

def failure_subtype(output,error):
 from .evidence_feedback import FeedbackContractError
 if isinstance(error,FeedbackContractError):return 'evidence_assessment_coverage'
 if isinstance(error,CalibrationError):return error.diagnostic['code']
 if isinstance(output,dict) and isinstance(output.get('decision_gaps'),list):
  for gap in output['decision_gaps']:
   paths=gap.get('calculation_paths') if isinstance(gap,dict) else None
   if isinstance(paths,list) and any(isinstance(p,str) and not p.startswith('/analysis/') for p in paths):return 'gap_calculation_root'
 return None

def followups(payload):
 return payload.get('evidence_feedback',[])+(payload.get('research_feedback_history') or {}).get('requests',[])

def attach(payload,role):
 payload['decision_policy']=copy.deepcopy(POLICY)
 payload['decision_policy']['knowledge_event_ids']=[x['event_id'] for x in payload.get('knowledge',{}).get('items',[])]
 return payload

def contract_for(contract,role,payload):
 if not payload.get('decision_policy'):return contract
 result=copy.deepcopy(contract);required=result['required']
 if role in ANALYSTS:required.append('decision_gaps')
 if role=='leader':required.append('decision_resolution')
 if role in ANALYSTS|{'evidence'}:required.append('knowledge_feedback')
 hist=payload.get('research_feedback_history',{})
 if role=='reflection' and (hist.get('requests') or hist.get('process_failures',{}).get('items')):required.append('research_learning')
 if role=='memory' and payload.get('learning_proposals'):required.append('learning_applications')
 if role in ('leader','validation') and payload.get('memory_feedback',{}).get('conflicts'):
  required.append('memory_reviews')
  result['properties']['memory_reviews'].update(minItems=len(payload['memory_feedback']['conflicts']),maxItems=len(payload['memory_feedback']['conflicts']))
  result['properties']['memory_reviews']['items']['properties']['conflict_id']['enum']=[r['id'] for r in payload['memory_feedback']['conflicts']]
 if role=='reflection' and payload.get('research_feedback_history',{}).get('requests'):
  result['properties']['research_learning']['items']['properties']['request_ids']['items']['enum']=sorted({r['request_id'] for r in payload['research_feedback_history']['requests']})
 if role=='reflection':
  props=result['properties']['research_learning']['items']['properties']
  if not hist.get('requests'):props['request_ids']['maxItems']=0
  failures=sorted({r['failure_id'] for r in hist.get('process_failures',{}).get('items',[])})
  if failures:props['failure_ids']['items']['enum']=failures
  else:props.pop('failure_ids',None)
 # New suppliers must distinguish unresolved operational/analytical causes.
 if role=='evidence' and 'evidence_responses' in result['properties']:
  result['properties']['evidence_responses']['items']['required'].append('unresolved_cause')
 if 'evidence_requests' in result['properties']:
  request=result['properties']['evidence_requests']['items']
  request['required']+=['gap_class','decision_priority','research_target','resolution_condition','stop_condition','related_fact_ids']
  known=sorted({r['request_id'] for r in followups(payload)})
  if known:request['properties']['followup_of']['enum']=known
  else:request['properties'].pop('followup_of',None)
 result['required']=list(dict.fromkeys(required))
 return result

def _fail(code,detail):raise CalibrationError(code,detail)

def validate_output(role,out,payload):
 if not payload.get('decision_policy'):return
 from .contracts import validate,output_schema
 validate(out,contract_for(output_schema(role),role,payload))
 facts={f['id'] for f in payload.get('market',{}).get('facts',[])}
 questions={q['id'] for q in payload.get('decision_scope',{}).get('questions',[])}
 for row in out.get('decision_gaps',[]):
  if row['question_id'] not in questions:_fail('gap_question','Unknown fixed question '+row['question_id'])
  kind=row['kind'];cause=row['cause'];status=row['status']
  allowed={'fact_verification':{'access_failure','not_extracted','allocation_limit','source_unverified'},'calculation_link':{'calculation_missing','not_extracted','allocation_limit'},'future_judgment':{'future_assumption'}}
  if cause not in allowed[kind]:_fail('gap_cause','Cause does not match '+kind)
  if kind!='future_judgment' and status=='managed_by_scenario':_fail('hard_gap','Facts/calculations cannot be replaced by scenarios')
  if kind=='future_judgment' and status=='resolved':_fail('future_fact','Future assumptions are not resolved observations')
  if not set(row['fact_ids'])<=facts:_fail('gap_sources','Gap cites undelivered fact IDs')
  if status=='resolved' and not (row['fact_ids'] or row['calculation_paths']):_fail('resolution_sources','Resolved gap needs source or calculation evidence')
  for path in row['calculation_paths']:
   from .evaluation import pointer
   try:
    if not path.startswith('/analysis/'):raise ContractError('analysis path required')
    value=pointer({'report':payload},'/report'+path)
    if value is None or value=={} or value==[]:raise ContractError('empty calculation')
   except ContractError:_fail('gap_calculation','Unknown/empty calculation '+path)
 for request in out.get('evidence_requests',[]):
  if not set(request['related_fact_ids'])<=facts:_fail('request_sources','Request cites undelivered facts')
  if request['gap_class']=='future_judgment' and request['gap_type']!='analysis':_fail('future_request','Future assumptions are analysis, not missing public facts')
  if request.get('followup_of'):
   prior=[r for r in followups(payload) if r['request_id']==request['followup_of']]
   if not prior or not request.get('retry_reason','').strip():_fail('retry_basis','A followup needs a known current or historical request and a specific new research/calculation route; unanswered history remains unanswered')
 if role in ('leader','validation') and payload.get('memory_feedback'):
  expected={r['id'] for r in payload['memory_feedback']['conflicts']};rows=out.get('memory_reviews',[]);ids=[r['conflict_id'] for r in rows]
  if len(ids)!=len(set(ids)) or set(ids)!=expected:_fail('memory_feedback','Assess each supplied memory conflict exactly once; incorporation is not factual resolution')
  if any(not set(r['fact_ids'])<=facts for r in rows):_fail('memory_review_sources','Memory review cites undelivered facts')
 if role in ANALYSTS|{'evidence'}:validate_knowledge(out['knowledge_feedback'],payload)
 if role=='validation' and payload.get('final_proposal'):
  hard=[g for g in out.get('decision_gaps',[]) if g['affects_selected'] and g['kind']!='future_judgment' and g['status']=='unresolved']
  if hard and out.get('qualitative_pass'):_fail('final_integrity','Final validation cannot pass with an unresolved selected factual/calculation basis')
 if role!='leader':return
 resolution=out['decision_resolution'];choices=resolution['choices']
 alternatives={a['comparison_path']:a for a in out.get('investment_case',{}).get('alternatives',[])}
 if len({c['comparison_path'] for c in choices})!=len(choices):_fail('choice_paths','Use distinct compared alternatives')
 participation={};assets=payload['market']['assets']
 from .domain import weights
 for choice in choices:
  path=choice['comparison_path']
  if path not in alternatives:_fail('choice_reference','Choice must link a declared investment_case alternative: '+path)
  w=alternatives[path]['weights'];weights(w)
  if not set(w)<=(set(assets)|{'CASH'}):_fail('choice_asset','Alternative contains an unregistered asset')
  exposure=sum(v for s,v in w.items() if s!='CASH' and assets.get(s,{}).get('asset_class')!='cash')
  label=choice['participation'];participation.setdefault(label,[]).append(exposure)
  if label=='cash_wait' and exposure>1e-9:_fail('cash_label','Cash alternative contains risk assets')
  if label in ('small_participation','higher_participation') and exposure<=0:_fail('participation_label','Participation alternative has no risk exposure')
  if {s['name'] for s in choice['scenarios']}!={'adverse','base','favorable'}:_fail('scenarios','Use distinct adverse, base and favorable assumptions')
 if not {'cash_wait','small_participation','higher_participation'}<=participation.keys():_fail('symmetric_choices','Compare cash waiting, small participation and a higher allocation')
 if max(participation['small_participation'])>=min(participation['higher_participation']):_fail('size_order','Higher participation must have higher risky-asset exposure')
 hard=[g for g in out['decision_gaps'] if g['affects_selected'] and g['kind']!='future_judgment' and g['status']=='unresolved']
 if hard and out['action']!='defer':_fail('selected_integrity','Unresolved factual/calculation basis of the selected allocation remains a hard condition')
 if resolution['basis']=='conditional_participation' and out['action']=='defer':_fail('basis_action','Conditional participation cannot describe a deferred proposal')

def validate_knowledge(rows,payload):
 items={x['event_id']:x for x in payload.get('knowledge',{}).get('items',[])}
 facts={f['id'] for f in payload.get('market',{}).get('facts',[])}
 ids=[r['knowledge_event_id'] for r in rows]
 if len(ids)!=len(set(ids)) or set(ids)!=set(items):_fail('knowledge_ids','Assess each delivered knowledge_event_id exactly once: '+str(sorted(items)))
 for row in rows:
  if not set(row['fact_ids'])<=facts:_fail('knowledge_sources','Knowledge feedback cites undelivered facts')
  if items[row['knowledge_event_id']].get('needs_revalidation') and row['status']=='applied':_fail('stale_knowledge','Revalidate expired knowledge before treating it as applicable')
