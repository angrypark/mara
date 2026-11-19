import copy,json,unittest
from unittest.mock import patch
from mara.agents import DemoModel
from mara.model_wire import VERSION as WIRE_VERSION
from mara.codex_model import CodexError,ProviderSubmissionError
from mara.continuation import prepare,LEGACY_MESSAGE
from mara.research_learning import history
from mara.workbench import project,run_state
import test_system as fixtures

class ContinuationTests(unittest.TestCase):
 setUp=fixtures.Harness.setUp
 tearDown=fixtures.Harness.tearDown
 initial=fixtures.Harness.initial
 def failed_prefix(self,learning=False):
  previous=self.initial() if learning else None
  captured={}
  class Model(DemoModel):
   input_wire_version=WIRE_VERSION
   def complete(inner,role,guide,p,c):
    out=super().complete(role,guide,p,c)
    if role=='marks':
     captured['raw']=json.dumps({'result_json':json.dumps(out)});raise CodexError(LEGACY_MESSAGE)
    return out
  self.e.model=Model()
  with self.assertRaises(CodexError):
   if previous:self.e.run('2026-11-14',self.mid,force=True,revision_reason='Learning review',learning_review_id=previous['event_id'])
   else:self.initial()
  failure=self.s.latest('failed');pending=self.s.latest('agent_input')
  return failure,pending,captured['raw']
 def test_same_run_continuation_preserves_exact_prefix_learning_and_failure_history(self):
  failed,pending,raw=self.failed_prefix(learning=True);run=failed['run_id']
  protected={e['id']:e['digest'] for e in self.s.events('knowledge')+self.s.events('profile')+self.s.events('actual')}
  starts=len(self.s.events('run_started'));applications=len(self.s.events('research_learning_application'));calls=[]
  class Model(DemoModel):
   input_wire_version=WIRE_VERSION
   def complete(inner,role,guide,p,c):
    calls.append(role)
    if len(calls)==1:
     assert role=='marks' and guide==pending['body']['guide'] and c==pending['body']['contract']
     expected=copy.deepcopy(pending['body']['payload']);expected['output_feedback']=p['output_feedback']
     assert p==expected
     assert p['output_feedback']['submission_diagnostic']['semantic_diagnostic']['reason']=='legacy_completion_unverified'
    return super().complete(role,guide,p,c)
  self.e.model=Model();plan=prepare(self.s,self.e.model,failed['id'],pending['id'],raw)
  self.assertEqual(plan['pending']['body'],pending['body'])
  result=self.e.resume(failed['id'],pending['id'],raw)
  self.assertEqual(result['run_id'],run);self.assertEqual(len(self.s.events('run_started')),starts)
  self.assertFalse(set(calls)&{'reflection','memory','context','evidence','buffett'})
  self.assertEqual(len(self.s.events('research_learning_application')),applications)
  self.assertEqual(len(self.s.events('knowledge')),sum(self.s.get(x)['kind']=='knowledge' for x in protected))
  self.assertTrue(all(self.s.get(k)['digest']==v for k,v in protected.items()))
  self.assertEqual(self.s.get(failed['id']),failed)
  self.assertEqual(result['execution_continuation']['raw_response_accepted'],False)
  self.assertEqual(project(self.s,run)['run']['status'],'completed')
  h=history(self.s,self.s.get(result['event_id']))
  original=next(x for x in h['process_failures']['items'] if x['failure_id']==failed['id'])
  self.assertEqual(original['run_state'],'failed');self.assertEqual(original['recovery']['continuation_status'],'completed')
  with self.assertRaises(ValueError):self.e.resume(failed['id'],pending['id'],raw)
 def test_scope_changed_pending_wrong_or_lock_active_prevents_new_calls(self):
  failed,pending,raw=self.failed_prefix();self.e.model=DemoModel()
  with self.assertRaises(PermissionError):prepare(self.other,self.e.model,failed['id'],pending['id'],raw)
  with self.assertRaises(ValueError):prepare(self.s,self.e.model,failed['id'],'wrong',raw)
  self.s.lock('unrelated')
  with self.assertRaises(RuntimeError):self.e.resume(failed['id'],pending['id'],raw)
  self.assertEqual(self.s.store.db.execute('select run_id from locks where owner=?',(self.s.owner,)).fetchone()[0],'unrelated')
  self.s.unlock('unrelated')
  self.e.set_profile(dict(self.p,goal='Changed after failure'),'2026-11-14')
  with self.assertRaisesRegex(ValueError,'state changed'):self.e.resume(failed['id'],pending['id'],raw)
  self.assertFalse(self.s.events('continuation_started'))
 def test_repeated_provider_completion_failure_is_rejected_even_with_valid_json(self):
  seen=[]
  class Model(DemoModel):
   input_wire_version=WIRE_VERSION
   n=0
   def complete(inner,role,guide,p,c):
    out=super().complete(role,guide,p,c)
    if role=='buffett':
     inner.n+=1
     if inner.n<=2:raise ProviderSubmissionError('completion_unverified',json.dumps({'result_json':json.dumps(out)}))
     seen.append(p)
    return out
  self.e.model=Model();r=self.initial()
  rows=[x['body'] for x in self.s.events('agent_validation') if x['body']['role']=='buffett']
  self.assertEqual([x['status'] for x in rows],['rejected','rejected','accepted'])
  self.assertEqual(rows[0]['code'],'provider_submission');self.assertTrue(seen[0]['revision_instructions'])
  original=self.s.get(rows[0]['output_id']);self.assertTrue(original['body']['raw_provider_response']);self.assertTrue(original['body']['provider_failure'])
  self.assertEqual(len(self.s.events('recovery_leader_output')),1)
 def test_interrupted_and_refailed_continuation_cannot_look_running_or_restart(self):
  failed,pending,raw=self.failed_prefix()
  class Model(DemoModel):
   input_wire_version=WIRE_VERSION
   def complete(inner,*args):raise CodexError('Synthetic authentication failure')
  self.e.model=Model()
  with self.assertRaises(CodexError):self.e.resume(failed['id'],pending['id'],raw)
  self.assertEqual(project(self.s,failed['run_id'])['run']['status'],'failed')
  self.assertFalse(self.s.store.db.execute('select * from locks').fetchall())
  self.assertEqual(len(self.s.events('continuation_failed')),1)
  with self.assertRaises(ValueError):self.e.resume(failed['id'],pending['id'],raw)
  fake=[{'kind':'failed','seq':1,'body':{}},{'kind':'recovery','seq':2,'body':{'status':'resuming','continuation_id':'one','pid':99999999,'process_birth':'never'}}]
  self.assertEqual(run_state(fake),'interrupted')

 def test_new_personal_answer_same_run_and_resource_change_prevent_continuation(self):
  failed,pending,raw=self.failed_prefix();self.e.model=DemoModel()
  with patch('mara.continuation.resource_fingerprint',return_value={}):
   with self.assertRaisesRegex(ValueError,'resource snapshot'):prepare(self.s,self.e.model,failed['id'],pending['id'],raw)
  self.s.append('clarification_answer',{'answer':'Changed personal constraint'},'2026-11-14',failed['run_id'])
  with self.assertRaisesRegex(ValueError,'state changed'):prepare(self.s,self.e.model,failed['id'],pending['id'],raw)

 def test_continuation_second_rejection_goes_to_leader_without_extra_local_attempt(self):
  failed,pending,raw=self.failed_prefix();seen=[]
  class Model(DemoModel):
   input_wire_version=WIRE_VERSION
   n=0
   def complete(inner,role,guide,p,c):
    seen.append((role,c.get('$id')));out=super().complete(role,guide,p,c)
    if role=='marks':
     inner.n+=1
     if inner.n==1:out['evidence_ids']=['not-delivered']
    return out
  self.e.model=Model();self.e.resume(failed['id'],pending['id'],raw)
  self.assertEqual([r for r,_ in seen[:3]],['marks','leader','marks'])
  rows=[e['body'] for e in self.s.events('agent_validation') if e['run_id']==failed['run_id'] and e['body']['role']=='marks']
  self.assertEqual([(r['attempt'],r['status']) for r in rows],[(1,'rejected'),(2,'rejected'),(1,'accepted')])

 def test_prepared_wire_input_budget_rejects_before_provider_and_keeps_source(self):
  from mara.agents import Agents
  from mara.submission_recovery import RecoveryIncomplete
  failed,pending,raw=self.failed_prefix();original=copy.deepcopy(pending)
  class Model(DemoModel):
   input_wire_version=WIRE_VERSION
   def complete(inner,*args):raise AssertionError('Provider must not be called')
  limited=copy.deepcopy(pending);limited['body']['payload']['input_budget']['max_characters']=64
  count=len(self.s.events('agent_input'))
  with self.assertRaisesRegex(RecoveryIncomplete,'submission_context_budget') as cm:
   Agents(self.s,Model(),'2026-11-14',failed['run_id']).submit_prepared(limited,{'rejected_output_id':'original-unaccepted'})
  self.assertEqual(cm.exception.diagnostic['source_output_id'],'original-unaccepted')
  self.assertEqual(self.s.latest('submission_input_validation')['body']['reason'],'submission_context_budget')
  self.assertEqual(len(self.s.events('agent_input')),count);self.assertEqual(self.s.get(pending['id']),original)
