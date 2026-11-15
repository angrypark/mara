import unittest
from mara.holding_values import concentration
class HoldingValueTests(unittest.TestCase):
 def test_missing_weights_are_not_zero_filled_and_currency_footer_checks_hold(self):
  raw='Fund Holdings as of,"Nov 12, 2026"\nTicker,Asset Class,Market Value,Currency,Market Currency,Market Weight,Name,Exchange\n'+'\n'.join(f'S{i},Equity,10,USD,USD,-,Name,NYSE' for i in range(11))+'\nCASH,Cash,90,USD,USD,-,Cash,-\n\nDisclosure\n'
  r=concentration(raw,'2026-11-16');self.assertEqual(r['denominator_usd'],200);self.assertEqual(r['top_equity_fraction'],.5);self.assertEqual(r['row_count'],12)
  for changed in (raw.replace('10,USD','-,USD',1),raw.replace('10,USD','-1,USD',1),raw.replace('USD,USD','USD,EUR',1),raw.replace('S1,Equity','S0,Equity',1),raw.replace('\nCASH,Cash,90,USD,USD,-,Cash,-','\nCASH,Cash,90'),raw.replace('Nov 12','Nov 20'),raw.replace('\nCASH,Cash,90,USD,USD,-,Cash,-','\n\nCASH,Cash,90')):
   with self.assertRaises(ValueError):concentration(changed,'2026-11-16')

 def test_original_weight_parser_cannot_bypass_structural_or_duplicate_checks(self):
  from mara.research_sources import fund_holdings
  raw='Fund Holdings as of,"Nov 12, 2026"\nTicker,Name,Exchange,Sector,Asset Class,Market Weight,Market Value,Currency,Market Currency\n'+'\n'.join(f'S{i},Name{i},NYSE,Tech,Equity,9.09,10,USD,USD' for i in range(11))+'\n\nDisclosure\n'
  self.assertTrue(fund_holdings(raw,'2026-11-16')['complete_reported_weights'])
  for changed in (raw.replace('\n\nDisclosure','\n\nCASH,Cash,90\nDisclosure'),raw.replace('S1,Name1','S0,Name0')):
   with self.assertRaises(ValueError):fund_holdings(changed,'2026-11-16')
