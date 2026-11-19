"""Same-run submission CI -> leader routing -> author -> final validation."""
import copy,unittest
from types import SimpleNamespace
from unittest.mock import patch
from mara.agents import DemoModel
from mara.submission import bind,validate_revisions
from mara.submission_recovery import RecoveryIncomplete,historical_facts
from mara.contracts import output_schema,validate,ContractError
from mara import research_learning as learning
from mara.workbench import project
import test_system as fixtures

class SubmissionRecoveryTests(unittest.TestCase):
 setUp=fixtures.Harness.setUp
 tearDown=fixtures.Harness.tearDown
 initial=fixtures.Harness.initial

 def test_actual_failure_shape_repairs_new_bad_id_through_leader_in_same_run(self):
  seen=[]
  class Model(DemoModel):
   attempts=0
   def complete(inner,role,guide,p,contract):
    seen.append((role,copy.deepcopy(p)))
    out=super().complete(role,guide,p,contract)
    if role=='buffett':
     inner.attempts+=1
     if inner.attempts==1:
      out['evidence_ids']=['truncated-company-id']
      out['evidence_assessments']=[{'request_id':'old-response','status':'incorporated','reason':'Past response incorrectly treated as current','fact_ids':[]}]
     elif inner.attempts==2:out['evidence_ids']=['different-hybrid-company-id']
     else:
      assert p['submission_repair']['diagnostic']['issues'][0]['value']=='different-hybrid-company-id'
      assert p['revision_instructions'][0]['source_output_id']==p['submission_repair']['rejected_output_id']
      assert not p.get('perspectives') and not p.get('submission_sources')
    return out
  self.e.model=Model();report=self.initial()
  self.assertEqual(report['perspectives']['buffett']['evidence_ids'],['demo-1'])
  rows=[e for e in self.s.events('agent_validation') if e['body']['role']=='buffett']
  self.assertEqual([e['body']['status'] for e in rows],['rejected','rejected','accepted'])
  self.assertEqual(len(self.s.events('recovery_leader_output')),1)
  self.assertFalse(self.s.events('failed'))
  self.assertEqual(self.s.get(rows[1]['body']['output_id'])['body']['output']['evidence_ids'],['different-hybrid-company-id'])
  self.assertEqual(next(c for c in project(self.s,report['run_id'])['components'] if c['id']=='buffett')['output']['evidence_ids'],['demo-1'])
  h=learning.history(self.s,self.s.get(report['event_id']))
  self.assertTrue(any(e['state']=='author_requested' for e in h['submission_recovery']['events']))
  self.assertFalse(any(e.get('target_role')=='buffett' for e in learning.for_role(h,'wood')['submission_recovery']['events']))

 def revision_model(self,needs_research=False):
  class Model(DemoModel):
   def complete(inner,role,guide,p,contract):
    out=super().complete(role,guide,p,contract)
    if contract.get('$id')=='urn:mara:recovery-review:1.0':return out
    if role=='buffett':
     changed=bool(p.get('revision_instructions')) or any(f['id']=='new-observation' for f in p['market']['facts'])
     out['thesis']='Corrected 2+2=4' if changed else 'Incorrect 2+2=5'
     if p.get('revision_instructions'):assert not p.get('perspectives') and not p.get('submission_sources')
    if role=='validation' and p.get('final_proposal') and p['perspectives']['buffett']['thesis'].startswith('Incorrect'):
     source=p['submission_sources']['buffett']
     out['revision_requests']=[dict(id='arithmetic',target_role='buffett',source_output_id=source['output_id'],issue_path='/thesis',
      kind='missing_evidence' if needs_research else 'calculation_error',reason='Author statement is inconsistent',requested_change='Recompute using the supplied observations',acceptance='Show the corrected calculation',question_ids=[],fact_ids=['demo-1'])]
    return out
  return Model()

 def test_final_validation_returns_to_author_and_rebuilds_synthesis_and_checks(self):
  self.e.model=self.revision_model();r=self.initial()
  self.assertEqual(r['perspectives']['buffett']['thesis'],'Corrected 2+2=4')
  states=r['submission_recovery']['events'];self.assertTrue(any(e['state']=='invalidated' for e in states))
  author=[e for e in states if e['state']=='accepted' and e.get('target_role')=='buffett']
  self.assertEqual(author[-1]['supersedes'],author[0]['output_id'])
  invalid=next(e for e in self.s.events('submission_recovery') if e['body']['state']=='invalidated')
  final=[e for e in self.s.events('agent_input') if e['body']['payload'].get('analysis_stage')=='final_validation']
  self.assertEqual(len(final),2);self.assertGreater(final[-1]['seq'],invalid['seq'])
  self.assertEqual(final[-1]['body']['payload']['perspectives'],r['perspectives'])
  self.assertEqual(r['validation']['final_critique']['revision_requests'],[])
  self.assertGreater(len(self.s.events('proposal_reference_validation')),1)

 def test_research_request_returns_new_fact_before_author_and_final_revalidation(self):
  self.e.model=self.revision_model(True);self.e.research_library=SimpleNamespace(today='2026-11-14')
  def research(s,model,role,guide,payload,run_id,as_of,library):
   if payload.get('recovery_research'):
    f=dict(self.m['facts'][0],id='new-observation',text='Original synthetic observation 2+2=4')
    from mara.company_research import ResearchTools
    allocator=ResearchTools(library,s,run_id,as_of)
    assert allocator.activate(role,f,payload['market'])
    assert allocator.activation_budget['recovery_supplier']
   return payload
  with patch('mara.company_research.research_loop',side_effect=research):r=self.initial()
  returns=[e for e in r['submission_recovery']['events'] if e['state']=='research_returned']
  self.assertEqual(returns[0]['new_fact_ids'],['new-observation'])
  self.assertEqual(r['perspectives']['buffett']['thesis'],'Corrected 2+2=4')
  self.assertEqual(r['validation']['final_critique']['revision_requests'],[])

 def test_generation_contract_and_revision_scope_do_not_accept_invented_sources(self):
  payload={'market':self.m,'submission_sources':{'buffett':{'output_id':'current-accepted','output':{'thesis':'source'}}},'decision_scope':{'questions':[]}}
  c=bind(output_schema('buffett'),'buffett',payload)
  self.assertEqual(c['properties']['evidence_ids']['items']['enum'],['demo-1'])
  row=dict(id='q',target_role='buffett',source_output_id='current-accepted',issue_path='/thesis',kind='analysis_error',reason='Mismatch',requested_change='Check',acceptance='Consistent',question_ids=[],fact_ids=[])
  validate_revisions({'revision_requests':[row]},payload)
  for changed in (dict(row,source_output_id='foreign'),dict(row,target_role='wood'),dict(row,issue_path='/absent')):
   with self.assertRaises(ContractError):validate_revisions({'revision_requests':[changed]},payload)

 def test_global_budget_does_not_become_investment_defer(self):
  with patch('mara.submission_recovery.MAX_MODEL_CALLS',2):
   with self.assertRaisesRegex(RecoveryIncomplete,'global_model_call_budget'):self.initial()
  self.assertFalse(self.s.events('completed'));self.assertFalse(self.s.events('proposal'))
  self.assertEqual(self.s.latest('failed')['body']['recovery']['kind'],'system_incomplete')

 def test_verified_historical_observation_reuse_rejects_other_scope_and_dates(self):
  r=self.initial();done=self.s.get(r['event_id']);limit=done['seq']+1;boundary={'after_seq':0,'reset_id':None}
  facts=historical_facts(self.s,done['id'],['demo-1'],'2026-11-14',boundary,'demo',limit)
  self.assertEqual(facts,[self.m['facts'][0]])
  for mode,scope,day,seq in [('live',boundary,'2026-11-14',limit),('demo',{'after_seq':done['seq'],'reset_id':'reset'},'2026-11-14',limit),('demo',boundary,'2099-01-01',limit),('demo',boundary,'2026-11-14',done['seq'])]:
   with self.assertRaises(RecoveryIncomplete):historical_facts(self.s,done['id'],['demo-1'],day,scope,mode,seq)
  with self.assertRaises(PermissionError):historical_facts(self.other,done['id'],['demo-1'],'2026-11-14',boundary,'demo',limit)

 def test_evidence_submission_repair_has_one_author_resubmission(self):
  class Model(DemoModel):
   n=0
   def complete(inner,role,guide,p,c):
    out=super().complete(role,guide,p,c)
    if role=='evidence':
     inner.n+=1
     if inner.n<=2:out['facts']=['invented']
    return out
  model=Model();self.e.model=model;r=self.initial()
  self.assertEqual(model.n,3)
  self.assertEqual(len(self.s.events('recovery_leader_output')),1)
  self.assertEqual(r['evidence_feedback']['initial_evidence']['analysis']['facts'],['demo-1'])

 def test_latest_source_selected_by_sequence_across_stages(self):
  from mara.submission_recovery import Coordinator
  co=Coordinator(self.s,DemoModel(),'2026-11-14','run','guide')
  for stage,value in [('evidence','first'),('evidence_followup','second'),('evidence','third')]:
   oid=self.s.append('agent_output',{'role':'evidence','output':{'summary':value}},'2026-11-14','run');co.accepted('evidence',stage,oid)
  self.assertEqual(co.sources({'evidence'})['evidence']['output']['summary'],'third')

 def test_cases_are_independent_and_progress_uses_changed_source_not_new_ids(self):
  from mara.submission_recovery import Coordinator
  co=Coordinator(self.s,DemoModel(),'2026-11-14','run','guide')
  item=dict(id='r',target_role='buffett',source_output_id='out',issue_path='/thesis',kind='calculation_error',reason='fix',requested_change='fix',acceptance='correct',question_ids=[],fact_ids=[])
  sources={'buffett':{'output_id':'out','output':{'thesis':'wrong','risks':['wrong']}}}
  co.review('final_revision',[item],sources)
  sources['buffett']['output']['thesis']='partly improved'
  co.review('final_revision',[dict(item,id='new-id')],sources)
  co.review('final_revision',[dict(item,id='independent',issue_path='/risks')],sources)
  with self.assertRaisesRegex(RecoveryIncomplete,'no_diagnostic_progress'):
   co.review('final_revision',[dict(item,id='random-again',issue_path='/risks')],sources)

 def test_pending_revision_is_not_shown_as_accepted_current_analysis(self):
  seen=[];model=self.revision_model();original=model.complete
  def complete(role,guide,p,c):
   if role=='buffett' and p.get('revision_instructions'):
    run=self.s.latest('run_started')['run_id'];component=next(x for x in project(self.s,run)['components'] if x['id']=='buffett')
    seen.append((component['status'],component['output']))
   return original(role,guide,p,c)
  model.complete=complete;self.e.model=model;self.initial()
  self.assertEqual(seen,[('running',None)])
 def test_historical_original_is_budgeted_and_fully_delivered_before_bogle_revises(self,early=False):
  import json
  from mara.company_research import ResearchTools
  from mara.research import project_fact
  original=dict(self.m['facts'][0],id='historical-financial',research_tool='sec_financials',text=json.dumps({'entity':'Fixture','metrics':{'cash':[{'value':123}]}}))
  first_market=copy.deepcopy(self.m);first_market['facts'].append(original)
  first=self.e.run('2026-11-14',self.db.publish_market(first_market))
  seen=[]
  class Model(DemoModel):
   bogle_calls=0
   def complete(inner,role,guide,p,c):
    out=super().complete(role,guide,p,c)
    if c.get('$id')=='urn:mara:recovery-review:1.0':
     out['requests'][0]['historical_sources']=[{'completed_id':first['event_id'],'fact_ids':['historical-financial']}]
     out['requests'][0]['needs_research']=False
     return out
    if role=='bogle':
     inner.bogle_calls+=1
     if early and inner.bogle_calls<=2:out['evidence_ids']=['not-delivered']
     full=next((f for f in p['market']['facts'] if f['id']=='historical-financial'),None)
     out['thesis']='Corrected' if full and 'metrics' in json.loads(full['text']) else 'Needs original'
     if inner.bogle_calls>2 or p.get('revision_instructions'):seen.append(full)
    if role=='validation' and p.get('final_proposal') and p['perspectives']['bogle']['thesis']=='Needs original':
     out['revision_requests']=[dict(id='original',target_role='bogle',source_output_id=p['submission_sources']['bogle']['output_id'],issue_path='/thesis',kind='missing_evidence',reason='Read original metrics',requested_change='Read source',acceptance='Check 123',question_ids=[],fact_ids=[])]
    return out
  self.assertNotIn('metrics',json.loads(project_fact(original,'bogle')['text']))
  self.e.model=Model()
  result=self.e.run('2026-11-14',self.mid,force=True,revision_reason='Recheck supplied source',learning_review_id=first['event_id'])
  self.assertTrue(seen);self.assertEqual(seen[0],project_fact(original,'validation'))
  self.assertEqual(result['perspectives']['bogle']['thesis'],'Corrected')
  rows=[e for e in self.s.events('research_evidence') if e['run_id']==result['run_id']]
  self.assertEqual(rows[0]['body']['fact'],original);self.assertNotIn('carried_from',rows[0]['body'])
  self.assertEqual(sum(rows[0]['body']['budget_allocation'].values()),len(__import__('mara.domain',fromlist=['dumps']).dumps(original)))
  tool=ResearchTools(None,self.s,result['run_id'],'2026-11-14')
  self.assertFalse(tool.activate('evidence',dict(original,id='after-return'),{'facts':[]}))
  self.assertEqual(tool.activation_budget['blocked_reason'],'research_role_already_closed')

 def test_initial_submission_recovery_preserves_full_delivery_after_cache_invalidation(self):
  self.test_historical_original_is_budgeted_and_fully_delivered_before_bogle_revises(early=True)
 def test_evidence_own_research_request_is_not_silently_skipped(self):
  for scenario in ('unavailable','frozen','available'):
   with self.subTest(scenario=scenario):
    # Isolate each execution, including the frozen baseline and all budgets.
    self.tearDown();self.setUp()
    baseline=self.initial() if scenario=='frozen' else None
    counts={'evidence':0,'research':0}
    class Model(DemoModel):
     def complete(inner,role,guide,p,c):
      out=super().complete(role,guide,p,c)
      if c.get('$id')=='urn:mara:recovery-review:1.0':
       out['requests'][0]['needs_research']=True;return out
      if role=='evidence':
       counts['evidence']+=1
       if counts['evidence']<=2:out['facts']=['invented']
       elif scenario=='available':assert 'supplier-observation' in {f['id'] for f in p['market']['facts']}
      return out
    self.e.model=Model();self.e.research_library=None if scenario=='unavailable' else SimpleNamespace(today='2026-11-14')
    def research(s,model,role,guide,payload,run_id,as_of,lib):
     if payload.get('recovery_research'):
      from mara.company_research import ResearchTools
      counts['research']+=1
      assert ResearchTools(lib,s,run_id,as_of).activate(role,dict(self.m['facts'][0],id='supplier-observation'),payload['market'])
     return payload
    with patch('mara.company_research.research_loop',side_effect=research):
     if scenario=='available':
      self.initial();self.assertEqual(counts,{'evidence':3,'research':1})
      self.assertEqual(len(self.s.events('recovery_research_return')),1)
     else:
      with self.assertRaisesRegex(RecoveryIncomplete,'requested_research_unavailable'):
       if baseline:self.e.run('2026-11-14',force=True,revision_reason='Frozen',improvement={'parent_completed_id':baseline['event_id']})
       else:self.initial()
      self.assertEqual(counts,{'evidence':2,'research':0})
