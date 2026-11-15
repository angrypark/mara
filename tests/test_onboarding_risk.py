import copy
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from mara.agents import DemoModel
from mara.engine import ContextNeedsInput
from mara.connection import save_private
from mara.domain import market,profile
from mara.onboarding import PortfolioSetup,InputError
from mara.risk import evaluate,history_metrics
from mara.service import Application,make_server

ROOT=Path(__file__).resolve().parent.parent


class ReadOnlyBroker:
    def __init__(self,*args): pass
    def holdings(self): return {'items':[{'symbol':'TEST','name':'Test','quantity':'2','currency':'USD','marketCountry':'US'}]}
    def sectors(self): return {'sectors':[{'sectorId':'1','name':'Technology','depth':0}]}
    def sector_stocks(self,sector): return {'stocks':[{'symbol':'TEST'}]}
    def stocks(self,symbols): return [{'symbol':s,'market':'NASDAQ','currency':'USD','securityType':'STOCK','status':'ACTIVE','leverageFactor':None} for s in symbols]
    def prices(self,symbols): return [{'symbol':s,'currency':'USD','lastPrice':'100','timestamp':datetime.now(timezone.utc).isoformat()} for s in symbols]
    def exchange_rate(self):
        now=datetime.now(timezone.utc)
        return {'baseCurrency':'USD','quoteCurrency':'KRW','midRate':'1400','rate':'1410',
                'validFrom':(now-timedelta(minutes=1)).isoformat(),'validUntil':(now+timedelta(minutes=1)).isoformat()}
    # Deliberately no submit, order, buying_power or execution methods.


class TestModel(DemoModel):
    mode='live'; identity={'mode':'live','model':'test-only'}
    def complete(self,role,guide,p,contract):
        result=super().complete(role,guide,p,contract)
        if role in ('buffett','marks','bogle','leader'):result['weights']={'TEST':0.2,'CASH':0.8}
        if role=='leader':result['action']='adjust'
        return result


