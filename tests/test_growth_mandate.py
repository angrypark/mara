import copy,json,unittest
from mara import domain as d
from mara.decision import semantics
from mara.analysis_pack import build
from mara.sector_lookthrough import apply
from mara.additional_funds import qqq_profile,qqq_holdings
from mara.trading import build_plan
from test_decision import profile,market
from test_analysis_pack import fixture as analysis_fixture
from test_service_trading import fixture as trade_fixture,NOW


class GrowthMandateTests(unittest.TestCase):
    def test_separate_budget_keeps_reference_and_other_limits(self):
        p=profile();m=market()
        m['assets']['OTHER']=copy.deepcopy(m['assets']['FUND']);m['prices']['OTHER']=m['prices']['FUND']
        w={'FUND':.4,'OTHER':.4,'CASH':.2}
        self.assertFalse(d.suitability(w,p,m,100)['passed'])
        p.update(loss_budget_scope='analysis_only',analysis_loss_budget=.5)
        result=d.suitability(w,p,m,100)
        self.assertTrue(result['passed']);self.assertTrue(result['breaches_reference_loss_fraction'])
        self.assertEqual(p['max_loss_fraction'],.25);self.assertFalse(result['risk_budget']['personal_tolerance_confirmed'])
        self.assertIn('Position limit: FUND',d.suitability({'FUND':.6,'CASH':.4},p,m,100)['errors'])
        p['cash_need']=30
        self.assertIn('Cash reserve below stated cash need',d.suitability(w,p,m,100)['errors'])

    def test_analysis_scope_requires_budget_and_rejects_unknown(self):
        for scope,budget in [('analysis_only',None),('typo',.5),('analysis_only',True)]:
            p=profile();p.update(loss_budget_scope=scope,analysis_loss_budget=budget)
            with self.assertRaises(ValueError):d.profile(p)

    def test_fx_and_context_do_not_claim_confirmed_loss(self):
        p,m,h,v=analysis_fixture();p.update(loss_budget_scope='analysis_only',analysis_loss_budget=.5)
        x=build(p,h,m,v,100,{'ITOT':.8,'CASH':.2})
        self.assertEqual(semantics(p,m)['risk_budget']['reference_fraction'],.25)
        self.assertTrue(all(x['breaches_reported_loss_tolerance'] is None for x in x['fx_stress']['scenarios']))
        self.assertTrue(any(x['breaches_reference_loss_fraction'] for x in x['fx_stress']['scenarios']))

    def test_frozen_report_analysis_scope_cannot_become_order(self):
        policy,report,actual,snapshot=trade_fixture()
        for scope in ['analysis_only','unknown',None]:
            report['risk_budget']={'scope':scope,'effective_fraction':.5}
            with self.assertRaisesRegex(ValueError,'Confirmed risk scope'):build_plan(report,actual,snapshot,policy,NOW)
        report.pop('risk_budget')
        with self.assertRaisesRegex(ValueError,'Confirmed risk scope'):build_plan(report,actual,snapshot,policy,NOW)

    def test_same_taxonomy_lookthrough_keeps_unmapped_weight(self):
        m=market();m['fund_constituents']={'FUND':[{'symbol':'ONE','weight':.6},{'symbol':'TWO','weight':.3}]}
        value=json.loads(m['facts'][1]['text']);value['observed_at']=m['as_of'];m['facts'][1]['text']=json.dumps(value)
        apply(m,{'Technology':{'stocks':[{'symbol':'ONE'}]},'Devices':{'stocks':[{'symbol':'ONE'}]}},{'as_of':m['as_of'],'expected_root_names':['Technology','Devices']})
        a=m['assets']['FUND'];self.assertEqual(a['sector_exposures'],{'Technology':.6,'Devices':.6})
        self.assertAlmostEqual(a['sector_unknown_fraction'],.4);self.assertFalse(a['sector_complete'])
        from mara.risk import evaluate
        p=profile();p.update(max_position_fraction=1,max_loss_fraction=1)
        result=evaluate({'FUND':.9,'CASH':.1},p,m,100)
        self.assertTrue(any('섹터' in x for x in result['missing']))

    def test_qqq_rejects_top10_stale_and_unlabelled_weights(self):
        x={'cusip':'QQQ','effectiveBusinessDate':'2026-11-13','totalNumberOfHoldings':2,'holdings':[
            {'ticker':'A','issuerName':'A','percentageOfTotalNetAssets':99,'securityTypeName':'Common Stock','currency':'USD'},
            {'ticker':None,'issuerName':'Cash','percentageOfTotalNetAssets':1,'securityTypeName':'Currency','currency':'USD'}]}
        sectors={'cusip':'QQQ','effectiveDate':'2026-10-31','holdingWeights':[{'name':'Technology','value':100}]}
        r=qqq_holdings(json.dumps(x),json.dumps(sectors),'2026-11-16')
        self.assertEqual(len(r['constituents']),1);self.assertEqual(r['other_positions'][0]['weight'],.01)
        for alter in ['truncated','stale','missing']:
            bad=copy.deepcopy(x)
            if alter=='truncated':bad['totalNumberOfHoldings']=100
            if alter=='stale':bad['effectiveBusinessDate']='2026-09-01'
            if alter=='missing':bad['holdings'][0]['percentageOfTotalNetAssets']=None
            with self.assertRaises((ValueError,TypeError)):qqq_holdings(json.dumps(bad),json.dumps(sectors),'2026-11-16')

    def test_unbounded_derivative_cannot_use_simple_sector_ceiling(self):
        from mara.risk import evaluate
        m=market();p=profile()
        m['assets']['FUND'].update(sector_exposure_unbounded=True,sector_unknown_fraction=1.)
        result=evaluate({'FUND':.4,'CASH':.6},p,m,100)
        self.assertFalse(result['passed']);self.assertTrue(any('경제적 노출' in x for x in result['missing']))

    def test_public_analysis_contract_has_typed_risk_budget(self):
        from mara.contracts import validate,schema,ContractError
        p,m,h,v=analysis_fixture();p.update(loss_budget_scope='analysis_only',analysis_loss_budget=.5)
        value=build(p,h,m,v,100)
        validate(value,schema('analysis'))
        value['risk_budget']['personal_tolerance_confirmed']=True
        with self.assertRaises(ContractError):validate(value,schema('analysis'))

    def test_incomplete_old_form_cannot_silently_confirm_scope(self):
        import tempfile
        from mara.onboarding import PortfolioSetup
        from mara.engine import Engine
        from mara.agents import DemoModel
        with tempfile.TemporaryDirectory() as tmp:
            setup=PortfolioSetup(tmp);p=profile();p.update(loss_budget_scope='analysis_only',analysis_loss_budget=.35)
            with setup.session() as s:Engine(s,DemoModel()).set_profile(p,'2026-11-15')
            setup.draft({'goal':'Synthetic new draft'})
            with setup.session() as s:draft=s.latest('onboarding_draft')['body']
            self.assertEqual(draft['loss_budget_scope'],'analysis_only');self.assertEqual(draft['analysis_loss_budget'],.35)

    def test_bad_xlsx_is_local_failure(self):
        import tempfile
        from mara.research import Research
        from mara.additional_funds import collect
        with tempfile.TemporaryDirectory() as tmp:
            r=Research(tmp,transport=lambda url:b'<html>maintenance</html>')
            r.as_of='2026-11-16';m={'assets':{'XLV':{}}}
            collect(r,m,['XLV'])
            self.assertEqual([x['status'] for x in r.calls],['failed','failed'])
            self.assertTrue(all(x['reason'] for x in r.calls))


if __name__=='__main__':unittest.main()
