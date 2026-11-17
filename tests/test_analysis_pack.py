import copy,json,unittest
from mara.analysis_pack import build
from test_decision import profile,market
from test_portfolio_comparison import history


def fixture():
    p=profile();m=market();m['assets']['ITOT']=m['assets'].pop('FUND');m['prices']['ITOT']=m['prices'].pop('FUND')
    for f in m['facts']:
        f['id']=f['id'].replace('FUND','ITOT');f['text']=f['text'].replace('FUND','ITOT')
    m['return_histories']={'ITOT':dict(history([.1,-.1,.02]*24),symbol='ITOT')}
    return p,m,{'cash':0},{'nav':0,'values':{'CASH':0},'weights':{}}


class AnalysisPackTests(unittest.TestCase):
    def test_role_receipt_matches_final_independent_replay_input_and_scope(self):
        from mara.quantitative_verifier import verify
        p,m,a,v=fixture();result=build(p,a,m,v,1000,{'ITOT':.4,'CASH':.6})
        receipt=result['comparison']['independent_replay']
        final=verify({'as_of':m['as_of'],'analysis':result},m)
        self.assertEqual(receipt['status'],'passed');self.assertEqual(receipt['input_hash'],final['input_hash'])
        self.assertIn('proposal',receipt['verified_portfolios']);self.assertIn('Does not validate',receipt['scope'])
        self.assertNotIn('recomputed',receipt)

    def test_all_cash_proposal_preserves_benchmark_only_sensitivity(self):
        p,m,a,v=fixture();c=build(p,a,m,v,1000,{'CASH':1})['comparison']
        self.assertTrue(c['available']);self.assertTrue(c['sensitivity'])
        self.assertTrue(all(any(k!='CASH' for k in row['comparison_anchor_weights']) for row in c['sensitivity']))

    def test_zero_future_contributions_do_not_create_fake_sensitivity(self):
        from mara.quantitative_verifier import verify
        p,m,a,v=fixture();p['contribution_amount']=0
        result=build(p,a,m,v,1000,{'ITOT':.4,'CASH':.6})
        self.assertEqual(len(result['comparison']['sensitivity']),5)
        self.assertEqual(verify({'analysis':result},m)['status'],'passed')

    def test_sensitivity_changes_only_declared_assumption(self):
        for days in (30,90,365):
            p,m,a,v=fixture();p['rebalance_every_days']=days
            c=build(p,a,m,v,1000,{'ITOT':.4,'CASH':.6})['comparison']
            self.assertTrue(c['available']);self.assertEqual(len(c['sensitivity']),6)
            names={'cost':'one_way_cost_bps','contribution':'monthly_usd_units','rebalance':'rebalance_months','cash_yield':'cash_annual_assumption'}
            for row in c['sensitivity']:
                changed={k for k,value in c['assumptions'].items() if row['assumptions'][k]!=value}
                self.assertEqual(changed,{names[row['changed_assumption']]})
                self.assertEqual(row['comparison_anchor_weights'],{'ITOT':.4,'CASH':.6})

    def test_fx_cross_term_and_unknown_currency_are_visible(self):
        p,m,a,v=fixture();p['base_currency']='KRW'
        r=build(p,a,m,v,1000,{'ITOT':.4,'CASH':.6})
        stress=r['fx_stress']['scenarios'][2]
        self.assertAlmostEqual(stress['portfolio_change_fraction'],.4*((1-.4)*(1-.15)-1))
        del m['assets']['ITOT']['currency']
        self.assertEqual(build(p,a,m,v,1000,{'ITOT':.4,'CASH':.6})['fx_stress']['unknown_currency_assets'],['ITOT'])

    def test_price_nav_must_share_us_trading_date(self):
        p,m,a,v=fixture();m['return_histories']['ITOT']['latest_nav']={'date':'2026-11-13','nav_per_share_usd':100}
        fact={'id':'toss-ITOT','text':json.dumps({'quote':{'timestamp':'2026-11-14T05:00:00+09:00','currency':'USD','lastPrice':101}})}
        m['facts'].append(fact)
        r=build(p,a,m,v,1000,{'ITOT':.4,'CASH':.6})['products']['ITOT']['nav_comparison']
        self.assertTrue(r['available']);self.assertAlmostEqual(r['premium_fraction'],.01)
        fact['text']=fact['text'].replace('2026-11-14','2026-11-15')
        self.assertFalse(build(p,a,m,v,1000,{'ITOT':.4,'CASH':.6})['products']['ITOT']['nav_comparison']['available'])

    def test_equal_numeric_weights_do_not_split_integer_and_float_cash(self):
        p,m,a,v=fixture();v={'nav':1000,'values':{'CASH':1000},'weights':{'CASH':1.0}}
        r=build(p,a,m,v,1000)['comparison']['independent_replay']
        self.assertEqual(r['verified_name_count'],5)
        self.assertEqual(r['distinct_positive_weight_count'],4)
