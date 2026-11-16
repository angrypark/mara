import copy,json,unittest
from mara.fund_economic_exposure import holdings
from mara.sector_lookthrough import apply
from test_decision import market,profile as user_profile


class FundEconomicsTests(unittest.TestCase):
    def fixture(self):
        profile={'net_assets':{'value':1000,'currency':'USD','observed_at':'2026-11-13'},'net_assets_source':'https://example.com/fund'}
        raw='Fund Holdings as of,"Nov 13, 2026"\nTicker,Name,Sector,Asset Class,Market Value,Notional Value,Currency,Quantity\nA,Company A,Technology,Equity,990,990,USD,10\nUSD,Cash,Cash,Cash,10,10,USD,10\nF,Future,Cash,Futures,0,20,USD,1\n'
        return profile,raw

    def test_zero_book_future_has_nonzero_economic_exposure(self):
        p,raw=self.fixture();r=holdings(raw,p,'2026-11-16');e=r['economic_exposure']
        self.assertAlmostEqual(e['non_equity_gross_fraction'],.03)
        self.assertGreater(e['gross_exposure_estimate'],1.02)
        m=market();m['as_of']='2026-11-16';m['fund_constituents']={'FUND':r.pop('constituents')}
        m['facts'][1]['text']=json.dumps(r);m['facts'][1]['known_at']='2026-11-16'
        apply(m,{'Technology':{'stocks':[{'symbol':'A'}]}},{'as_of':m['as_of'],'expected_root_names':['Technology']})
        asset=m['assets']['FUND'];self.assertFalse(asset['sector_exposure_unbounded'])
        self.assertAlmostEqual(asset['sector_unknown_fraction'],.031)
        self.assertGreater(asset['stress_loss'],.51)
        from mara.risk import evaluate
        user=user_profile();w={'FUND':.4,'CASH':.6}
        self.assertFalse(evaluate(w,user,m,100)['passed'])
        user.update(loss_budget_scope='analysis_only',analysis_loss_budget=.5)
        evaluated=evaluate(w,user,m,100)
        self.assertTrue(evaluated['passed']);self.assertTrue(any('추정' in x for x in evaluated['warnings']))

    def test_nav_denominated_sector_can_exceed_one_without_clipping(self):
        p,raw=self.fixture();raw=raw.replace('990,990','1010,1010').replace('10,10,USD,10','-10,-10,USD,-10')
        r=holdings(raw,p,'2026-11-16');m=market();m['as_of']='2026-11-16'
        m['fund_constituents']={'FUND':r.pop('constituents')};m['facts'][1]['text']=json.dumps(r)
        apply(m,{'Technology':{'stocks':[{'symbol':'A'}]}},{'as_of':m['as_of'],'expected_root_names':['Technology']})
        self.assertAlmostEqual(m['assets']['FUND']['sector_exposures']['Technology'],1.01)
        from mara.domain import market as validate_market
        validate_market(m)

    def test_currency_dates_unknown_derivatives_and_missing_values_fail(self):
        p,raw=self.fixture()
        for bad in [raw.replace('Futures','Swap'),raw.replace('0,20,USD,1','0,,USD,1'),raw.replace('0,20,USD,1','0,0,USD,1'),raw.replace('990,990,USD','990,990,EUR'),raw.replace('Nov 13','Nov 12'),raw.replace('990,990','900,900')]:
            with self.assertRaises((ValueError,TypeError)):holdings(bad,p,'2026-11-16')

    def test_original_weight_missing_does_not_become_zero(self):
        p,raw=self.fixture()
        result=holdings(raw,p,'2026-11-16')
        self.assertEqual(result['constituents'][0]['weight'],.99)
        self.assertIn('원 CSV 비중 결측을 0으로',result['limits'])


if __name__=='__main__':unittest.main()
