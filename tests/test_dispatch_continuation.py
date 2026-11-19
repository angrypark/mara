import copy,unittest
from unittest.mock import patch
from mara.agents import DemoModel
from mara.continuation import prepare
from mara.submission_recovery import same_observation,reference_scope,Coordinator,RecoveryIncomplete
from mara.research_learning import history
from mara.codex_model import CodexError
from mara.continuation import LEGACY_MESSAGE
import test_system as fixtures

class DispatchContinuationTests(unittest.TestCase):
 setUp=fixtures.Harness.setUp
 tearDown=fixtures.Harness.tearDown
 initial=fixtures.Harness.initial
 def interrupted(self,legacy=False):
  original=dict(self.m['facts'][0],id='archive-source',raw_refs=[{'source':'https://example.com/original','sha256':'a'*64,'bytes':100,'cache_hit':False,'retrieved_at':'2026-11-14T01:00:00+00:00'}])
  before=copy.deepcopy(self.m);before['facts'].append(original)
  prior=self.e.run('2026-11-14',self.db.publish_market(before))
  current=copy.deepcopy(before);current['facts'][-1]['raw_refs'][0].update(cache_hit=True,retrieved_at='2026-11-14T02:00:00+00:00')
  self.current_id=self.db.publish_market(current);calls=[]
  captured={}
  class Model(DemoModel):
   def complete(inner,role,guide,p,c):
    calls.append((role,copy.deepcopy(p)));out=super().complete(role,guide,p,c)
    if c.get('$id')=='urn:mara:recovery-review:1.0':
     for i,q in enumerate(out['requests']):
      q['needs_research']=False;q['historical_sources']=[{'completed_id':prior['event_id'],'fact_ids':['demo-1' if i==0 else 'archive-source']}]
    elif role=='marks':
     out['thesis']='Corrected' if p.get('revision_instructions') else 'Needs checking'
     if legacy and not captured:
      import json
      captured['raw']=json.dumps({'result_json':json.dumps(out)});raise CodexError(LEGACY_MESSAGE)
    elif role=='validation' and not p.get('final_proposal') and p['perspectives']['marks']['thesis']!='Corrected':
     out['revision_requests']=[dict(id='fix-'+str(i),target_role='marks',source_output_id=p['submission_sources']['marks']['output_id'],issue_path='/thesis' if i==0 else '/risks',kind='calculation_error',reason='Check '+str(i),requested_change='Recheck original',acceptance='Both requests evaluated',question_ids=[],fact_ids=[]) for i in range(2)]
    return out
  self.e.model=Model();self.calls=calls
  # Reproduce the original full-dict collision after the first return.
  with patch('mara.submission_recovery.same_observation',side_effect=lambda a,b:a==b):
   def run():return self.e.run('2026-11-14',self.current_id,force=True,revision_reason='Same-source review',learning_review_id=prior['event_id'])
   if legacy:
    with self.assertRaises(CodexError):run()
    first=self.s.latest('failed');pending=self.s.latest('agent_input');self.initial_failure_id=first['id']
    with self.assertRaisesRegex(RecoveryIncomplete,'historical_fact_collision'):self.e.resume(first['id'],pending['id'],captured['raw'])
   else:
    with self.assertRaisesRegex(RecoveryIncomplete,'historical_fact_collision'):run()
  return self.s.latest('failed')
 def test_partial_dispatch_continues_same_run_with_both_instructions_and_no_duplicates(self):
  failure=self.interrupted();run=failure['run_id'];self.calls.clear()
  kinds=('run_started','knowledge','research_learning_application','recovery_leader_input','recovery_research_dispatch')
  counts={k:len(self.s.events(k)) for k in kinds};returns=len(self.s.events('recovery_research_return'))
  originals={e['id']:e['digest'] for e in self.s.events('agent_output')+self.s.events('failed')}
  result=self.e.resume_dispatch(failure['id']);self.assertEqual(result['run_id'],run)
  self.assertEqual({k:len(self.s.events(k)) for k in kinds},counts)
  self.assertEqual(len(self.s.events('recovery_research_return')),returns+1)
  self.assertTrue(all(self.s.get(k)['digest']==v for k,v in originals.items()))
  self.assertEqual(self.calls[0][0],'marks');p=self.calls[0][1]
  self.assertEqual([q['id'] for q in p['revision_instructions']],['fix-0','fix-1'])
  self.assertEqual({f for q in p['revision_instructions'] for f in q['fact_ids']},{'demo-1','archive-source'})
  self.assertEqual({role for role,_ in self.calls}&{'reflection','memory','context','evidence','buffett','bogle','wood'},set())
  self.assertEqual(result['perspectives']['marks']['thesis'],'Corrected')
  self.assertFalse(result['validation']['final_critique']['revision_requests'])
  history_rows=history(self.s,self.s.get(result['event_id']))['process_failures']['items']
  self.assertTrue(any(x['failure_id']==failure['id'] and x['recovery']['continuation_status']=='completed' for x in history_rows))
  with self.assertRaises(ValueError):self.e.resume_dispatch(failure['id'])
 def test_preserves_review_budget_and_no_progress_signature(self):
  failure=self.interrupted();plan=prepare(self.s,self.e.model,failure['id'],None,None,pending_dispatch=True)
  x=plan['dispatch'];co=Coordinator(self.s,self.e.model,failure['effective'],failure['run_id'],'guide');co.restore_review(x['packet'],x['leader_output_id'])
  self.assertEqual(co.reviews,1);self.assertTrue(all(n==1 for n in co.rounds.values()))
  with self.assertRaisesRegex(RecoveryIncomplete,'no_diagnostic_progress'):
   co.review(x['packet']['case_id'],x['packet']['work_items'],x['packet']['sources'])
 def test_new_personal_state_prevents_resume_before_models(self):
  failure=self.interrupted();self.calls.clear();self.e.set_profile(dict(self.p,goal='Changed'),'2026-11-14')
  with self.assertRaisesRegex(ValueError,'state changed'):self.e.resume_dispatch(failure['id'])
  self.assertFalse(self.calls)
 def test_real_failure_chain_retains_both_original_failures_in_next_learning(self):
  failure=self.interrupted(legacy=True);self.calls.clear();run=failure['run_id']
  before={k:len(self.s.events(k)) for k in ('run_started','knowledge','research_learning_application','recovery_leader_input','recovery_research_dispatch')}
  result=self.e.resume_dispatch(failure['id'])
  self.assertEqual(result['run_id'],run);self.assertEqual(before,{k:len(self.s.events(k)) for k in before})
  self.assertEqual(result['execution_continuation']['source_failed_ids'],[self.initial_failure_id,failure['id']])
  h=history(self.s,self.s.get(result['event_id']))['process_failures']['items']
  for fid in (self.initial_failure_id,failure['id']):
   row=next(x for x in h if x['failure_id']==fid);self.assertEqual(row['run_state'],'failed');self.assertEqual(row['recovery']['continuation_status'],'completed')
  self.assertEqual(self.calls[0][0],'marks');self.assertEqual(len(self.calls[0][1]['revision_instructions']),2)
 def test_extra_request_dispatch_return_and_post_dispatch_author_call_are_rejected(self):
  for kind in ('request','dispatch','return','author_call'):
   with self.subTest(kind=kind):
    self.tearDown();self.setUp();failure=self.interrupted();self.calls.clear();run=failure['run_id']
    if kind=='request':
     source=next(e for e in self.s.events('submission_recovery') if e['run_id']==run and e['body']['state']=='author_requested');body=copy.deepcopy(source['body']);body['request']['instruction']='Unverified replacement';self.s.append('submission_recovery',body,failure['effective'],run)
    elif kind=='dispatch':
     body=copy.deepcopy(self.s.latest('recovery_research_dispatch')['body']);body['request_id']='not-routed';self.s.append('recovery_research_dispatch',body,failure['effective'],run)
    elif kind=='return':
     body=copy.deepcopy(self.s.latest('recovery_research_return')['body']);body['fact_ids']=['wrong'];self.s.append('recovery_research_return',body,failure['effective'],run)
    else:
     body=copy.deepcopy(self.s.latest('agent_input')['body']);body['role']='marks';self.s.append('agent_input',body,failure['effective'],run)
    with self.assertRaises(ValueError):self.e.resume_dispatch(failure['id'])
    self.assertFalse(self.calls)
 def test_observation_equivalence_does_not_relax_content_or_source(self):
  a={'id':'same','known_at':'2026-11-14','text':'123 USD','raw_refs':[{'source':'https://example.com/a','sha256':'a'*64,'bytes':100,'cache_hit':False,'retrieved_at':'2026-11-14T01:00:00+00:00'}]}
  b=copy.deepcopy(a);b['raw_refs'][0].update(cache_hit=True,retrieved_at='2026-11-14T02:00:00+00:00')
  self.assertTrue(same_observation(a,b))
  for field,value in [('id','other'),('known_at','2026-11-13'),('text','123 million USD')]:
   changed=copy.deepcopy(b);changed[field]=value;self.assertFalse(same_observation(a,changed))
  for field,value in [('source','https://example.com/b'),('sha256','b'*64),('bytes',101),('retrieved_at','unknown')]:
   changed=copy.deepcopy(b);changed['raw_refs'][0][field]=value;self.assertFalse(same_observation(a,changed))
 def test_reference_scope_uses_original_author_indices_and_stable_identity(self):
  row={'request_id':'AMZN-stable','question_id':'candidate-AMZN','response':{'request_id':'AMZN-stable','status':'partial','fact_ids':['one']}}
  iid=self.s.append('agent_input',{'role':'marks','payload':{'research_feedback_history':{'requests':[{'request_id':'NVDA'},row]}}},'2026-11-14','r')
  oid=self.s.append('agent_output',{'role':'marks','input_id':iid,'output':{'thesis':'/research_feedback_history/requests/1/response'}},'2026-11-14','r')
  scope=reference_scope(self.s,oid);mapping=scope['mappings'][1]
  self.assertEqual(scope['source_input_id'],iid);self.assertEqual(mapping['path'],'/research_feedback_history/requests/1')
  self.assertEqual(mapping['request_id'],mapping['response_request_id']);self.assertEqual(mapping['request_id'],'AMZN-stable')
  self.assertEqual(len(mapping['response_sha256']),64)
  bad=copy.deepcopy(row);bad['response']['request_id']='unrelated'
  bid=self.s.append('agent_input',{'payload':{'evidence_feedback':[bad]}},'2026-11-14','r')
  boid=self.s.append('agent_output',{'input_id':bid},'2026-11-14','r')
  with self.assertRaisesRegex(ValueError,'identity mismatch'):reference_scope(self.s,boid)

if __name__=='__main__':unittest.main()
