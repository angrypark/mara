import copy,tempfile,unittest
from pathlib import Path
from mara.store import Store
from mara.report_audit import record,findings,digest
from mara.research_learning import process_failures

class ReportAuditTests(unittest.TestCase):
 def fixture(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);db=Store(Path(tmp.name)/'db');self.addCleanup(db.close);s=db.session(db.create_user('owner'));day='2026-11-19';run='r'
  fact={'id':'f','published_at':day,'known_at':day,'valid_until':day,'text':'synthetic original observations'}
  market=s.append('market',{'facts':[fact]},day)
  s.append('run_started',{'mode':'demo','history_scope':{'after_seq':0}},day,run)
  inp=s.append('agent_input',{'role':'validation','payload':{}},day,run)
  out=s.append('agent_output',{'role':'validation','input_id':inp,'output':{'reason':'Value is 1.31'}},day,run)
  s.append('agent_validation',{'role':'validation','input_id':inp,'output_id':out,'status':'accepted'},day,run)
  done=s.append('completed',{'run_id':run,'mode':'demo','market_id':market,'as_of':day,'history_scope':{'after_seq':0}},day,run)
  body={'source_completed_id':done,'source_output_id':out,'source_body_sha256':digest(s.get(out)['body']),
   'source_path':'/output/reason','original_text':'Value is 1.31','original_sha256':digest('Value is 1.31'),
   'code':'arithmetic_rounding','classification':'verified_arithmetic_correction','reviewer':'independent_test_review',
   'review_summary':'Check the original period and rounding','correction_or_review':'Correct display is 1.30',
   'limits':'Synthetic verification; no decision or performance claim','scope':'process_review_only','fact_hashes':{'f':digest(fact)},
   'verification':{'formula':'(4-1-0.4)/2','result':'1.30','unit':'USD/share','period':'synthetic','rounding':'half up 2 decimals','script_sha256':'a'*64,'artifact_sha256':'b'*64}}
  return s,s.get(done),body,day

 def test_append_only_idempotent_and_next_learning_is_separate_process_evidence(self):
  s,done,body,day=self.fixture();original=copy.deepcopy(done);eid=record(s,body,day)
  self.assertEqual(record(s,body,day),eid);self.assertEqual(s.get(done['id']),original)
  self.assertEqual(findings(s,done)[0]['event_id'],eid)
  before=s.get(eid)['seq'];self.assertEqual(process_failures(s,done,day,before)['items'],[])
  rows=process_failures(s,done,day,before+1)['items'];self.assertEqual(len(rows),1)
  self.assertEqual(rows[0]['kind'],'independent_post_run_review');self.assertEqual(rows[0]['run_state'],'completed');self.assertEqual(rows[0]['failure_id'],eid)
  self.assertEqual(rows[0]['review_detail']['correction_or_review'],'Correct display is 1.30');self.assertEqual(rows[0]['review_detail']['verification'],body['verification']);self.assertEqual(rows[0]['review_detail']['limits'],body['limits']);self.assertNotIn('original_text',rows[0]);self.assertNotIn('fact_hashes',rows[0]);self.assertEqual(s.get(done['id']),original)

 def test_bad_source_pointer_original_fact_and_proof_hashes_are_rejected(self):
  s,done,body,day=self.fixture()
  for key,value in (('source_path','/output/missing'),('original_sha256','0'*64),('source_body_sha256','0'*64),('fact_hashes',{'f':'0'*64}),('scope','market_fact')):
   with self.subTest(key=key):
    changed=copy.deepcopy(body);changed[key]=value
    with self.assertRaises((ValueError,KeyError)):record(s,changed,day)
  other=s.append('agent_output',{'role':'validation','output':{'reason':'Value is 1.31'}},day,'other-run')
  changed=dict(body,source_output_id=other)
  with self.assertRaises(ValueError):record(s,changed,day)
  self.assertEqual(findings(s,done),[])

 def test_scope_opinion_keeps_its_type_and_does_not_claim_arithmetic_verification(self):
  s,done,body,day=self.fixture();body.update(code='conditional_scope_mixed',classification='independent_scope_review',fact_hashes={},correction_or_review='Separate conditional research from execution confirmation')
  body.pop('verification');record(s,body,day)
  self.assertEqual(findings(s,done)[0]['classification'],'independent_scope_review')
  self.assertEqual(s.get(done['id'])['body'],done['body'])
