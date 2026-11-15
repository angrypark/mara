import calendar,copy,unittest
from datetime import date
from mara.fx_history import parse
from mara.krw_comparison import build


def fixture():
    levels=[];history=[];csv=['observation_date,DEXKOUS']
    for i in range(49):
        year=2022+i//12;month=i%12+1;day=date(year,month,calendar.monthrange(year,month)[1]).isoformat()
        level=1000*(1.01**i);csv.append(day+','+str(level));levels.append({'date':day,'observed_at':day,'krw_per_usd':level})
        if i:history.append({'date':day,'return':.02})
    fx=parse(('\n'.join(csv)+'\n').encode(),'2026-02-15')
    return {'as_of':'2026-02-15','fx_history':fx,'return_histories':{'FUND':{'symbol':'FUND','source':'https://example.org/synthetic','currency':'USD','frequency':'monthly','return_type':'issuer_reported_nav_total_return','observations':history}}},csv


class FXComparisonTests(unittest.TestCase):
    def test_cross_currency_compounding_matches_closed_form_without_fees_or_flows(self):
        m,_=fixture();r=build(m,{'stock':{'FUND':1},'cash':{'CASH':1}},100,0,3,0)
        self.assertTrue(r['available']);self.assertEqual(r['currency'],'KRW')
        self.assertEqual(r['independent_replay']['status'],'passed')
        self.assertAlmostEqual(r['results']['stock']['ending_wealth'],100*(1.02*1.01)**48,places=8)
        self.assertEqual(r['results']['cash']['ending_wealth'],100)
        self.assertEqual(r['results']['cash']['profit'],0)
        self.assertIn('initial_krw_units',r['assumptions']);self.assertNotIn('initial_usd_units',r['assumptions'])

    def test_gaps_identity_future_and_stale_month_end_fail(self):
        m,csv=fixture()
        for raw in ('\n'.join(csv).replace('DEXKOUS','EXKOUS'), '\n'.join(csv[:3]+csv[4:]), '\n'.join(csv+[csv[-1]])):
            with self.assertRaises(ValueError):parse(raw.encode(),'2026-02-15')
        for key,value in [('units','USD per KRW'),('known_at','2026-02-16'),('frequency','annual')]:
            altered=copy.deepcopy(m);altered['fx_history'][key]=value
            self.assertFalse(build(altered,{'stock':{'FUND':1}},100,0,3,10)['available'])
        for mutate in (lambda x:x['fx_history']['observations'].pop(),lambda x:x['return_histories']['FUND'].update(frequency='daily'),lambda x:x['return_histories']['FUND']['observations'][0].update(date='2022-02-15')):
            altered=copy.deepcopy(m);mutate(altered);self.assertFalse(build(altered,{'stock':{'FUND':1}},100,0,3,10)['available'])
        altered=copy.deepcopy(m);altered['fx_history']['observations'][4]['observed_at']='2022-05-01'
        self.assertFalse(build(altered,{'stock':{'FUND':1}},100,0,3,10)['available'])

    def test_deposits_cost_and_cash_sensitivity_are_separate(self):
        m,_=fixture();r=build(m,{'mixed':{'FUND':.4,'CASH':.6},'cash':{'CASH':1}},100,10,3,15.005)
        self.assertTrue(r['available']);self.assertEqual(r['independent_replay']['status'],'passed')
        for row in r['results'].values():
            self.assertEqual(row['contributed'],570);self.assertAlmostEqual(row['profit'],row['ending_wealth']-570)
        self.assertEqual(r['results']['cash']['profit'],0)
        self.assertEqual(r['results']['cash']['transaction_cost_paid'],0)
        self.assertGreater(r['results']['mixed']['transaction_cost_paid'],0)
        self.assertGreater(r['sensitivity'][0]['results']['cash']['profit'],0)

    def test_large_krw_cash_balance_never_incurs_phantom_bisection_fees(self):
        m,_=fixture();r=build(m,{'mixed':{'FUND':.4,'CASH':.6},'cash':{'CASH':1}},3000000,3000000,3,15.005)
        self.assertEqual(r['independent_replay']['status'],'passed')
        self.assertEqual(r['results']['cash']['transaction_cost_paid'],0)
        self.assertEqual(r['results']['cash']['profit'],0)
