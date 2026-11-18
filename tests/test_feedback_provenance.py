import tempfile,unittest,copy
from pathlib import Path
from mara.store import Store,Session,SHARED
from mara.feedback_provenance import present

class FeedbackProvenanceTests(unittest.TestCase):
 def fixture(self,tamper=None):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);db=Store(Path(tmp.name)/'db');self.addCleanup(db.close);s=db.session(db.create_user('owner'));day='2026-11-19'
  parent=s.append('completed',{'mode':'demo'},day,'parent');start={'previous_id':parent,'mode':'demo','history_scope':{'after_seq':0}}
  s.append('run_started',start,day,'source')
  old_out=s.append('agent_output',{'role':'buffett','output':{'evidence_requests':[{'need':'cash flow'}]}},day,'source')
  old_q=s.append('evidence_feedback_request',{'request_id':'r','source_output_id':old_out,'acceptance':'same period'},day,'source')
  old_r=s.append('evidence_feedback_return',{'responses':[{'request_id':'r','remaining_gap':'future outcome'}]},day,'source')
  failed=s.append('failed',{'error_type':'CodexError'},day,'source')
  s.append('run_started',start,day,'continued')
  out=s.append('agent_output',copy.deepcopy(s.get(old_out)['body']),day,'continued')
  q=s.append('evidence_feedback_request',{'request_id':'r','source_output_id':out,'acceptance':'altered' if tamper=='body' else 'same period'},day,'continued')
  response=s.append('evidence_feedback_return',copy.deepcopy(s.get(old_r)['body']),day,'continued')
  mapping={out:old_out,q:old_q,response:old_r}
  if tamper in ('foreign','shared'):
   other=db.session(db.create_user('foreign')) if tamper=='foreign' else Session(db,SHARED);mapping[q]=other.append('evidence_feedback_request',s.get(old_q)['body'],day,'source')
  if tamper=='omitted':mapping.pop(q)
  receipt={'source_failed_id':failed,'source_run_id':'source','id_mapping':mapping,'recorded_time_mapping':{}}
  s.append('execution_prefix_reuse',receipt,day,'continued')
  assessment=s.append('evidence_feedback_assessment',{'request_id':'r','request_event_id':q,'response_event_id':response,'assessment':{'request_id':'r','reason':'new assessment'}},day,'continued')
  new_out=s.append('agent_output',{'role':'leader','output':{'evidence_requests':[{'need':'new question'}]}},day,'continued')
  new_q=s.append('evidence_feedback_request',{'request_id':'new','source_output_id':new_out},day,'continued')
  body={'run_id':'continued','evidence_feedback':{'exchanges':[{'request_id':'r','requester':'buffett','need':'cash flow','request_event_id':q,'source_output_id':out,'response_event_id':response,'response':{'request_id':'r','remaining_gap':'future outcome'},'assessment_event_id':assessment,'assessment':{'request_id':'r','reason':'new assessment'}},{'request_id':'new','requester':'leader','need':'new question','request_event_id':new_q,'source_output_id':new_out}]}}
  completed=s.append('completed',body,day,'continued')
  return s,s.get(completed),q,new_q,old_q,assessment

 def test_original_times_and_new_assessment_remain_distinct_without_document_mutation(self):
  s,event,q,new_q,old_q,assessment=self.fixture();before=copy.deepcopy(event)
  result=present(s,event)['rows'];self.assertEqual(result[q]['queued']['status'],'reused');self.assertEqual(result[q]['queued']['origin_event_id'],old_q)
  self.assertEqual(result[q]['queued']['origin_recorded'],s.get(old_q)['recorded']);self.assertEqual(result[q]['queued']['current_recorded'],s.get(q)['recorded'])
  self.assertEqual(result[q]['response']['status'],'reused');self.assertEqual(result[q]['assessment']['status'],'new');self.assertEqual(result[q]['assessment']['origin_event_id'],assessment)
  self.assertEqual(result[new_q]['request']['status'],'new');self.assertEqual(result[new_q]['queued']['status'],'new');self.assertEqual(event,before);self.assertEqual(s.get(event['id']),before)

 def test_changed_or_other_owner_source_is_unverified_not_false_origin(self):
  for tamper in ('body','foreign','shared','omitted'):
   with self.subTest(tamper=tamper):
    s,event,q,_,_,_=self.fixture(tamper);row=present(s,event)['rows'][q]['queued'];self.assertEqual(row['status'],'unverified');self.assertNotIn('origin_recorded',row)

 def test_missing_foreign_run_future_and_wrong_kind_roots_do_not_look_new(self):
  s,event,q,new_q,old_q,_=self.fixture()
  future=s.append('evidence_feedback_request',{},event['effective'],event['run_id'])
  shared=Session(s.store,SHARED).append('evidence_feedback_request',{},event['effective'],event['run_id'])
  for bad in ('missing',old_q,future,shared,event['body']['evidence_feedback']['exchanges'][0]['source_output_id']):
   with self.subTest(bad=bad):
    altered=copy.deepcopy(event);altered['body']['evidence_feedback']['exchanges']=[{'request_event_id':bad}]
    row=present(s,altered)['rows'][bad]['queued'];self.assertEqual(row['status'],'unverified');self.assertNotIn('origin_recorded',row)

 def test_same_run_other_request_response_and_assessment_are_not_certified(self):
  s,event,q,new_q,_,_=self.fixture()
  # A wrong same-run edge recorded before the final report, not merely a future root.
  for label,field,kind,body in (
   ('response','response_event_id','evidence_feedback_return',{'responses':[{'request_id':'other','remaining_gap':'different question'}]}),
   ('assessment','assessment_event_id','evidence_feedback_assessment',{'request_id':'other','request_event_id':new_q,'response_event_id':'other','assessment':{}})):
   bad=s.append(kind,body,event['effective'],event['run_id'])
   row=copy.deepcopy(event['body']['evidence_feedback']['exchanges'][0]);row[field]=bad
   altered=copy.deepcopy(event);altered['seq']=s.get(bad)['seq']+1;altered['body']['evidence_feedback']['exchanges']=[row]
   result=present(s,altered)['rows'][q][label];self.assertEqual(result['status'],'unverified');self.assertNotIn('origin_recorded',result)
