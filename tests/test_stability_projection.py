import copy,unittest
from mara.workbench import stability_receipt
class StabilityProjectionTests(unittest.TestCase):
 def test_only_the_matching_report_and_evaluator_spec_can_receive_a_followup(self):
  rows=[{'id':'same','recorded':'now','body':{'base_completed_id':'A','evaluator_spec_hash':'x','passed':False}}, {'id':'other-report','recorded':'later','body':{'base_completed_id':'B','evaluator_spec_hash':'x','passed':True}}, {'id':'other-spec','recorded':'later','body':{'base_completed_id':'A','evaluator_spec_hash':'y','passed':True}}]
  class Session:
   def events(self,kind):return rows
  before=copy.deepcopy(rows);s=Session()
  self.assertEqual(stability_receipt(s,'A','x')['source_event_id'],'same')
  self.assertFalse(stability_receipt(s,'A','x')['passed'])
  self.assertIsNone(stability_receipt(s,'missing','x'));self.assertIsNone(stability_receipt(s,'A',None));self.assertEqual(rows,before)
