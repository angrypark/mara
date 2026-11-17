import copy,tempfile,unittest
from pathlib import Path
from mara.agents import DemoModel
from mara.engine import Engine
from mara.store import Store
from mara.contracts import schema,validate
from mara.report_references import errors
from mara.registry import personas
from test_decision import profile,market


class AlternativeExhibitTests(unittest.TestCase):
    def test_unknown_asset_remains_blocked_with_unknown_stress(self):
        from mara.analysis_pack import build
        a=build(profile(),{'cash':0},market(),{'nav':0,'weights':{},'values':{}},1000,{'NOTCOLLECTED':.1,'CASH':.9})
        row=a['selected_comparison']
        self.assertFalse(row['numeric_checks']['passed'])
        self.assertIsNone(row['numeric_scenario_assumptions']['NOTCOLLECTED'])
        self.assertIn('NOTCOLLECTED',row['fx_stress']['unknown_currency_assets'])
        validate(a,schema('analysis'))

    def test_peer_independence_and_nonhistorical_comparison_references(self):
        stages=[]
        class Model(DemoModel):
            def complete(self,role,guide,p,contract):
                if role in personas():
                    self_check=p['analysis']
                    assert 'perspective_comparisons' not in self_check
                if role in ('validation','leader'):
                    rows=p['analysis']['perspective_comparisons']
                    assert set(rows)==set(personas())
                    assert all(not x['historical_performance']['available'] for x in rows.values())
                    stages.append(role)
                out=super().complete(role,guide,p,contract)
                if role in personas():out['weights']={'FUND':.4,'CASH':.6}
                if role=='leader':out.update(weights={'FUND':.3,'CASH':.7},action='adjust')
                return out
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');s=db.session(db.create_user('synthetic'));e=Engine(s,Model())
            p,m=profile(),market();e.set_profile(p,m['as_of']);e.set_holdings({'as_of':m['as_of'],'base_currency':'USD','cash':100,'positions':{},'rationale':'Synthetic','last_rebalanced':m['as_of']})
            report=e.run(m['as_of'],db.publish_market(m));a=report['analysis'];validate(a,schema('analysis'))
            self.assertEqual(a['selected_comparison']['weights'],{'FUND':.3,'CASH':.7})
            self.assertEqual(a['selected_comparison']['capital'],a['fx_stress']['capital'])
            for role,row in a['perspective_comparisons'].items():
                self.assertEqual(row['weights'],report['perspectives'][role]['weights'])
                self.assertAlmostEqual(row['fx_stress']['scenarios'][0]['portfolio_change_fraction'],-.08)
                self.assertEqual(row['allocation_sleeves']['invested_fraction'],.4)
            for path in ['/analysis/selected_comparison','/analysis/perspective_comparisons/wood']:
                row=a['selected_comparison'] if path.endswith('selected_comparison') else a['perspective_comparisons']['wood']
                proposal={'investment_case':{'alternatives':[{'name':'synthetic','weights':row['weights'],'comparison_path':path}]}}
                self.assertEqual(errors(proposal,a,{},{}),[])
                bad=copy.deepcopy(proposal);bad['investment_case']['alternatives'][0]['weights']={'CASH':1}
                self.assertTrue(errors(bad,a,{},{}))
            invalid=copy.deepcopy(a);invalid['selected_comparison']['historical_performance']['available']=True
            with self.assertRaises(ValueError):validate(invalid,schema('analysis'))
            self.assertIn('validation',stages);self.assertIn('leader',stages);db.close()
