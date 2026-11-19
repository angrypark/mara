import copy,json,unittest
from unittest.mock import patch
from mara.agents import DemoModel
from mara.submission_recovery import Coordinator,RecoveryIncomplete
from mara.codex_model import ProviderSubmissionError
from mara.research_learning import history
import test_dispatch_continuation as dispatch_fixtures
import test_system as fixtures

class RoutingPreflightTests(unittest.TestCase):
 setUp=fixtures.Harness.setUp
 tearDown=fixtures.Harness.tearDown
 def test_all_conflicting_historical_ids_are_returned_before_any_dispatch(self):
  s=self.s;seen=[]
  class Model(DemoModel):
   def complete(inner,role,guide,p,c):
    out=super().complete(role,guide,p,c);seen.append(copy.deepcopy(p))
    if len(seen)==1:out['requests'][0]['historical_sources']=[{'completed_id':'unoffered','fact_ids':['unknown']},{'completed_id':'prior','fact_ids':['quote','fund']}]
    else:
     assert [e['fact_id'] for e in p['repair']['routing_issues']]==['unknown','quote','fund']
     assert not s.events('recovery_research_dispatch')
     assert not [e for e in s.events('submission_recovery') if e['body']['state'] in ('dispatched','author_requested')]
     out['requests'][0]['instruction']='Use the current delivered quote and fund observations; preserve their dates.'
    return out
  co=Coordinator(s,Model(),'2026-11-14','r','guide')
  item=dict(id='fix',target_role='leader',source_output_id='source',issue_path='/rationale',kind='calculation_error',reason='Compare alternatives',requested_change='Recompute',acceptance='Current facts used',question_ids=[],fact_ids=[])
  sources={'leader':{'output_id':'source','output':{'rationale':'Draft'}}}
  catalog=[{'completed_id':'prior','facts':[{'id':i,'current_relation':'different_observation'} for i in ('quote','fund')]}]
  routes=co.review('final_revision',[item],sources,historical_catalog=catalog)
  self.assertEqual(routes[0]['historical_sources'],[]);self.assertEqual(co.reviews,1)
  self.assertEqual(len(s.events('recovery_leader_input')),2)
  self.assertEqual([e['body']['status'] for e in s.events('recovery_leader_validation')],['rejected','accepted'])
  rejected=s.events('recovery_leader_validation')[0]['body'];self.assertEqual(len(rejected['routing_issues']),3)
  self.assertEqual(s.get(rejected['output_id'])['body']['output']['requests'][0]['historical_sources'][1]['fact_ids'],['quote','fund'])
  self.assertEqual(len([e for e in s.events('submission_recovery') if e['body']['state']=='dispatched']),1)
 def test_unattested_routing_response_uses_same_bounded_correction(self):
  class Model(DemoModel):
   n=0
   def complete(inner,role,guide,p,c):
    inner.n+=1;out=super().complete(role,guide,p,c)
    if inner.n==1:raise ProviderSubmissionError('completion_unverified',json.dumps({'result_json':json.dumps(out)}))
    return out
  model=Model();co=Coordinator(self.s,model,'2026-11-14','r','guide')
  item=dict(id='fix',target_role='leader',source_output_id='source',issue_path='/rationale',kind='calculation_error',reason='Recheck',requested_change='Fix',acceptance='Valid',question_ids=[],fact_ids=[])
  co.review('final_revision',[item],{'leader':{'output_id':'source','output':{'rationale':'Draft'}}})
  self.assertEqual(model.n,2);self.assertEqual(co.reviews,1)
  outputs=self.s.events('recovery_leader_output');self.assertIn('provider_failure',outputs[0]['body'])
  self.assertEqual([e['body']['status'] for e in self.s.events('recovery_leader_validation')],['rejected','accepted'])
 def test_transient_author_input_citation_is_repaired_before_final_validation(self):
  from mara.report_references import errors
  proposal={'premise_changes':['Recomputed at /reference_feedback/selected_weights_recomputed'],
   'change_response':{'reason':'Confirmed in /reference_feedback/selected_weights_recomputed'}}
  found=errors(proposal,{}, {}, {})
  self.assertEqual({e['path'] for e in found},{'/proposal/premise_changes/0','/proposal/change_response/reason'})
  self.assertTrue(all('not evidence fabrication' in e['reason'] for e in found))
  proposal['premise_changes']=['Recomputed at /analysis/selected_comparison'];proposal['change_response']['reason']='Checked current selected comparison'
  self.assertEqual(errors(proposal,{}, {}, {}),[])

