import copy,json,unittest
from mara.codex_model import ProviderSubmissionError,CodexError,INPUT_LIMIT_MESSAGE
from mara.continuation import prepare
from mara.research_learning import history
from mara.agents import DemoModel
import test_routing_preflight as routing_fixtures
import test_system as fixtures

class PreparedSubmissionContinuationTests(unittest.TestCase):
 setUp=fixtures.Harness.setUp
 tearDown=fixtures.Harness.tearDown
 interrupted=routing_fixtures.FinalDispatchContinuationTests.interrupted
 final_interruption=routing_fixtures.FinalDispatchContinuationTests.final_interruption
 def pending_repair(self):
  third=self.final_interruption();original=self.e.model.complete;state=[]
  def complete(role,guide,p,c):
   out=original(role,guide,p,c)
   if role!='leader' or 'calls' in c.get('properties',{}):return out
   if p.get('output_feedback') and state==['rejected']:
    state.append('undelivered');raise CodexError(INPUT_LIMIT_MESSAGE)
   if p.get('reference_feedback') and not state:
    self.assertFalse(p['reference_feedback']['errors'])
    out['premise_changes']=['Read /reference_feedback/selected_weights_recomputed'];state.append('transient')
   elif p.get('reference_feedback',{}).get('errors') and state==['transient']:
    state[:]=['rejected'];raise ProviderSubmissionError('output_budget',json.dumps({'result_json':json.dumps(out)}),{'characters':39118,'limit':38000})
   return out
  self.e.model.complete=complete
  with self.assertRaisesRegex(CodexError,'1,048,576'):self.e.resume_dispatch(third['id'])
  return self.s.latest('failed')
 def test_four_failure_chain_resumes_exact_second_submission_and_reference_attempt(self):
  failure=self.pending_repair();pending=self.s.latest('agent_input');run=failure['run_id'];self.calls.clear()
  plan=prepare(self.s,self.e.model,failure['id'],None,None,pending_repair=True)
  self.assertEqual(plan['repair_submission']['reference_event']['body']['attempt'],2)
  self.assertEqual(len(plan['repair_submission']['reviews']),2)
  originals={e['id']:e['digest'] for k in ('failed','agent_input','agent_output','proposal_reference_validation') for e in self.s.events(k)}
  counts={k:len(self.s.events(k)) for k in ('run_started','knowledge','research_learning_application','recovery_leader_input','recovery_research_dispatch')}
  refs=len(self.s.events('proposal_reference_validation'));result=self.e.resume_repair(failure['id'])
  self.assertEqual(result['run_id'],run);self.assertEqual(counts,{k:len(self.s.events(k)) for k in counts})
  self.assertTrue(all(self.s.get(k)['digest']==v for k,v in originals.items()))
  self.assertEqual(self.calls[0],('leader',pending['body']['payload']))
  self.assertFalse({r for r,p in self.calls}&{'reflection','memory','context','evidence','buffett','marks','bogle','wood'})
  fresh=[e for e in self.s.events('agent_input') if e['seq']>pending['seq'] and e['body']['role']=='leader']
  self.assertEqual(len(fresh),1);self.assertEqual(fresh[0]['body']['payload'],pending['body']['payload'])
  validation=next(e for e in self.s.events('agent_validation') if e['body']['input_id']==fresh[0]['id'])
  self.assertEqual(validation['body']['attempt'],2);self.assertEqual(validation['body']['status'],'accepted')
  checks=self.s.events('proposal_reference_validation')[refs:]
  self.assertEqual(len(checks),1);self.assertEqual(checks[0]['body']['attempt'],3);self.assertEqual(checks[0]['body']['status'],'passed')
  self.assertEqual(len(self.s.events('continuation_reference_verified')),1)
  self.assertEqual(len(result['execution_continuation']['source_failed_ids']),4)
  next_history=history(self.s,self.s.get(result['event_id']))
  for fid in result['execution_continuation']['source_failed_ids']:
   row=next(x for x in next_history['process_failures']['items'] if x['failure_id']==fid)
   self.assertEqual(row['recovery']['continuation_status'],'completed')
  with self.assertRaises(ValueError):self.e.resume_repair(failure['id'])
 def test_reference_rejection_is_consumed_next_run_only_after_both_submission_and_reference_pass(self):
  failure=self.pending_repair();run=failure['run_id']
  before=history(self.s,self.s.get(self.prior_id),failure['effective'],failure['seq']+1)
  rows=[r for r in before['process_failures']['items'] if r['kind']=='proposal_reference_rejection']
  self.assertEqual(len(rows),1);bad=rows[0]
  self.assertEqual(bad['source_submission_status'],'accepted');self.assertEqual(bad['source_reference_status'],'failed')
  self.assertEqual(bad['correction_status'],'not_completed')
  self.assertEqual({x['submission_status'] for x in bad['correction_attempts']},{'rejected','not_completed'})
  self.assertFalse(bad['verified_corrections'])
  self.assertNotIn('Fully corrected',json.dumps(bad))
  normal=[e['id'] for e in self.s.events('proposal_reference_validation') if e['run_id']==run and not e['body']['errors']]
  self.assertTrue(normal);self.assertFalse(set(normal)&{r['failure_id'] for r in before['process_failures']['items']})
  done=self.e.resume_repair(failure['id']);after=history(self.s,self.s.get(done['event_id']))
  row=next(r for r in after['process_failures']['items'] if r['failure_id']==bad['failure_id'])
  self.assertEqual(row['correction_status'],'accepted');self.assertEqual(len(row['verified_corrections']),1)
  verified=row['verified_corrections'][0];self.assertEqual(verified['submission_status'],'accepted');self.assertEqual(verified['reference_status'],'passed')
  seen=[]
  class Captured(Exception):pass
  class NextModel(DemoModel):
   def complete(inner,role,guide,p,c):
    if role=='reflection':
     observed=p['research_feedback_history']['process_failures']['items']
     seen.append(next(r for r in observed if r['failure_id']==bad['failure_id']))
     raise Captured()
    return super().complete(role,guide,p,c)
  self.e.model=NextModel()
  with self.assertRaises(Captured):self.e.run('2026-11-14',self.current_id,force=True,revision_reason='Verify next reflection',learning_review_id=done['event_id'])
  self.assertEqual(seen,[row])
 def test_changed_personal_state_and_post_pending_output_are_rejected_without_model_call(self):
  for kind in ('profile','output'):
   with self.subTest(kind=kind):
    self.tearDown();self.setUp();failure=self.pending_repair();self.calls.clear()
    if kind=='profile':self.e.set_profile(dict(self.p,goal='Changed'),'2026-11-14')
    else:self.s.append('agent_output',{'role':'leader','input_id':self.s.latest('agent_input')['id'],'output':{}},failure['effective'],failure['run_id'])
    count=len(self.s.events('continuation_started'))
    with self.assertRaises(ValueError):self.e.resume_repair(failure['id'])
    self.assertFalse(self.calls);self.assertEqual(len(self.s.events('continuation_started')),count)

if __name__=='__main__':unittest.main()
