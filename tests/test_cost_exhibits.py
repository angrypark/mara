import json,unittest
from mara.cost_exhibits import build

class CostExhibitsTests(unittest.TestCase):
    def fixture(self):
        p={'base_currency':'KRW','contribution_schedule':'monthly','contribution_amount':1000}
        obs={'fx_regular_effective_spread_fraction':.0005,'fx_outside_effective_spread_fraction':.005,'us_stock_standard_commission_fraction':.001}
        m={'facts':[{'id':'fee','research_tool':'release_notes','text':json.dumps({'id':'toss-us-fees-fixture','observations':obs})}],
           'assets':{'ETF':{'asset_class':'equity','currency':'USD'}},'prices':{'ETF':{'price':100}}}
        return p,m
    def test_integer_cash_cost_and_deposit_correction(self):
        p,m=self.fixture();result=build(p,m,{'ETF':.4,'CASH':.6},1000)
        self.assertTrue(result['available']);a,b=result['scenarios']
        self.assertEqual(a['first_contribution_integer_illustration'][0]['units'],3)
        self.assertAlmostEqual(a['cash_remaining'],1000-300*1.001*1.0005)
        self.assertAlmostEqual(a['monthly_cost_at_target_notional'],400*(1.001*1.0005-1))
        self.assertGreater(b['estimated_cost_total'],a['estimated_cost_total'])
        self.assertAlmostEqual(result['deposit_vs_sale_example']['deposit_to_cash_needed_to_restore_target'],125)
        self.assertEqual(result['authority'],'illustrative_only_no_order_authorization')
    def test_missing_rates_and_out_of_scope_never_assume_free(self):
        p,m=self.fixture();m['prices']={}
        r=build(p,m,{'ETF':1},1000);self.assertFalse(r['available']);self.assertEqual(r['missing_prices'],['ETF'])
        p,m=self.fixture();m['facts']=[]
        self.assertFalse(build(p,m,{'ETF':.4,'CASH':.6},1000)['available'])
        p,m=self.fixture();m['assets']['ETF']['currency']='KRW'
        self.assertFalse(build(p,m,{'ETF':.4,'CASH':.6},1000)['available'])
        p,m=self.fixture();r=build(p,m,{'CASH':1},1000)
        self.assertIsNone(r['deposit_vs_sale_example']['deposit_to_cash_needed_to_restore_target'])

    def test_usd_buffer_only_pays_fx_and_stays_separate_from_stock_units(self):
        p,m=self.fixture();m['assets']['USD_CASH']={'asset_class':'cash','currency':'USD'};m['prices']['USD_CASH']={'price':10}
        result=build(p,m,{'ETF':.6,'USD_CASH':.4},1000);a=result['scenarios'][0]
        self.assertTrue(result['available'])
        self.assertAlmostEqual(a['monthly_cost_at_target_notional'],600*(1.001*1.0005-1)+400*.0005)
        cash=a['first_contribution_integer_illustration'][1]
        self.assertEqual(cash['asset_type'],'foreign_cash');self.assertAlmostEqual(cash['estimated_cash_needed'],400)
        self.assertAlmostEqual(cash['estimated_fee_fx_cost'],400-400/1.0005)
