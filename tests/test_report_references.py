import copy,unittest
from mara.report_references import errors


class ReportReferencesTests(unittest.TestCase):
    def test_author_paths_are_body_relative_and_zero_is_valid(self):
        p={'investment_case':{'claims':[{'id':'c','calculation_paths':['/funding/amount','/analysis/results/base','/proposal/investment_case/monitoring']}],'monitoring':[{'variable':'synthetic'}],'alternatives':[{'name':'base','weights':{'A':.4,'CASH':.6},'comparison_path':'/analysis/results/base'}]}}
        a={'results':{'base':{'weights':{'A':.4,'CASH':.6}}}}
        self.assertEqual(errors(p,a,{'amount':0},{}),[])
        for path in ('/input/analysis/results/base','/report/analysis/results/base','/analysis/missing','/valuation/weights'):
            changed=copy.deepcopy(p);changed['investment_case']['claims'][0]['calculation_paths']=[path]
            self.assertTrue(errors(changed,a,{'amount':0},{'weights':{'CASH':1}}))
        changed=copy.deepcopy(p);changed['investment_case']['alternatives'][0]['weights']={'A':.5,'CASH':.5}
        self.assertIn('weights differ',errors(changed,a,{'amount':0},{})[0]['reason'])

        changed=copy.deepcopy(p);changed['investment_case']['alternatives'][0]['comparison_path']='/analysis/value'
        self.assertTrue(errors(changed,dict(a,value=0),{'amount':0},{}))