class FinalDispatchContinuationTests(unittest.TestCase):
 setUp=fixtures.Harness.setUp
 tearDown=fixtures.Harness.tearDown
 interrupted=dispatch_fixtures.DispatchContinuationTests.interrupted
 def final_interruption(self,extra_marks_cycle=False):
  failure=self.interrupted(legacy=True);original=self.e.model.complete;s=self.s;prior=self.prior_id;extra_sent=[]
  def complete(role,guide,p,c):
   out=original(role,guide,p,c)
   if c.get('$id')=='urn:mara:recovery-review:1.0' and any(q['id']=='extra-marks' for q in out['requests']):
    for q in out['requests']:q['historical_sources']=[];q['needs_research']=False
   elif c.get('$id')=='urn:mara:recovery-review:1.0' and p['case_id']=='final_revision':
    for q in out['requests']:q['historical_sources']=[];q['needs_research']=False
    if not p.get('repair'):out['requests'][-1]['historical_sources']=[{'completed_id':prior,'fact_ids':['conflict-1','conflict-2']}]
    else:
     assert len(p['repair']['routing_issues'])==2
     assert s.latest('recovery_research_cancelled')['body']['status']=='cancelled_before_delivery'
   elif role=='leader' and (p.get('revision_instructions') or p.get('reference_feedback',{}).get('previous_output',{}).get('rationale','').startswith('Fully corrected')):out['rationale']='Fully corrected report using current observations'
   elif role=='validation' and p.get('final_proposal') and not p['final_proposal']['rationale'].startswith('Fully corrected'):
    source=p['submission_sources']['leader']['output_id']
    out['revision_requests']=[dict(id='final-'+str(i),target_role='leader',source_output_id=source,issue_path='/rationale' if i==0 else '/risks',kind='calculation_error',reason='Final report needs correction',requested_change='Fix current report',acceptance='All current comparisons included',question_ids=[],fact_ids=[]) for i in (0,1)]
   elif extra_marks_cycle and not extra_sent and role=='validation' and 'calls' not in c.get('properties',{}) and p.get('analysis_stage')=='perspective_validation' and p.get('perspectives',{}).get('marks',{}).get('thesis')=='Corrected':
    extra_sent.append(True)
    out['revision_requests']=[dict(id='extra-marks',target_role='marks',source_output_id=p['submission_sources']['marks']['output_id'],issue_path='/weights',kind='calculation_error',reason='Second independent correction',requested_change='Recheck weights',acceptance='Weights checked',question_ids=[],fact_ids=[])]
   return out
  self.e.model.complete=complete
  with patch('mara.submission_recovery.routing_issues',return_value=[]):
   with self.assertRaisesRegex(RecoveryIncomplete,'historical_fact_collision'):self.e.resume_dispatch(failure['id'])
  return self.s.latest('failed')
 def test_earlier_author_fact_deliveries_survive_a_later_correction_without_repeated_ids(self):
  from mara.continuation import prepare
  failure=self.final_interruption(extra_marks_cycle=True)
  plan=prepare(self.s,self.e.model,failure['id'],None,None,pending_dispatch=True)
  latest=plan['final_dispatch']['perspectives']['marks'][1]
  last_input=self.s.get(self.s.get(latest)['body']['input_id'])['body']['payload']
  self.assertEqual([q['id'] for q in last_input['revision_instructions']],['extra-marks'])
  self.assertFalse(last_input['revision_instructions'][0]['fact_ids'])
  self.assertEqual(set(plan['final_dispatch']['role_fact_deliveries']['marks']),{'demo-1','archive-source'})
  self.calls.clear();result=self.e.resume_dispatch(failure['id'])
  self.assertEqual(result['run_id'],failure['run_id'])
  self.assertFalse(any(r=='marks' for r,p in self.calls))
 def test_actual_three_failure_chain_restores_final_stage_and_repairs_without_prefix_regeneration(self):
  failure=self.final_interruption();run=failure['run_id'];self.calls.clear()
  kinds=('run_started','knowledge','research_learning_application','recovery_research_dispatch','recovery_research_return')
  counts={k:len(self.s.events(k)) for k in kinds};models=len(self.s.events('recovery_leader_input'))
  originals={e['id']:e['digest'] for kind in ('agent_output','failed','recovery_leader_output','recovery_research_dispatch','recovery_research_return') for e in self.s.events(kind)}
  result=self.e.resume_dispatch(failure['id'])
  self.assertEqual(result['run_id'],run);self.assertEqual(counts,{k:len(self.s.events(k)) for k in kinds})
  self.assertEqual(len(self.s.events('recovery_leader_input')),models+1)
  self.assertTrue(all(self.s.get(k)['digest']==v for k,v in originals.items()))
  self.assertEqual(self.calls[0][0],'leader');self.assertEqual(self.calls[0][1]['analysis_stage'],'submission_review')
  self.assertEqual(self.calls[0][1]['budget']['reviews_used'],2)
  self.assertFalse({r for r,_ in self.calls}&{'reflection','memory','context','evidence','buffett','marks','bogle','wood'})
  self.assertEqual(len(self.s.events('recovery_research_cancelled')),1)
  changed=[p for role,p in self.calls if role=='leader' and p.get('revision_instructions')]
  self.assertTrue(changed);self.assertEqual(len(changed[0]['revision_instructions']),2)
  states=[e['body'] for e in self.s.events('submission_recovery') if e['run_id']==run]
  self.assertEqual(sum(x['state']=='author_request_withdrawn' for x in states),2)
  replacements=[x for x in states if x['state']=='author_requested' and x.get('replaces_request_event_id')]
  self.assertEqual(len(replacements),2)
  self.assertTrue(result['proposal']['rationale'].startswith('Fully corrected'))
  h=history(self.s,self.s.get(result['event_id']))
  self.assertEqual(len(result['execution_continuation']['source_failed_ids']),3)
  for fid in result['execution_continuation']['source_failed_ids']:
   row=next(x for x in h['process_failures']['items'] if x['failure_id']==fid)
   self.assertEqual(row['run_state'],'failed');self.assertEqual(row['recovery']['continuation_status'],'completed')
  self.assertTrue(any(x['state']=='research_cancelled' for x in h['submission_recovery']['events']))
  with self.assertRaises(ValueError):self.e.resume_dispatch(failure['id'])
 def test_final_stage_rejects_extra_dispatch_author_progress_and_changed_inputs_before_calls(self):
  for kind in ('dispatch','author','profile'):
   with self.subTest(kind=kind):
    self.tearDown();self.setUp();failure=self.final_interruption();self.calls.clear();run=failure['run_id']
    if kind=='dispatch':
     body=copy.deepcopy(self.s.latest('recovery_research_dispatch')['body']);body['request_id']='not-routed'
     self.s.append('recovery_research_dispatch',body,failure['effective'],run)
    elif kind=='author':
     body=copy.deepcopy(self.s.latest('agent_input')['body']);body['role']='leader'
     self.s.append('agent_input',body,failure['effective'],run)
    else:self.e.set_profile(dict(self.p,goal='Changed conditions'),'2026-11-14')
    count=len(self.s.events('continuation_started'))
    with self.assertRaises(ValueError):self.e.resume_dispatch(failure['id'])
    self.assertFalse(self.calls);self.assertEqual(len(self.s.events('continuation_started')),count)

if __name__=='__main__':unittest.main()