def form(snapshot):
    p=json.loads((ROOT/'examples/profile.json').read_text())
    p.update(capital_amount=1000000,capital_mode='total',cash_krw=100000,cash_usd=0,
        total_assets=30000000,cash_need=100000,cash_need_date='2099-01-01',last_rebalanced=date.today().isoformat(),
        rationale='Test context',symbols='TEST',constraints='',risk_level='balanced',
        preferred_sectors=['Technology'],excluded_sectors=[],max_sector_fraction=0.4,
        max_equity_fraction=0.8,min_cash_fraction=0.1,max_foreign_fraction=1,
        max_loss_fraction=0.5,max_position_fraction=0.5,
        confirmed=True,snapshot_id=snapshot['id'],revision_reason='')
    p.pop('base_currency');p.pop('markets')
    return p


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        (root/'toss').mkdir()
        save_private(root/'toss/credentials.json',{'client_id':'fake','client_secret':'fake-secret','account_seq':1})
        save_private(root/'toss/policy.json',{'max_capital_krw':30000000})
        self.app=PortfolioSetup(root/'service',ReadOnlyBroker,TestModel,research_factory=None)
        self.snap=self.app.refresh()
        with self.app.session() as s:self.snapshot=s.get(self.snap['id'])
        self.value=form(self.snap)

    def tearDown(self):
        if self.app.thread:self.app.thread.join(10)
        self.tmp.cleanup()

    def test_draft_private_persistence_and_no_confirmation_reuse(self):
        self.app.draft({'goal':'partial','confirmed':True})
        self.assertEqual(self.app.state()['draft'],{'goal':'partial','confirmed':False})
        again=PortfolioSetup(self.app.directory)
        self.assertEqual(again.state()['draft']['goal'],'partial')
        self.assertEqual(self.app.path.stat().st_mode&0o777,0o600)
        self.assertFalse(again.state()['model']['configured'])

    def test_validation_confirmation_conflict_and_no_silent_demo(self):
        for change in ({'confirmed':False},{'preferred_sectors':['Technology'],'excluded_sectors':['Technology']},
                       {'capital_mode':''},{'max_sector_fraction':float('nan')},{'cash_krw':''}):
            with self.assertRaises(ValueError):self.app.start(dict(self.value,**change))
        self.app.model_factory=None
        with self.assertRaisesRegex(InputError,'모델 설정'):self.app.start(self.value)
        self.assertIsNone(self.app.state()['latest'])

    def test_read_only_generation_funding_separation_and_revision(self):
        r=self.app.generate(self.value,self.snapshot)
        self.assertEqual(r['valuation']['nav'],380000)
        self.assertEqual(r['funding']['proposal_capital'],1000000)
        self.assertEqual(r['funding']['additional_funding_needed'],620000)
        self.assertEqual(r['validation']['final_numeric']['metrics']['sector_exposures'],{'Technology':0.2})
        with self.app.session() as s:
            actual=s.latest('actual')['body'];self.assertEqual(actual['cash'],100000)
            self.assertEqual(actual['positions'],{'TEST':2})
            self.assertFalse(s.events('broker_intent'))
            self.assertIn('evidence_id',actual)
        with self.assertRaisesRegex(InputError,'변경 이유'):self.app.start(self.value)
        revised=self.app.generate(dict(self.value,revision_reason='changed preference'),self.snapshot)
        self.assertEqual(revised['revision_of'],r['event_id']);self.assertIsNone(revised['performance'])
        self.assertEqual(len(self.app.state()['history']),2)

    def test_actual_generation_coverage_reaches_every_role_and_blocks_unsupported_allocation(self):
        r=self.app.generate(self.value,self.snapshot)
        self.assertEqual(r['proposal']['action'],'defer')
        self.assertEqual(r['proposal']['eligibility'],'blocked')
        self.assertTrue(any('기업·시장' in x for x in r['validation']['final_numeric']['missing']))
        with self.app.session() as s:
            for event in s.events('agent_input'):
                self.assertFalse(event['body']['payload']['market']['coverage']['actionable_risky_allocation'])
            self.assertEqual(s.get(r['market_id'])['body']['coverage']['status'],'limited')

    def test_usd_cash_is_separate_and_foreign_cap_cannot_be_bypassed(self):
        class Hold(DemoModel):mode='live';identity={'mode':'live','model':'test-hold'}
        self.app.model_factory=Hold
        value=dict(self.value,cash_usd=100,cash_krw=100000,capital_amount=520000,max_foreign_fraction=0)
        r=self.app.generate(value,self.snapshot)
        self.assertEqual(r['valuation']['values']['USD_CASH'],140000)
        self.assertEqual(r['valuation']['values']['CASH'],100000)
        self.assertAlmostEqual(r['validation']['final_numeric']['metrics']['currencies']['USD'],420000/520000)
        self.assertIn('외화 표시 자산 비중 상한 초과',r['validation']['final_numeric']['errors'])
        self.assertEqual(r['proposal']['action'],'defer')

    def test_zero_actual_is_not_fabricated_cash(self):
        class Empty(ReadOnlyBroker):
            def holdings(self):return {'items':[]}
        self.app.client_factory=Empty
        snap=self.app.refresh()
        with self.app.session() as s:stored=s.get(snap['id'])
        r=self.app.generate(dict(form(snap),cash_krw=0),stored)
        self.assertEqual(r['valuation']['nav'],0)
        self.assertEqual(r['valuation']['weights'],{})
        self.assertEqual(r['funding']['additional_funding_needed'],1000000)

    def test_optional_candidates_use_disclosed_sector_screen(self):
        r=self.app.generate(dict(self.value,symbols=''),self.snapshot)
        with self.app.session() as s:
            screen=s.get(r['profile_id'])['body']['candidate_screen']
        self.assertTrue(screen['automatic']);self.assertEqual(screen['symbols'],['ITOT','IVV','TEST'])

    def test_holdings_changed_and_total_cap_block(self):
        class Changed(ReadOnlyBroker):
            def holdings(self):return {'items':[]}
        self.app.client_factory=Changed
        with self.assertRaisesRegex(InputError,'보유 수량'):self.app.generate(self.value,self.snapshot)
        self.app.client_factory=ReadOnlyBroker
        with self.assertRaisesRegex(InputError,'운용 한도'):
            self.app.generate(dict(self.value,capital_mode='additional',capital_amount=30000000),self.snapshot)

    def test_job_restart_and_safe_errors(self):
        self.app.job('test','running','pending');self.app.recover()
        self.assertEqual(self.app.state()['job']['status'],'interrupted')
        self.app.start(self.value);self.app.thread.join(10)
        self.assertEqual(self.app.state()['job']['status'],'completed')

    def test_context_questions_are_actionable_and_answer_reaches_next_analysis(self):
        question='추가 투자금의 출처와 투입 시점을 알려주세요.'
        class AskOnce(TestModel):
            def complete(model,role,guide,p,contract):
                result=super().complete(role,guide,p,contract)
                if role=='context' and not p['profile'].get('context_notes'):
                    result['missing']=[question]
                return result
        self.app.model_factory=AskOnce
        self.app.start(self.value);self.app.thread.join(10)
        state=self.app.state();job=state['job']
        self.assertEqual(job['status'],'needs_input');self.assertEqual(job['questions'],[question])
        self.assertNotIn('토스 연결',job['message']);self.assertIsNone(state['latest'])
        with self.app.session() as s:
            output=s.get(job['context_output_id'])['body']
            self.assertEqual(output['output']['missing'],[question])
            self.assertEqual(len(s.events('agent_output')),1)
            self.assertFalse(s.events('proposal'));self.assertFalse(s.events('broker_intent'))
        answer='추가 자금은 별도 저축이며 다음 달에 투입할 계획이에요.'
        self.app.start(dict(self.value,context_notes=answer));self.app.thread.join(10)
        state=self.app.state();self.assertEqual(state['job']['status'],'completed')
        self.assertEqual(state['draft']['context_notes'],answer)
        with self.app.session() as s:
            inputs=[x['body'] for x in s.events('agent_input') if x['body']['role']=='context']
            self.assertEqual(inputs[-1]['payload']['profile']['context_notes'],answer)
            self.assertEqual(inputs[-1]['payload']['profile']['asset_scope'],'financial_assets')

    def test_old_context_stop_recovered_once_without_rewriting_records(self):
        class Asking(TestModel):
            def complete(model,role,guide,p,contract):
                result=super().complete(role,guide,p,contract)
                if role=='context':result['missing']=['필수 현금의 사용 시점을 알려주세요.']
                return result
        self.app.model_factory=Asking
        self.app.job('legacy-job','running','분석 중')
        with self.assertRaises(ContextNeedsInput):self.app.generate(self.value,self.snapshot)
        self.app.job('legacy-job','failed','기존 일반 오류',error_type='ValueError')
        with self.app.session() as s:original=s.latest('onboarding_job')
        self.app.recover();state=self.app.state()
        self.assertEqual(state['job']['status'],'needs_input')
        self.assertEqual(state['job']['previous_job_event'],original['id'])
        self.app.recover()
        with self.app.session() as s:
            self.assertEqual(s.get(original['id']),original)
            self.assertEqual(len([r for r in s.events('onboarding_job') if r['body']['status']=='needs_input']),1)

    def test_generic_error_not_reclassified_without_valid_context_result(self):
        self.app.job('unknown','running','pending')
        with self.app.session() as s:s.append('failed',{'error_type':'ValueError'},date.today().isoformat(),'missing-output')
        self.app.job('unknown','failed','기존 일반 오류',error_type='ValueError')
        self.app.recover();self.assertEqual(self.app.state()['job']['status'],'failed')

    def test_model_config_not_exposed_and_permissions(self):
        self.app.model_factory=None
        r=self.app.save_model({'model':'test-model','api_key':'fake-secret-key'})
        self.assertNotIn('fake-secret-key',json.dumps(r))
        self.assertNotIn('fake-secret-key',json.dumps(self.app.state()))
        self.assertEqual(self.app.model_path.stat().st_mode&0o777,0o600)
        self.app.save_model({'model':'updated','api_key':''})
        self.assertEqual(json.loads(self.app.model_path.read_text())['api_key'],'fake-secret-key')


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.p=json.loads((ROOT/'examples/profile.json').read_text());self.p['cash_need']=0
        self.p['max_loss_fraction']=1;self.p['max_position_fraction']=1
        self.p['criteria']={'risk_level':'balanced','preferred_sectors':[],'excluded_sectors':[],
             'max_sector_fraction':0.4,'max_equity_fraction':1,'max_foreign_fraction':1,'min_cash_fraction':0}
        self.m=json.loads((ROOT/'examples/market.json').read_text())
        for a in self.m['assets'].values():
            a.update(asset_class='equity',currency='USD',sector_exposures={'Technology':1},sector_complete=True,
                sector_source='https://example.com/sectors',sector_as_of=self.m['as_of'],sector_valid_until='2099-01-01')

    def test_concentration_exclusion_and_deterministic_veto(self):
        r=evaluate({'BROAD':0.6,'CASH':0.4},self.p,self.m,1000)
        self.assertFalse(r['passed']);self.assertIn('섹터 상한 초과: Technology',r['errors'])
        self.assertEqual(r['metrics']['effective_positions'],1)
        self.p['criteria']['excluded_sectors']=['Technology']
        self.assertFalse(evaluate({'BROAD':0.1,'CASH':0.9},self.p,self.m,1000)['passed'])

    def test_unknown_etf_overlap_not_treated_as_diversified(self):
        a=self.m['assets']['BROAD'];a.pop('sector_exposures');a['asset_class']='unknown'
        self.p['criteria']['max_equity_fraction']=0.8
        r=evaluate({'BROAD':0.2,'CASH':0.8},self.p,self.m,1000)
        self.assertFalse(r['passed']);self.assertEqual(r['status'],'needs_review');self.assertTrue(r['missing'])
        self.assertIsNone(r['historical']['sharpe']);self.assertIsNone(r['historical']['max_drawdown'])
        self.assertEqual(r['metrics']['unknown_sector_fraction'],0.2)

    def test_overlapping_sector_tags_are_not_split(self):
        self.m['assets']['BROAD']['sector_exposures']={'Technology':1,'Hardware':1}
        r=evaluate({'BROAD':0.3,'CASH':0.7},self.p,self.m,1000)
        self.assertEqual(r['metrics']['sector_exposures'],{'Technology':0.3,'Hardware':0.3})

    def test_stale_sector_source_is_missing_and_zero_weight_ignored(self):
        self.m['assets']['BROAD']['sector_valid_until']='2020-01-01'
        result=evaluate({'BROAD':0.2,'CASH':0.8},self.p,self.m,1000)
        self.assertTrue(result['passed']);self.assertEqual(result['metrics']['unknown_sector_fraction'],0.2)
        self.p['criteria']['max_sector_fraction']=0.1
        self.assertFalse(evaluate({'BROAD':0.2,'CASH':0.8},self.p,self.m,1000)['passed'])
        self.assertTrue(evaluate({'BROAD':0,'CASH':1},self.p,self.m,1000)['passed'])
        self.m['assets']['BROAD']['sector_as_of']='2099-01-01'
        with self.assertRaises(ValueError):market(self.m)

    def test_asset_class_unknown_value_cannot_bypass_equity_cap(self):
        self.m['assets']['BROAD']['asset_class']='guaranteed-safe'
        with self.assertRaises(ValueError):market(self.m)

    def test_history_computation_and_no_fabricated_missing_observations(self):
        dates=[];day=date(2026,8,24)
        while len(dates)<60:
            if day.weekday()<5:dates.append(day.isoformat())
            day+=timedelta(days=1)
        self.m['as_of']=dates[-1]
        self.m['risk_history']={'dates':dates,'base_currency':self.m['base_currency'],'frequency':'daily',
            'return_type':'total_return','source':'https://example.com/total-returns','known_at':dates[-1],
            'returns':{'BROAD':[0.01,-0.01]*30,'CASH':[0]*60},'risk_free_returns':[0]*60,'benchmark_returns':[0.01,-0.01]*30}
        r=history_metrics({'BROAD':0.5,'CASH':0.5},self.m)
        self.assertEqual(r['status'],'available');self.assertAlmostEqual(r['benchmark_beta'],0.5)
        self.assertAlmostEqual(r['annualized_volatility'],0.005*(60/59)**0.5*252**0.5)
        self.assertGreater(r['max_drawdown'],0.005)
        self.assertEqual(r['sharpe'],0)
        self.m['risk_history']['returns']['CASH'].pop()
        self.assertEqual(history_metrics({'BROAD':0.5,'CASH':0.5},self.m)['status'],'unavailable')


