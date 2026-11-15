import copy
import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from mara import domain as d
from mara.decision import POLICY,assessment,contributions,household,semantics,decision_findings
from mara.risk import evaluate
from mara.commentary_sources import report,news
from mara.agents import DemoModel,validate_output
from mara.engine import Engine
from mara.store import Store
from mara.workbench import project
from mara.contracts import validate,schema
import test_onboarding_risk as setup_fixture

ASOF='2026-11-15'

def profile():
    return {'base_currency':'USD','markets':['US'],'goal':'합성 월 적립 계획','horizon_months':120,
        'total_assets':0,'monthly_income':5000,'monthly_expenses':3000,'cash_need':0,'cash_need_date':'2027-11-15',
        'max_loss_fraction':.25,'max_position_fraction':.4,'contribution_amount':1000,'contribution_every_days':30,
        'contribution_schedule':'monthly','rebalance_every_days':90,'constraints':[],
        'proposal_capital':1000,'funding_source':'future_income',
        'household':{'property_value':400000,'mortgage_balance':200000,'monthly_debt_payment':700,'debt_payment_in_expenses':'yes'},
        'criteria':{'risk_level':'growth','preferred_sectors':[],'excluded_sectors':[],
                    'max_sector_fraction':.7,'max_equity_fraction':1,'min_cash_fraction':0,'max_foreign_fraction':1}}

def market():
    m={'as_of':ASOF,'base_currency':'USD','prices':{'FUND':{'price':100,'observed_at':ASOF,'known_at':ASOF,'source':'https://example.com/price'}},
        'assets':{'FUND':{'kind':'ETF','asset_class':'equity','market':'US','currency':'USD','stress_loss':.5,'liquid':False,'expense_ratio':.0003,'eligible':True}},
        'facts':[],'coverage':{'proposal_policy':POLICY,'status':'partial','missing':['Other companies unavailable']}}
    for tool,value in [('fund_profile',{'symbol':'FUND','objective':'Synthetic broad index','benchmark':'Synthetic index','expense_ratio':.0003}),('fund_holdings',{'holdings_count':100,'sector_weights':{'Technology':.3},'reported_weight_sum':1})]:
        m['facts'].append({'id':'research-'+tool+'-FUND','topic':'Synthetic only','text':d.dumps(value),'research_tool':tool,'source':'https://example.com/data','published_at':ASOF,'known_at':ASOF,'valid_until':'2026-12-01','uncertainty':'Synthetic only'})
    return m

