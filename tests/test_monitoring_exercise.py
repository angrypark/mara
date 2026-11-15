import copy,unittest
from mara.monitoring_exercise import exercise
class MonitoringExerciseTests(unittest.TestCase):
 def test_income_counterexample_and_restoration_are_executed_without_mutation(self):
  p={'monthly_income':100};before=copy.deepcopy(p)
  r=exercise(p,{'stress':[{'expenses':60}]},30)
  self.assertEqual([x['action'] for x in r['results']],['maintain','reduce','pause','maintain'])
  self.assertEqual([x['permitted_new_contribution'] for x in r['results']],[30,10,0,30])
  self.assertTrue(r['all_checks_passed']);self.assertEqual(p,before)
  r=exercise(p,{'stress':[{'expenses':60}]},0)
  self.assertEqual([x['permitted_new_contribution'] for x in r['results']],[0]*4)
  self.assertTrue(r['all_checks_passed'])

  r=exercise({'monthly_income':8.3},{'stress':[{'expenses':5.81}]},1)
  self.assertEqual(r['results'][1]['action'],'pause');self.assertEqual(r['results'][1]['permitted_new_contribution'],0)
  self.assertTrue(r['all_checks_passed']);self.assertTrue(r['working_copy_restored'])
