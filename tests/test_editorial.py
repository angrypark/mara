import copy,unittest
from mara.editorial import check,inputs,presented,period,create
from mara.final_report import digest

class EditorialTests(unittest.TestCase):
 def setUp(self):
  self.report={'as_of':'2026-11-18','proposal':{'action':'defer','weights':{'CASH':1},'investment_case':{'claims':[{'id':'c1','status':'unresolved'}]}}}
  self.facts=[{'id':'f1','text':'Observation','source':'https://example.org','published_at':'2026-11-17','known_at':'2026-11-18','valid_until':'2026-11-25'}]
  self.payload=inputs(self.report,self.facts)
  self.brief={'schema_version':'mara.reader-brief/1.0','as_of':'2026-11-18','period':period('2026-11-18'),'coverage':'partial','headline':'Synthetic summary','summary':'Only supplied observations.',
   'themes':[{'id':'market','title':'Synthetic theme','what_happened':'Observation','portfolio_meaning':'Interpretation','counterpoint':'Limited coverage','fact_ids':['f1']}],
   'key_reasons':[{'headline':'Wait','explanation':'Original claim unresolved','claim_ids':['c1']}],'missing_evidence':['Full period coverage']}
 def test_calendar_period_and_reference_binding(self):
  self.assertEqual(period('2026-05-31')['start'],'2026-02-28')
  self.assertEqual(period('2024-05-31')['start'],'2024-02-29')
  before=copy.deepcopy(self.report);check(self.brief,self.payload);self.assertEqual(self.report,before)
  record={'brief':self.brief,'provenance':{'input_sha256':digest(self.payload),'brief_sha256':digest(self.brief)}}
  self.assertEqual(presented(record,self.report,self.facts),self.brief)
  other=copy.deepcopy(self.report);other['proposal']['action']='adjust';self.assertIsNone(presented(record,other,self.facts))
 def test_unknown_refs_future_sources_and_decision_fields_rejected(self):
  for mutate in [lambda b:b['themes'][0].update(fact_ids=['invented']),lambda b:b['key_reasons'][0].update(claim_ids=['absent']),lambda b:b.update(weights={'CASH':0}),lambda b:b['period'].update(start='2026-08-17')]:
   b=copy.deepcopy(self.brief);mutate(b)
   with self.assertRaises(ValueError):check(b,self.payload)
  self.payload['market']['facts'][0]['known_at']='2026-11-19'
  with self.assertRaises(ValueError):check(self.brief,self.payload)
 def test_no_market_claim_without_sources(self):
  b=copy.deepcopy(self.brief);b.update(themes=[],missing_evidence=[])
  with self.assertRaises(ValueError):check(b,self.payload)
  b['missing_evidence']=['No source'];check(b,self.payload)
 def test_repair_records_exact_attempt_and_preserves_frozen_decision_binding(self):
  records=[];bad=copy.deepcopy(self.brief);bad['themes'][0]['fact_ids']=['unknown']
  answers=[bad,copy.deepcopy(self.brief)]
  class Session:
   def append(self,kind,body,*args):
    records.append((kind,copy.deepcopy(body)));return 'event-'+str(len(records))
  class Model:
   mode='live';identity={'provider':'synthetic'}
   def complete(self,*args):return answers.pop(0)
  self.report['run_id']='synthetic';before=copy.deepcopy(self.report)
  from unittest.mock import patch
  with patch('mara.submission_recovery.guard'):
   record=create(Session(),Model(),self.report,self.facts)
  attempts=[body for kind,body in records if kind=='report_editor_input']
  self.assertEqual(len(attempts),2)
  self.assertNotEqual(attempts[0]['attempt_input_sha256'],attempts[1]['attempt_input_sha256'])
  for attempt in attempts:self.assertEqual(attempt['attempt_input_sha256'],digest(attempt['payload']))
  self.assertEqual(record['provenance']['attempt_input_sha256'],attempts[1]['attempt_input_sha256'])
  self.assertEqual(record['provenance']['input_sha256'],digest(inputs(self.report,self.facts)))
  self.assertEqual(presented(record,self.report,self.facts),self.brief);self.assertEqual(self.report,before)
if __name__=='__main__':unittest.main()
