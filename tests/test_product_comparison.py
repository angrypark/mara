import unittest,json
from mara.product_comparison import build
class ProductComparisonTests(unittest.TestCase):
 def test_equal_fees_cannot_pay_for_switch_and_concentration_is_not_invented(self):
  m={'facts':[],'as_of':'2026-11-16'}
  for symbol,top in [('ITOT',.3),('IVV',.4)]:
   for tool,value in [('fund_profile',{'symbol':symbol,'observed_at':'2026-11-12','expense_observed_at':'2026-11-12','expense_ratio':.0003,'issuer_metrics':{'thirtyDayMedianBidAskSpread':{'value':.0001,'unit':'fraction','observed_at':'2026-11-12'}}}),('fund_holdings',{'observed_at':'2026-11-12','top_holdings':[{'weight':top}],'reported_weight_sum':1,'complete_reported_weights':True,'missing_weight_rows':[]})]:m['facts'].append({'id':'research-'+tool+'-'+symbol,'research_tool':tool,'valid_until':'2026-11-20','known_at':'2026-11-16','text':json.dumps(value)})
  costs={'published_conditions_and_examples':{'available':True,'published_rates':{'us_stock_standard_commission_fraction':.001,'fx_regular_effective_spread_fraction':.0005,'fact_id':'fee'}}}
  r=build({'base_currency':'KRW'},m,3000000,costs)
  self.assertTrue(r['available']);self.assertAlmostEqual(r['switch_existing_ITOT_to_IVV']['estimated_commission_and_half_spreads'],2520)
  self.assertEqual(r['switch_existing_ITOT_to_IVV']['annual_ter_saving_at_constant_notional'],0)
  self.assertIsNone(r['switch_existing_ITOT_to_IVV']['break_even_years']);self.assertFalse(r['new_money_cost_and_concentration_dominance'])
  self.assertAlmostEqual(r['switch_existing_ITOT_to_IVV']['boundaries'][1]['minimum_annual_fee_saving_bps'],10.5)
  v=json.loads(m['facts'][-1]['text']);v['observed_at']='2026-11-11';m['facts'][-1]['text']=json.dumps(v)
  r=build({'base_currency':'KRW'},m,3000000,costs);self.assertIsNone(r['ivv_minus_itot_top_holdings_fraction'])

  v['observed_at']='2026-11-12';v['complete_reported_weights']=False;v['missing_weight_rows']=[{'symbol':'missing'}];m['facts'][-1]['text']=json.dumps(v)
  r=build({'base_currency':'KRW'},m,3000000,costs);self.assertIsNone(r['new_money_cost_and_concentration_dominance'])
  v=json.loads(m['facts'][0]['text']);v['issuer_metrics']['thirtyDayMedianBidAskSpread']['unit']='percent';m['facts'][0]['text']=json.dumps(v)
  self.assertFalse(build({'base_currency':'KRW'},m,3000000,costs)['available'])
