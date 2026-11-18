import copy,tempfile,unittest
from pathlib import Path
from mara import decision_calibration as policy,research_learning as learning
from mara.evidence_feedback import collect,schedule
from mara.agents import DemoModel
from mara.contracts import ContractError
from mara.knowledge import Knowledge
from mara.engine import Engine
from mara.store import Store
from test_evidence_feedback import FeedbackModel,request
from test_decision import profile,market


def calibrated_request(need='Read cash source',**changes):
 r=request(need);r.update(gap_class='fact_verification',decision_priority='changes_choice',research_target={'subject':'FUND','topic':'cash_generation','measure':'operating_cashflow','period':'FY2025','unit':'USD','basis':'consolidated'},resolution_condition='Dated original fact and matched computation',stop_condition='Two bounded rounds; keep unresolved if absent',related_fact_ids=[]);r.update(changes);return r


def gap(**changes):
 x=dict(question_id='candidate-FUND',kind='fact_verification',cause='not_extracted',status='unresolved',subject='FUND',affects_selected=True,reason='Missing source',resolution_condition='Read source',next_action='Request source',fact_ids=[],calculation_paths=[]);x.update(changes);return x


class CalibrationTests(unittest.TestCase):
 def test_priority_is_permutation_invariant_sharing_respects_units_and_period(self):
  rows=collect([(r,'perspective',r,{'evidence_requests':[calibrated_request(r,decision_priority=p)]}) for r,p in [('bogle','explanation_only'),('wood','changes_size'),('buffett','changes_choice')]],set(),1)
  a=schedule(copy.deepcopy(rows),[]);b=schedule(list(reversed(copy.deepcopy(rows))),[])
  self.assertEqual([r['request_id'] for r in a],[r['request_id'] for r in b]);self.assertEqual(a[0]['requester'],'buffett');self.assertEqual(len({r['research_group'] for r in a}),1)
  rows[1]['research_target']['unit']='shares';rows[2]['research_target']['period']='FY2024'
  self.assertEqual(len({r['research_group'] for r in schedule(rows,[])}),3)
 def test_budget_and_repeat_stop_are_not_resolution_and_partial_response_can_retry(self):
  rows=collect([('buffett','perspective','out',{'evidence_requests':[calibrated_request(str(i),research_target={'subject':str(i),'topic':'cash_generation','measure':'operating_cashflow','period':'FY2025','unit':'USD','basis':'consolidated'}) for i in range(9)]})],set(),1)
  self.assertEqual(len(schedule(rows,[])),6);self.assertEqual(sum(r['status']=='deferred_capacity' for r in rows),3)
  prior=copy.deepcopy(rows[0]);prior.update(response={'status':'evidence_supplied','fact_ids':['f1']},assessment={'status':'still_missing'})
  retry=copy.deepcopy(rows[0]);self.assertFalse(schedule([retry],[prior]));self.assertEqual(retry['status'],'repeat_target_stopped')
  retry.update(status='pending',followup_of=prior['request_id'],retry_reason='Read the previously unread diluted-share table and compute period-matched ratio')
  self.assertEqual(len(schedule([retry],[prior])),1)
  prior['assessment']['status']='incorporated';prior['response']['remaining_gap']='The diluted denominator table remains unread'
  self.assertEqual(len(schedule([retry],[prior])),1)
  separate=copy.deepcopy(rows[0]);separate['research_target']['measure']='capital_expenditure'
  self.assertEqual(len(schedule([separate],[prior])),1)
 def test_final_validator_cannot_approve_selected_integrity_gap(self):
  p={'decision_policy':policy.POLICY,'decision_scope':{'questions':[{'id':'candidate-FUND'}]},'market':market(),'knowledge':{'items':[]},'final_proposal':{'action':'rebalance'}}
  out=DemoModel().complete('validation','',p,{});out.update(decision_gaps=[gap()],knowledge_feedback=[],qualitative_pass=True)
  with self.assertRaisesRegex(ContractError,'final_integrity'):policy.validate_output('validation',out,p)
  out['decision_gaps']=[gap(kind='future_judgment',cause='future_assumption',status='managed_by_scenario')]
  policy.validate_output('validation',out,p)
  out['decision_gaps']=[gap(status='managed_by_scenario')]
  with self.assertRaisesRegex(ContractError,'hard_gap'):policy.validate_output('validation',out,p)
 def test_learning_cannot_launder_process_into_market_or_use_unseen_source(self):
  item=dict(key='k',event_id='knowledge',refs=['source'],category='lesson',valid_until=None)
  p={'decision_policy':policy.POLICY,'allowed_refs':['reflection'],'reflection_id':'reflection','review_items':[item],'learning_proposals':[{'id':'l1','status':'propose'}]}
  op=dict(action='revise',key='k',reason='Process change',text='Check source',refs=['reflection'],category='market')
  out={'operations':[op],'learning_applications':[dict(review_id='l1',disposition='apply',operation_indices=[0],reason='Apply',validation='Check next input')]}
  with self.assertRaisesRegex(ContractError,'learning_category'):learning.validate_memory(out,p)
  op['category']='lesson';learning.validate_memory(out,p)
  op['refs']=['invented']
  with self.assertRaisesRegex(ContractError,'allowed_refs'):learning.validate_memory(out,p)
 def test_multiple_memory_batches_have_a_satisfiable_exact_review_contract(self):
  p={'decision_policy':policy.POLICY,'decision_scope':{'questions':[]},'market':market(),'knowledge':{'items':[]},'memory_feedback':{'conflicts':[{'id':'conflict-'+str(i)} for i in range(121)]}}
  out=DemoModel().complete('validation','',p,{});out.update(decision_gaps=[],knowledge_feedback=[],memory_reviews=[dict(conflict_id=r['id'],status='still_open',reason='Keep condition',decision_impact='Reassess before commitment',next_action='Review source',fact_ids=[]) for r in p['memory_feedback']['conflicts']])
  policy.validate_output('validation',out,p)
  out['memory_reviews'].pop()
  with self.assertRaises(ContractError):policy.validate_output('validation',out,p)
 def test_historical_answered_and_unanswered_followups_keep_original_request_links(self):
  p={'decision_policy':policy.POLICY,'decision_scope':{'questions':[{'id':'candidate-FUND'}]},'market':market(),'knowledge':{'items':[]},'research_feedback_history':{'requests':[{'request_id':'old-pending','status':'round_budget'},{'request_id':'old-returned','response':{'status':'evidence_supplied'}}]}}
  out=DemoModel().complete('validation','',p,{});out.update(decision_gaps=[],knowledge_feedback=[])
  for source in ('old-pending','old-returned'):
   out['evidence_requests']=[calibrated_request(followup_of=source,retry_reason='Read the previously unavailable dated source')];policy.validate_output('validation',out,p)
  out['evidence_requests'][0]['followup_of']='invented'
  with self.assertRaises(ContractError):policy.validate_output('validation',out,p)
 def test_pruning_never_erases_different_delivery_scope_or_validity(self):
  for field,value in [('roles',['wood']),('category','hypothesis'),('priority',9),('valid_until','2026-12-01')]:
   with self.subTest(field=field),tempfile.TemporaryDirectory() as t:
    db=Store(Path(t)/'db');s=db.session(db.create_user('test'));k=Knowledge(s);ref=s.append('fixture',{},'2026-11-15')
    op=dict(action='add',reason='Fixture',text='Same lesson',topic='process',condition='same',perspective='process',category='lesson',roles=['buffett'],refs=[ref],valid_until=None,priority=1)
    k.apply(op,'2026-11-15');k.apply(dict(op,**{field:value}),'2026-11-15');k.prune('2026-11-15')
    self.assertEqual(len(k.active('2026-11-15')),2)
    if field=='roles':self.assertEqual(len(k.retrieve('2026-11-15','wood')['items']),1)
    db.close()
 def test_knowledge_revision_applies_scope_metadata_and_preserves_versions(self):
  with tempfile.TemporaryDirectory() as t:
   db=Store(Path(t)/'db');s=db.session(db.create_user('test'));k=Knowledge(s);ref=s.append('test',{},'2026-11-15')
   first=k.apply(dict(action='add',reason='fixture',text='Old rule',topic='process',condition='old',perspective='process',category='lesson',roles=['bogle'],refs=[ref],valid_until=None,priority=1),'2026-11-15')
   key=s.get(first)['body']['key'];second=k.apply(dict(action='revise',reason='New source condition',key=key,text='New rule',condition='new',roles=['evidence'],priority=9,refs=[ref]),'2026-11-16')
   self.assertEqual(k.retrieve('2026-11-16','bogle')['items'],[]);self.assertEqual(k.retrieve('2026-11-16','evidence')['items'][0]['condition'],'new');self.assertEqual(s.get(first)['body']['condition'],'old');self.assertEqual(s.get(second)['body']['previous_event'],first);db.close()