class SetupHttpTests(unittest.TestCase):
    def test_form_routes_csrf_limits_and_no_order_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Application(Path(tmp)/'service');server=make_server(app,0)
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            base='http://127.0.0.1:'+str(server.server_port)
            def post(path,body,headers=None):
                h={'Content-Type':'application/json','Origin':base,'X-Mara-CSRF':app.nonce};h.update(headers or {})
                return urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(body).encode(),headers=h))
            try:
                with urllib.request.urlopen(base) as r:
                    html=r.read().decode();self.assertIn('max_sector_fraction',html);self.assertIn('포트폴리오 평가',html)
                with post('/api/setup/draft',{'goal':'test'}) as r:self.assertTrue(json.load(r)['saved'])
                from mara.clarifications import questions
                old={'summary':'합성 질문','constraints':[],'missing':['추가 자금 출처는요?']}
                with app.setup.session() as s:source=s.append('agent_output',{'role':'context','output':old},date.today().isoformat())
                answer={'context_output_id':source,'request_id':'a'*32,'answers':[{'question_id':questions(old)[0]['id'],'option_id':None,'text':'급여 저축','expected_answer_id':None}]}
                with self.assertRaises(urllib.error.HTTPError):post('/api/setup/answers',answer,{'X-Mara-CSRF':'invalid'})
                with post('/api/setup/answers',answer) as r:self.assertEqual(len(json.load(r)['answers']),1)
                for path,body,headers in [('/api/setup/draft',{}, {'Origin':'http://evil.test'}),
                    ('/api/setup/draft',{'goal':'x'*40000},{}),('/api/trade',{},{}),('/api/setup/model',{'model':'x'}, {})]:
                    with self.assertRaises(urllib.error.HTTPError):post(path,body,headers)
                with urllib.request.urlopen(base+'/dashboard.js') as r:self.assertEqual(r.status,200)
                # A running API keeps serving its matching frontend during an on-disk deployment.
                with patch('mara.service.resource',side_effect=RuntimeError('new files being deployed')):
                    for asset in ['/','/dashboard.js','/report.js','/clarifications.js','/dashboard.css']:
                        with urllib.request.urlopen(base+asset) as r:self.assertEqual(r.status,200)
                with urllib.request.urlopen(base+'/api/state') as r:
                    state=json.load(r);self.assertFalse(state['live_trading']);self.assertIsNone(state['onboarding']['latest'])
            finally:server.shutdown();server.server_close();t.join()

if __name__=='__main__':unittest.main()
