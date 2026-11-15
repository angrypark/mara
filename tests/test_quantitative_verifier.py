import copy,unittest
from mara.portfolio_comparison import compare
from mara.quantitative_verifier import verify
from test_portfolio_comparison import history


class QuantitativeVerifierTests(unittest.TestCase):
    def test_semantic_corruption_and_unrelated_history(self):
        h=history([.1,-.1,.02]*12)
        c=compare({'ETF':h},{'balanced':{'ETF':.4,'CASH':.6}},initial=100,monthly=15)
        r={'analysis':{'comparison':dict(c,available=True)}};m={'as_of':'2026-11-16','return_histories':{'ETF':h}}
        self.assertEqual(verify(r,m)['status'],'passed')
        bad=copy.deepcopy(r);bad['as_of']='2020-06-30'
        self.assertEqual(verify(bad,m)['status'],'failed')
        other={'analysis':{'comparison':dict(compare({'ETF':h},{'balanced':{'ETF':.2,'CASH':.8}},initial=100,monthly=15),available=True)}}
        self.assertNotEqual(verify(other,m)['input_hash'],verify(r,m)['input_hash'])
        for key,value in [('contribution_timing','end, from first month'),('fund_expense_treatment','deduct again')]:
            bad=copy.deepcopy(r);bad['analysis']['comparison']['assumptions'][key]=value
            self.assertEqual(verify(bad,m)['status'],'failed')
        for key,value in [('currency','KRW'),('frequency','daily'),('symbol','OTHER')]:
            bad=copy.deepcopy(m);bad['return_histories']['ETF'][key]=value
            self.assertEqual(verify(r,bad)['status'],'failed')
        m['return_histories']['UNUSED']=history([.01]*12)
        self.assertEqual(verify(r,m)['status'],'passed')
        bad=copy.deepcopy(r);bad['analysis']['comparison']['results']['balanced']['target_weight_annual_volatility_contribution']['ETF']=999
        self.assertEqual(verify(bad,m)['status'],'failed')

    def test_sensitivity_numbers_and_one_variable_rule(self):
        from test_analysis_pack import fixture
        from mara.analysis_pack import build
        p,m,a,v=fixture();report={'analysis':build(p,a,m,v,1000,{'ITOT':.4,'CASH':.6})}
        receipt=verify(report,m);self.assertEqual(receipt['status'],'passed');self.assertEqual(len(receipt['recomputed_sensitivities']),6)
        report['analysis']['comparison']['sensitivity'][0]['result']['profit']+=1000000
        self.assertEqual(verify(report,m)['status'],'failed')
        report['analysis']['comparison']['sensitivity'][0]['assumptions']['rebalance_months']=12
        self.assertEqual(verify(report,m)['status'],'failed')

    def test_independent_replay_and_one_number_corruption(self):
        h=history([.1,-.1,.02]*12)
        for frequency in (1,3,12):
            result=compare({'ETF':h},{'all_equity':{'ETF':1},'cash':{'CASH':1},'balanced':{'ETF':.37,'CASH':.63}},initial=100,monthly=15,rebalance_months=frequency,cost_bps=37,cash_annual=.02)
            report={'analysis':{'comparison':dict(result,available=True)}};market={'as_of':'2026-11-16','return_histories':{'ETF':h}}
            receipt=verify(report,market);self.assertEqual(receipt['status'],'passed')
            report['analysis']['comparison']['results']['balanced']['profit']+=15
            self.assertEqual(verify(report,market)['status'],'failed')
    def test_missing_inputs_never_pass(self):
        self.assertEqual(verify({'analysis':{'comparison':{'available':True}}},{})['status'],'unavailable')
