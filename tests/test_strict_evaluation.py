import copy
import unittest
from mara.evaluation import rubric,score
from mara.agents import DemoModel
from mara.contracts import ContractError,schema


def fixture():
    p={'rubric':rubric(),'as_of':'2026-11-16','profile':{'goal':'fixture'},'market':{'facts':[]},'role_outputs':{},
       'report':{'proposal':{'eligibility':'blocked','decision_status':{'execution_status':'not_authorized'}},'analysis':{'comparison':{'available':False}}}}
    o=DemoModel().complete('evaluator','',p,schema('agent-evaluator'))
    return p,o


class StrictEvaluationTests(unittest.TestCase):
    def test_conflicting_asset_identity_deterministically_fails(self):
        p,o=fixture();p['market']['facts']=[{'id':'research-fund_profile-ITOT','research_tool':'fund_profile','text':'{"symbol":"IVV"}',
            'known_at':'2026-11-16','published_at':'2026-11-13','valid_until':'2026-11-20'}]
        self.assertEqual(score(o,p)['gates']['G1'],'fail')

    def test_narrow_section_and_all_path_errors(self):
        p,o=fixture();p['report']['proposal']['monthly_allocation']={'CASH':100}
        check=o['criteria'][5]['checks'][2]
        check.update(status='met',evidence_paths=['/report/proposal/monthly_allocation'])
        score(o,p)
        check['evidence_paths']=['/profile/goal','/report/absent']
        with self.assertRaises(ContractError) as caught:score(o,p)
        self.assertIn('/profile/goal',str(caught.exception));self.assertIn('/report/absent',str(caught.exception))
        check['evidence_paths']=['/report/proposal']
        self.assertRaises(ContractError,score,o,p)

    def test_independent_receipt_scoped_and_empty_rejected(self):
        p,o=fixture();p['role_outputs']['quantitative_verifier']={'status':'passed','recomputed':{'fixture':1},'discrepancies':[]}
        check=o['criteria'][1]['checks'][3]
        check.update(status='met',evidence_paths=['/role_outputs/quantitative_verifier/recomputed'])
        score(o,p)
        check['evidence_paths']=['/role_outputs/quantitative_verifier/discrepancies']
        self.assertRaises(ContractError,score,o,p)

    def test_v1_irrelevant_pointer_exploit_cannot_award_new_score(self):
        p,o=fixture()
        for row in o['criteria']:
            row['score']=4;row['evidence_paths']=['/profile/goal']
        result=score(o,p)
        self.assertEqual(result['total'],0);self.assertFalse(result['strict_pass'])
        row=o['criteria'][1];row['checks'][0].update(status='met',evidence_paths=['/profile/goal'])
        self.assertRaises(ContractError,score,o,p)

    def test_consecutive_levels_and_no_compensation_for_gap(self):
        p,o=fixture();p['report']['proposal']['rationale']='Fixture relevant text; semantic correctness separately tested'
        row=o['criteria'][0]
        row['checks'][0].update(status='met',evidence_paths=['/report/proposal/rationale'])
        row['checks'][3].update(status='met',evidence_paths=['/report/proposal/investment_case/key_points/0'])
        p['report']['proposal']['investment_case']={'key_points':['fixture']}
        result=score(o,p);self.assertEqual(result['criterion_levels']['suitability'],1)
        self.assertFalse(result['coverage_complete']);self.assertFalse(result['strict_pass'])

    def test_fail_is_never_downgraded_and_unresolved_claim_is_not_supported(self):
        p,o=fixture()
        for g in o['gates']:g.update(status='fail',reason='Known material contradiction')
        result=score(o,p)
        self.assertEqual(set(result['gates'].values()),{'fail'})
        for g in o['gates']:g.update(status='pass',evidence_paths=['/profile/goal'])
        p['report']['proposal']['investment_case']={'claims':[{'id':'c1','status':'unresolved','fact_ids':[],'calculation_paths':[]}]}
        result=score(o,p)
        self.assertEqual(result['gates']['G2'],'unknown');self.assertFalse(result['strict_pass'])
        p['report']['proposal']['investment_case']['claims'][0]['calculation_paths']=['/analysis/absent']
        result=score(o,p)
        self.assertEqual(result['gates']['G3'],'fail')

    def test_missing_fixed_coverage_and_duplicate_checks_rejected(self):
        p,o=fixture();o['coverage'].pop()
        self.assertRaises(ContractError,score,o,p)
        p,o=fixture();o['criteria'][0]['checks'][1]=copy.deepcopy(o['criteria'][0]['checks'][0])
        self.assertRaises(ContractError,score,o,p)