class DecisionTests(unittest.TestCase):
    def test_calendar_month_and_debt_inclusion_are_exact(self):
        p=profile();self.assertEqual(contributions(p)['monthly_amount'],1000)
        self.assertEqual(household(p)['monthly_remaining_after_investing'],1000)
        p['household']['debt_payment_in_expenses']='no'
        self.assertEqual(household(p)['monthly_remaining_after_investing'],300)
        self.assertEqual(household(p)['property_equity'],200000)
        p['contribution_schedule']='days';self.assertGreater(contributions(p)['monthly_amount'],1000)
    def test_unknown_debt_is_not_zero_or_invented_payment(self):
        p=profile();p['household'].update(monthly_debt_payment=None,debt_payment_in_expenses='unknown')
        self.assertFalse(household(p)['cashflow_complete']);self.assertIsNone(household(p)['monthly_debt_payment'])
    def test_known_payment_unknown_scope_is_conditional_and_conservative(self):
        p=profile();p['household'].update(mortgage_balance=None,monthly_debt_payment=1700,debt_payment_in_expenses='unknown')
        h=household(p);self.assertFalse(h['cashflow_complete']);self.assertEqual(h['monthly_remaining_after_investing'],-700)
        self.assertIn('조건부',h['limits']);r=evaluate({'FUND':.4,'CASH':.6},p,market(),1000)
        self.assertFalse(r['passed']);self.assertTrue(any('상환액' in x for x in r['warnings']))
    def test_equity_identity_observation_and_filing_are_validated(self):
        m=market();m['assets']['FUND']['kind']='STOCK';m['facts']=[]
        row={'start':'2025-09-28','end':'2026-09-26','filed':'2026-11-03','value':123.,'accession':'0000320193-26-000026','form':'10-K'}
        filing={'symbol':'FUND','cik':'0000320193','filings':[dict(row,url='https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/a.htm')]}
        fin={'cik':320193,'metrics':{k:[{'unit':'USD','period_type':'annual','observations':[row]}] for k in ('revenue','operating_cashflow')}}
        def ready(f=fin,g=filing):
            m['facts']=[{'id':'research-'+tool+'-FUND','research_tool':tool,'valid_until':'2026-12-01','text':d.dumps(v)} for tool,v in [('sec_financials',f),('sec_filings',g)]]
            return assessment({'FUND':1},m)['blockers']
        self.assertFalse(ready())
        columns=['start','end','filed','value','accession','form'];compact=copy.deepcopy(fin);compact['observation_columns']=columns
        for series in compact['metrics'].values():series[0]['observations']=[[row[k] for k in columns]]
        self.assertFalse(ready(compact))
        for change in ({'unit':'shares'},{'observations':[]},{'observations':[dict(row,end='2020-09-26')]},{'observations':[dict(row,value=True)]}):
            bad=copy.deepcopy(fin);bad['metrics']['revenue'][0].update(change);self.assertTrue(ready(bad))
        self.assertTrue(ready(fin,dict(filing,filings=[{}])))
        self.assertTrue(ready(dict(fin,cik=123)))
    def test_selected_fund_can_be_deliberated_with_unrelated_missing_data(self):
        r=evaluate({'FUND':.4,'CASH':.6},profile(),market(),1000,{'nav':0,'values':{'CASH':0},'weights':{}})
        self.assertTrue(r['passed']);self.assertEqual(r['metrics']['actual_cash_available'],0)
        self.assertEqual(r['metrics']['proposal_cash_reserved'],600)
        self.assertEqual(r['historical']['status'],'unavailable');self.assertTrue(r['warnings'])
    def test_constraints_and_required_evidence_still_block(self):
        p=profile();m=market()
        self.assertFalse(evaluate({'FUND':.6,'CASH':.4},p,m,1000)['passed'])
        m['facts']=m['facts'][:1]
        self.assertFalse(evaluate({'FUND':.4,'CASH':.6},p,m,1000)['passed'])
        self.assertIn('내부 구성',assessment({'FUND':.4,'CASH':.6},m)['blockers'][0]['reason'])
    def test_invalid_fund_evidence_or_wrong_symbol_not_adopted(self):
        m=market();m['facts'][0]['text']=d.dumps({'symbol':'OTHER','objective':'Test','benchmark':'X','expense_ratio':0})
        self.assertTrue(assessment({'FUND':1},m)['blockers'])
        m['facts'][0]['text']='{}';self.assertTrue(assessment({'FUND':1},m)['blockers'])
    def test_exclusion_cannot_use_conservative_sector_bound_as_bypass(self):
        p=profile();p['criteria']['excluded_sectors']=['Technology']
        self.assertFalse(evaluate({'FUND':.4,'CASH':.6},p,market(),1000)['passed'])
        p['criteria']['excluded_sectors']=[];p['criteria']['max_sector_fraction']=.3
        self.assertFalse(evaluate({'FUND':.4,'CASH':.6},p,market(),1000)['passed'])
    def test_future_income_deficit_is_a_real_blocker(self):
        p=profile();p['monthly_expenses']=4500
        self.assertFalse(evaluate({'FUND':.4,'CASH':.6},p,market(),1000)['passed'])
    def test_legacy_snapshot_does_not_silently_lose_its_gate(self):
        m=market();m['coverage']={'actionable_risky_allocation':False}
        self.assertFalse(evaluate({'FUND':.4,'CASH':.6},profile(),m,1000)['passed'])
    def test_validation_findings_cannot_pass_a_blocker(self):
        value={'issues':['Fixture'],'unsupported_claims':[],'qualitative_pass':True,'reason':'Fixture',
            'findings':[{'category':'constraint','blocks_proposal':True,'subject':'Fixture','reason':'Limit','resolution':'Change plan','owner':'user'}]}
        with self.assertRaises(ValueError):validate_output('validation',value,{})
    def test_numeric_evidence_gap_keeps_owner_and_resolution_in_final_findings(self):
        m=market();m['facts']=m['facts'][:1]
        check=evaluate({'FUND':.4,'CASH':.6},profile(),m,1000)
        findings=decision_findings(check,{'qualitative_pass':True,'issues':[],'reason':'No qualitative issue'})
        self.assertTrue(findings[0]['blocks_proposal']);self.assertEqual(findings[0]['owner'],'evidence')
        self.assertTrue(findings[0]['resolution']);self.assertIn('내부 구성',findings[0]['reason'])
    def test_combined_findings_allow_all_agent_and_numeric_issues(self):
        finding={'category':'constraint','blocks_proposal':True,'subject':'Fixture','reason':'Constraint','resolution':'Review','owner':'leader'}
        findings=decision_findings({'errors':['Numeric limit'],'missing':[]},{'qualitative_pass':False,'reason':'Issues','findings':[finding]*25})
        self.assertEqual(len(findings),26)
        value={'scope':'portfolio_proposal_only','status':'blocked','numeric_blockers':['Numeric limit'],'analyst_blockers':[],
               'findings':findings,'execution_status':'not_authorized','funding_availability':'conditional_on_deposit','execution_checks':[]}
        validate(value,schema('decision'))
    def test_future_income_full_flow_keeps_zero_actual_and_monthly_plan(self):
        class Model(DemoModel):
            def complete(self,role,guide,p,contract):
                out=super().complete(role,guide,p,contract)
                if role in ('buffett','marks','bogle','leader'):out['weights']={'FUND':.4,'CASH':.6}
                if role=='leader':out['action']='adjust'
                return out
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');s=db.session(db.create_user('synthetic'));e=Engine(s,Model())
            e.set_profile(profile(),ASOF);e.set_holdings({'as_of':ASOF,'base_currency':'USD','cash':0,'positions':{},'rationale':'Synthetic empty account','last_rebalanced':ASOF})
            original=s.latest('actual');r=e.run(ASOF,db.publish_market(market()))
            self.assertEqual(r['proposal']['eligibility'],'review_now');self.assertEqual(r['valuation']['nav'],0)
            self.assertEqual(r['proposal']['monthly_allocation']['amounts']['FUND'],400)
            self.assertEqual(r['funding']['availability'],'conditional_on_deposit');self.assertEqual(s.latest('actual'),original)
            doc=project(s,r['run_id']);self.assertEqual(doc['schema_version'],'mara.workbench/1.1.0')
            self.assertTrue(all(row['body']['skills'] for row in s.events('agent_input')))
            self.assertFalse(any('perspectives' in row['body']['payload'] for row in s.events('agent_input') if row['body']['role'] in ('buffett','marks','bogle')))
            db.close()