class PlannerLearningTests(unittest.TestCase):
 def test_planner_reads_scoped_lesson_and_records_actual_tool_choice(self):
  from mara.company_research import CompanyLibrary,research_loop
  m=market();lesson={'event_id':'k1','text':'Read original before interpreting','needs_revalidation':False}
  payload={'as_of':m['as_of'],'market':m,'profile':{'goal':'Synthetic'},'knowledge':{'items':[lesson]},'research_feedback_history':{'requests':[],'status_counts':{'round_budget':2}},'decision_scope':{'questions':[{'id':'candidate-FUND','target':'FUND','owner':'buffett'}]}}
  class Model:
   mode='live';identity={'provider':'synthetic'};decision_policy_version=policy.VERSION;count=0
   def complete(self,role,guide,p,contract):
    assert p['knowledge']['items'][0]['event_id']=='k1'
    assert p['research_feedback_history']['status_counts']['round_budget']==2
    self.count+=1
    return {'reason':'Read exact source because lesson requires it' if self.count==1 else 'No useful additional source','calls':[{'tool':'evidence_read','arguments':{'fact_id':m['facts'][0]['id'],'offset':0,'limit':1000},'question_ids':['candidate-FUND']}] if self.count==1 else [],'stop_reason':'low_information_value','knowledge_feedback':[{'knowledge_event_id':'k1','status':'applied','effect':'Choose evidence_read before interpretation','fact_ids':[]}]}
  with tempfile.TemporaryDirectory() as t:
   db=Store(Path(t)/'db');s=db.session(db.create_user('test'));research_loop(s,Model(),'buffett','Synthetic',payload,'run',m['as_of'],CompanyLibrary(Path(t)/'library',today=m['as_of']))
   self.assertTrue(s.events('research_plan_accepted'));self.assertTrue(any(e['body']['call']['tool']=='evidence_read' for e in s.events('research_tool_result')))
   self.assertTrue(any(r.get('stage')=='research_plan' and r['status']=='applied' for r in learning.usage_receipts(s,'run')));db.close()

