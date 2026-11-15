import calendar
import math
import unittest
from mara.portfolio_comparison import compare


def history(returns):
    return {'symbol':'ETF','currency':'USD','frequency':'monthly','return_type':'issuer_reported_nav_total_return',
        'source':'https://example.com/issuer','observations':[{'date':f'{2020+i//12}-{i%12+1:02}-{calendar.monthrange(2020+i//12,i%12+1)[1]}','return':r} for i,r in enumerate(returns)]}


class ComparisonTests(unittest.TestCase):
    def test_cash_flows_not_profit_and_fee_not_double_counted(self):
        d=compare({'ETF':history([0.]*36)},{'equity':{'ETF':1},'cash':{'CASH':1}},initial=100,monthly=10,cost_bps=100)
        a=d['results']['equity'];c=d['results']['cash']
        self.assertEqual(c['profit'],0);self.assertEqual(c['contributed'],450)
        self.assertAlmostEqual(a['ending_wealth'],450/1.01)
        self.assertAlmostEqual(a['transaction_cost_paid'],450-450/1.01)
        self.assertAlmostEqual(a['profit'],-a['transaction_cost_paid'])
        self.assertEqual(c['annualized_volatility'],0)

    def test_returns_rebalance_cost_and_risk_decomposition(self):
        rs=[.1,-.1,.02]*12
        d=compare({'ETF':history(rs)},{'equity':{'ETF':1},'balanced':{'ETF':.4,'CASH':.6}},cost_bps=0,rebalance_months=1)
        self.assertAlmostEqual(d['results']['equity']['cumulative_return'],math.prod(1+r for r in rs)-1)
        b=d['results']['balanced'];self.assertAlmostEqual(b['cumulative_return'],math.prod(1+.4*r for r in rs)-1)
        self.assertAlmostEqual(b['target_weight_annual_volatility_contribution']['ETF'],b['annualized_volatility'])
        self.assertEqual(b['target_weight_annual_volatility_contribution']['CASH'],0)
        costly=compare({'ETF':history(rs)},{'balanced':{'ETF':.4,'CASH':.6}},cost_bps=50,rebalance_months=1)['results']['balanced']
        self.assertLess(costly['ending_wealth'],b['ending_wealth'])

    def test_incompatible_history_and_missing_month_rejected(self):
        h=history([.01]*48);h['observations'].pop(20)
        self.assertRaises(ValueError,compare,{'ETF':h},{'x':{'ETF':1}})
        h=history([.01]*48);h['currency']='KRW'
        self.assertRaises(ValueError,compare,{'ETF':h},{'x':{'ETF':1}})