class CommentaryTests(unittest.TestCase):
    def test_current_report_attribution_and_stale_or_shell_rejected(self):
        html='<div data-component="storyheader-panel"><h1>Fixture outlook</h1><p>November 13, 2026</p></div><h2>The Week That Was</h2>'+('<p>Analyst opinion only, with uncertainty and a different investment horizon from long term savings.</p>'*9)
        r=report(html,'schwab',ASOF);self.assertEqual(r['source_kind'],'institutional_opinion');self.assertLessEqual(r['excerpt_words'],150)
        for bad in [html.replace('2026','2027'),html.replace('2026','2020'),'<h1>Login</h1>November 13, 2026']:
            with self.assertRaises(ValueError):report(bad,'schwab',ASOF)
        with self.assertRaises(ValueError):report('<p>Economic calendar November 14, 2026</p>'+html.replace('2026','2020'),'schwab',ASOF)
    def test_news_is_headlines_only_and_future_duplicates_are_excluded(self):
        item='<item><title>Fixture</title><link>https://www.cnbc.com/test</link><pubDate>Sun, 15 Nov 2026 10:00:00 GMT</pubDate><description>Never treated as full article</description></item>'
        raw='<rss><channel>'+item*2+item.replace('/test','/future').replace('10:00','23:00')+'</channel></rss>'
        r=news(raw,ASOF,'2026-11-15T12:00:00+00:00');self.assertEqual(len(r['items']),1)
        self.assertEqual(r['items'][0]['scope'],'headline_only');self.assertNotIn('description',r['items'][0])
        with self.assertRaises(ValueError):news('<!DOCTYPE test>'+raw,ASOF,'2026-11-15T12:00:00+00:00')

class FutureIncomeSetupTests(unittest.TestCase):
    setUp=setup_fixture.SetupTests.setUp
    tearDown=setup_fixture.SetupTests.tearDown
    def test_future_plan_exceeding_current_assets_is_explicit_not_invented_cash(self):
        self.value.update(total_assets=500000,funding_source='future_income',contribution_schedule='monthly')
        r=self.app.generate(self.value,self.snapshot)
        self.assertEqual(r['funding']['availability'],'conditional_on_deposit')
        self.assertLess(r['valuation']['nav'],r['funding']['proposal_capital'])
        with self.app.session() as s:self.assertEqual(s.latest('profile')['body']['total_assets'],500000)