class LearningFlowTests(unittest.TestCase):
 def test_real_engine_history_review_application_and_later_delivery(self):
  class Model(FeedbackModel):
   decision_policy_version=policy.VERSION
   def complete(self,role,guide,p,contract):
    out=super().complete(role,guide,p,contract)
    if role in policy.ANALYSTS:out['decision_gaps']=[]
    if role in policy.ANALYSTS|{'evidence'}:out['knowledge_feedback']=[dict(knowledge_event_id=i['event_id'],status='considered',effect='Evaluate process condition',fact_ids=[]) for i in p.get('knowledge',{}).get('items',[])]
    if out.get('evidence_requests'):out['evidence_requests']=[calibrated_request(r['need']) for r in out['evidence_requests']]
    for r in out.get('evidence_responses',[]):r['unresolved_cause']='calculation_missing'
    if role=='leader':
     out['investment_case']={'key_points':['synthetic']*3,'claims':[dict(id='c'+str(i),requirement_id=contract['properties']['investment_case']['properties']['claims']['items']['properties']['requirement_id']['enum'][i],importance='Synthetic condition',statement='Synthetic unresolved premise',status='unresolved',assumptions=['Synthetic only'],counterevidence='Unresolved evidence',decision_impact='No superiority claim',fact_ids=[],calculation_paths=[]) for i in range(12)],
      'alternatives':[dict(name='Alternative '+str(i),weights=w,decision='diagnostic_only',reason='Synthetic comparison',change_condition='New source',comparison_path='/analysis/alternative_comparisons/'+str(i)) for i,w in enumerate([{'CASH':1},{'FUND':.1,'CASH':.9},{'FUND':.3,'CASH':.7}])],
      'monitoring':[dict(variable='Premise',condition='Changed fact',check_at='Next review',owner='leader',action='Reconsider',counterexample_test='Adverse evidence')]*3,'scope_limits':['Synthetic'],'implementation':['No orders']*3}
     out['decision_resolution']={'basis':'temporary_wait','choices':[dict(comparison_path='/analysis/alternative_comparisons/'+str(i),participation=kind,scenarios=[dict(name=n,assumptions=['Synthetic assumption'],implication='Review source') for n in ['adverse','base','favorable']],opportunity_cost='Foregone participation or liquidity',why_this_size='Same risk constraint',falsifier='Changed cash conversion',review_condition='Original source arrives',review_by='2026-11-23') for i,kind in enumerate(['cash_wait','small_participation','higher_participation'])],'decisive_tradeoff':'Synthetic comparison','remaining_uncertainty_treatment':'Source check and explicit scenarios'}
    if role=='reflection':
     rows=p['research_feedback_history']['requests'];assert rows and rows[0]['assessment_history']
     out['research_learning']=[dict(id='lesson-1',category='acceptance_condition',request_ids=[rows[0]['request_id']],observation='Supplier receipt was not analytical resolution',proposed_change='Keep acceptance condition until requester assesses source',target='research_plan',condition='Returned source',validation='Next role reads exact receipt and reports use',status='propose')]
    if role=='memory':
     out['conflicts']=['Keep unresolved evidence separate from adverse investment evidence']
     out['operations']=[dict(action='add',reason='Traceable process lesson',text='Assess the original source against the acceptance condition',topic='request-process',condition='Returned evidence',perspective='process',category='lesson',roles=['buffett'],refs=[p['reflection_id']],valid_until=None,priority=9)]
     out['learning_applications']=[dict(review_id='lesson-1',disposition='apply',operation_indices=[0],reason='Bounded process instruction',validation='Read next delivered input')]
    if role in ('leader','validation') and p.get('memory_feedback'):
     out['memory_reviews']=[dict(conflict_id=c['id'],status='still_open',reason='Preserve the unresolved condition',decision_impact='Do not treat an uncompleted investigation as negative evidence',next_action='Review the original source',fact_ids=[]) for c in p['memory_feedback']['conflicts']]
    if role in ('buffett','marks','bogle','wood'):assert 'memory_feedback' not in p
    if role=='buffett' and p.get('knowledge',{}).get('items'):
     out['knowledge_feedback']=[dict(knowledge_event_id=i['event_id'],status='applied',effect='Keep unresolved acceptance condition',fact_ids=[]) for i in p['knowledge']['items']]
     if p.get('current_reflection'):assert set(p['current_reflection']['perspective_review'])=={'buffett'}
     assert all(r['requester']=='buffett' for r in p['research_feedback_history']['requests'])
    return out
  with tempfile.TemporaryDirectory() as t:
   from mara.company_research import CompanyLibrary
   db=Store(Path(t)/'db');s=db.session(db.create_user('fixture'));m=market();model=Model();e=Engine(s,model,CompanyLibrary(Path(t)/'library',today=m['as_of']))
   e.set_profile(profile(),m['as_of']);e.set_holdings(dict(as_of=m['as_of'],base_currency='USD',cash=100,positions={},rationale='Synthetic',last_rebalanced=m['as_of']))
   first=e.run(m['as_of'],db.publish_market(m),evaluate_after=False)
   m['as_of']='2026-11-16';e.research_library._today=m['as_of'];second=e.run(m['as_of'],db.publish_market(m),force=True,evaluate_after=False)
   trace=second['research_learning'];self.assertEqual(trace['status'],'reviewed');self.assertEqual(trace['source_completed_id'],first['event_id']);self.assertTrue(trace['applications']);self.assertTrue(trace['knowledge_usage']);self.assertEqual(len(trace['memory_feedback']['conflicts']),1);self.assertEqual(len(trace['memory_reviews']['final_validation']),1)
   applied=trace['applications'][0]['knowledge_event_id'];self.assertTrue(any(r['knowledge_event_id']==applied and r['status']=='applied' for r in trace['knowledge_usage']));self.assertTrue(second['evidence_feedback']['exchanges'][0]['final_decision'])
   third=e.run(m['as_of'],force=True,revision_reason='Frozen feedback test',improvement={'parent_completed_id':second['event_id']},evaluate_after=False)
   self.assertEqual(third['research_learning']['status'],'skipped_frozen_revision');self.assertEqual(third['research_learning']['memory_feedback']['conflicts'],trace['memory_feedback']['conflicts']);self.assertEqual(len(third['research_learning']['memory_reviews']['final_validation']),1);db.close()
