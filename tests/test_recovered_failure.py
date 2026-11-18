"""Recovery provenance must preserve process failures without duplicating opinions."""
import tempfile,unittest
from pathlib import Path
from mara.store import Store
from mara.research_learning import process_failures

class RecoveredFailureTests(unittest.TestCase):
 def test_verified_terminal_failure_reaches_next_history_once_with_scoped_provenance(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=Store(Path(tmp)/'db');self.addCleanup(db.close);s=db.session(db.create_user('owner'));day='2026-11-19'
   parent=s.append('completed',{'mode':'demo'},day,'parent')
   def start(run,parent_id=parent,mode='demo',boundary=0):
    return s.append('run_started',{'previous_id':parent_id,'mode':mode,'history_scope':{'after_seq':boundary}},day,run)
   def fail(run,**kw):
    start(run,**kw);return s.append('failed',{'error_type':'CodexError','message':'PRIVATE_MODEL_OUTPUT'},day,run)
   valid=fail('source');mode=fail('wrong-mode',mode='live');scope=fail('wrong-scope',boundary=99);other=fail('wrong-parent',parent_id='other')
   start('future-source');future=s.append('failed',{'error_type':'Future'},'2026-11-20','future-source')
   start('recovered')
   for fid,run in ((valid,'source'),(valid,'source'),(mode,'wrong-mode'),(scope,'wrong-scope'),(other,'wrong-parent'),(valid,'forged-run'),('unknown','unknown'),(future,'future-source')):
    s.append('execution_prefix_reuse',{'source_failed_id':fid,'source_run_id':run},day,'recovered')
   # Another tenant cannot make its failure visible through a forged ID.
   foreign=db.session(db.create_user('foreign'));foreign_id=foreign.append('failed',{'error_type':'Other'},day,'foreign')
   s.append('execution_prefix_reuse',{'source_failed_id':foreign_id,'source_run_id':'foreign'},day,'recovered')
   completed=s.append('completed',{'previous_id':parent,'mode':'demo','history_scope':{'after_seq':0}},day,'recovered')
   late=fail('late')
   s.append('execution_prefix_reuse',{'source_failed_id':late,'source_run_id':'late'},day,'recovered')
   snapshot=s.append('fixture',{},day)
   rows=process_failures(s,s.get(completed),day,s.get(snapshot)['seq'])['items']
   self.assertEqual([r['failure_id'] for r in rows],[valid]);self.assertEqual(rows[0]['run_state'],'failed');self.assertEqual(rows[0]['recovery']['completed_id'],completed);self.assertEqual(rows[0]['recovery']['continuation_status'],'completed')
   self.assertNotIn('PRIVATE',str(rows));self.assertEqual(rows[0]['correction_status'],'not_completed')
   # It is a one-generation carried process observation, not a new failure on every run.
   start('following',parent_id=completed)
   following=s.append('completed',{'previous_id':completed,'mode':'demo','history_scope':{'after_seq':0}},day,'following')
   self.assertEqual(process_failures(s,s.get(following),day,s.get(following)['seq']+1)['items'],[])

 def test_recovered_rejection_is_not_counted_again_from_original_failed_prefix(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=Store(Path(tmp)/'db');self.addCleanup(db.close);s=db.session(db.create_user('owner'));day='2026-11-19'
   parent=s.append('completed',{},day,'parent')
   start={'previous_id':parent,'mode':'demo','history_scope':{'after_seq':0}}
   def rejected(run):
    iid=s.append('agent_input',{'role':'wood','payload':{}},day,run)
    oid=s.append('agent_output',{'role':'wood','input_id':iid,'output':{'SECRET':'not process evidence'}},day,run)
    return s.append('agent_validation',{'role':'wood','input_id':iid,'output_id':oid,'status':'rejected','code':'output_contract'},day,run)
   s.append('run_started',start,day,'source');original=rejected('source');failed=s.append('failed',{'error_type':'CodexError'},day,'source')
   s.append('run_started',start,day,'recovered');copied=rejected('recovered')
   s.append('execution_prefix_reuse',{'source_failed_id':failed,'source_run_id':'source'},day,'recovered')
   completed=s.append('completed',dict(start),day,'recovered')
   rows=process_failures(s,s.get(completed),day,s.get(completed)['seq']+1)['items']
   self.assertEqual({r['failure_id'] for r in rows},{failed,copied});self.assertNotIn(original,str(rows));self.assertNotIn('SECRET',str(rows))

 def test_nested_continuation_keeps_two_terminals_but_only_current_rejections(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=Store(Path(tmp)/'db');self.addCleanup(db.close);s=db.session(db.create_user('owner'));day='2026-11-19'
   parent=s.append('completed',{'mode':'demo'},day,'parent')
   start={'previous_id':parent,'mode':'demo','history_scope':{'after_seq':0}}
   terminals=[];rejections=[]
   for run in ('source-three','source-four','continuation-five'):
    s.append('run_started',start,day,run)
    iid=s.append('agent_input',{'role':'validation','payload':{}},day,run)
    oid=s.append('agent_output',{'role':'validation','input_id':iid,'output':{}},day,run)
    rejections.append(s.append('agent_validation',{'role':'validation','input_id':iid,'output_id':oid,'status':'rejected','code':'output_contract'},day,run))
    for source_run,failed in terminals:
     s.append('execution_prefix_reuse',{'source_run_id':source_run,'source_failed_id':failed},day,run)
    if run!='continuation-five':terminals.append((run,s.append('failed',{'error_type':'CodexError'},day,run)))
   completed=s.append('completed',start,day,'continuation-five')
   rows=process_failures(s,s.get(completed),day,s.get(completed)['seq']+1)['items']
   self.assertEqual({r['failure_id'] for r in rows},{fid for _,fid in terminals}|{rejections[-1]})
   self.assertEqual(len(rows),3)
   for row in rows:
    if row['kind']=='execution_failure':
     self.assertEqual(row['recovery']['completed_id'],completed)
     self.assertEqual(s.get(row['recovery']['receipt_id'])['run_id'],'continuation-five')

 def test_requester_coverage_failure_is_specific_safe_learning_input(self):
  from mara.evidence_feedback import FeedbackContractError
  from mara.decision_calibration import failure_subtype
  self.assertEqual(failure_subtype({},FeedbackContractError('PRIVATE_MESSAGE',{'request-a'},set())),'evidence_assessment_coverage')
  self.assertIsNone(failure_subtype({},ValueError('PRIVATE_MESSAGE')))
  with tempfile.TemporaryDirectory() as tmp:
   db=Store(Path(tmp)/'db');self.addCleanup(db.close);s=db.session(db.create_user('owner'));day='2026-11-19';run='r'
   s.append('run_started',{'mode':'demo','history_scope':{'after_seq':0}},day,run)
   iid=s.append('agent_input',{'role':'validation','payload':{'analysis_stage':'perspective_validation'}},day,run)
   oid=s.append('agent_output',{'role':'validation','input_id':iid,'output':{}},day,run)
   rejected=s.append('agent_validation',{'role':'validation','input_id':iid,'output_id':oid,'status':'rejected','code':'output_contract'},day,run)
   corrected=s.append('agent_input',{'role':'validation','payload':{'output_feedback':{'rejected_output_id':oid,'evidence_feedback_error':{'required_response_ids':['request-private'],'pending_request_ids':[],'instruction':'PRIVATE_INSTRUCTION'}}}},day,run)
   s.append('agent_validation',{'role':'validation','input_id':corrected,'output_id':'corrected-output','status':'accepted','code':'ok'},day,run)
   completed=s.append('completed',{'mode':'demo','history_scope':{'after_seq':0}},day,run)
   rows=process_failures(s,s.get(completed),day,s.get(completed)['seq']+1)['items'];self.assertEqual(len(rows),1)
   row=rows[0];self.assertEqual(row['failure_id'],rejected);self.assertEqual(row['subtype'],'evidence_assessment_coverage');self.assertEqual(row['diagnostic_source_id'],corrected);self.assertEqual(row['correction_status'],'accepted')
   self.assertNotIn('PRIVATE',str(rows));self.assertNotIn('request-private',str(rows))
