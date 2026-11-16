import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime,timezone,timedelta
from pathlib import Path
from mara.service import Application,make_server
from mara.store import Store
from mara.toss import TossClient,secret_config,BrokerError
from mara.trading import build_plan,Executor,validate_policy

NOW=datetime(2026,11,14,0,0,tzinfo=timezone.utc)

def fixture():
    policy={'market':'US','live_enabled':True,'account_seq':1,'max_order_krw':1000000,'max_daily_krw':3000000,
            'max_capital_krw':3000000,'allowed_symbols':['TEST'],'fee_buffer_fraction':'0.01'}
    report={'risk_budget':{'scope':'confirmed','effective_fraction':.25,'reference_fraction':.25,'personal_tolerance_confirmed':None,'definition':'Synthetic stress test','notice':'Synthetic fixture, no consent claim'},'event_id':'report-1','mode':'live','as_of':'2026-11-14','proposal':{'action':'adjust','eligibility':'review_now','weights':{'TEST':0.5,'CASH':0.5}}}
    actual={'base_currency':'USD','cash':1000,'positions':{'TEST':2}}
    quote={'symbol':'TEST','timestamp':NOW.isoformat(),'lastPrice':'100','currency':'USD'}
    snapshot={'captured_at':NOW.isoformat(),'account_seq':1,'open_orders':{'orders':[],'hasNext':False},
        'calendar':{'today':{'regularMarket':{'startTime':(NOW-timedelta(hours=1)).isoformat(),'endTime':(NOW+timedelta(hours=4)).isoformat()}}},
        'fx':{'baseCurrency':'USD','quoteCurrency':'KRW','rate':'1400','midRate':'1390',
              'validFrom':(NOW-timedelta(minutes=1)).isoformat(),'validUntil':(NOW+timedelta(minutes=1)).isoformat()},
        'prices':[quote],'stocks':[{'symbol':'TEST','market':'NASDAQ','currency':'USD','status':'ACTIVE','leverageFactor':None}],
        'holdings':{'items':[{'symbol':'TEST','quantity':'2'}]},'sellable':{'TEST':'2'},'buying_power':{'cashBuyingPower':'1000'}}
    return policy,report,actual,snapshot


class BrokerFake:
    account=1
    def __init__(self,fail=False,status='FILLED'): self.sent=[];self.fail=fail;self.status=status
    def prices(self,symbols):return fixture()[3]['prices']
    def open_orders(self):return {'orders':[]}
    def buying_power(self):return {'cashBuyingPower':'1000'}
    def sellable(self,symbol):return {'sellableQuantity':'2'}
    def submit(self,payload):
        self.sent.append(payload)
        if self.fail: raise BrokerError('timeout')
        return {'orderId':'fake-order'}
    def order(self,eid):return {'orderId':eid,'status':self.status,'execution':{'filledQuantity':'4' if self.status=='FILLED' else '1'}}


class TradingTests(unittest.TestCase):
    def test_limits_in_krw_with_fx_and_fee_buffer(self):
        p,r,a,s=fixture();plan=build_plan(r,a,s,p,NOW)
        self.assertEqual(plan['orders'][0]['quantity'],'4')
        self.assertEqual(float(plan['gross_krw']),565600)
        p['max_order_krw']=500000
        with self.assertRaises(ValueError):build_plan(r,a,s,p,NOW)

    def test_missing_capital_disabled_template(self):
        p,*_=fixture();p['max_capital_krw']=None
        with self.assertRaisesRegex(ValueError,'max_capital'):validate_policy(p)

    def test_stale_fx_quote_closed_session_and_existing_orders(self):
        p,r,a,s=fixture()
        for field in ['fx','prices','calendar','open_orders']:
            bad=copy.deepcopy(s)
            if field=='fx':bad['fx']['validUntil']=(NOW-timedelta(seconds=1)).isoformat()
            if field=='prices':bad['prices'][0]['timestamp']=(NOW-timedelta(minutes=2)).isoformat()
            if field=='calendar':bad['calendar']['today']['regularMarket']=None
            if field=='open_orders':bad['open_orders']['orders']=[{'status':'PENDING'}]
            with self.assertRaises(ValueError):build_plan(r,a,bad,p,NOW)

    def test_demo_report_and_holdings_mismatch_blocked(self):
        p,r,a,s=fixture();r['mode']='demo'
        with self.assertRaises(ValueError):build_plan(r,a,s,p,NOW)
        r['mode']='live';s['holdings']['items'][0]['quantity']='3'
        with self.assertRaises(ValueError):build_plan(r,a,s,p,NOW)

    def test_no_sell_proceeds_assumed(self):
        p,r,a,s=fixture();s['buying_power']['cashBuyingPower']='100'
        with self.assertRaises(ValueError):build_plan(r,a,s,p,NOW)

    def execute_fixture(self,tmp,broker):
        p,r,a,s=fixture();db=Store(Path(tmp)/'db.sqlite3');session=db.session(db.create_user('test'))
        return db,session,Executor(session,broker,p,Path(tmp)/'STOP',clock=lambda:NOW),build_plan(r,a,s,p,NOW)

    def test_ledger_before_submit_and_permanent_replay_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker=BrokerFake();db,s,e,plan=self.execute_fixture(tmp,broker)
            e.execute(plan,NOW)
            self.assertEqual(len(broker.sent),1);self.assertEqual(len(s.events('broker_intent')),1)
            with self.assertRaises(ValueError):e.execute(plan,NOW)
            self.assertEqual(len(broker.sent),1);db.close()

    def test_ambiguous_order_never_retried_even_new_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker=BrokerFake(fail=True);db,s,e,plan=self.execute_fixture(tmp,broker)
            with self.assertRaises(RuntimeError):e.execute(plan,NOW)
            plan['report_id']='report-2'
            with self.assertRaises(ValueError):e.execute(plan,NOW)
            self.assertEqual(len(broker.sent),1);self.assertTrue(s.events('broker_unknown'));db.close()

    def test_partial_fill_not_treated_as_full_and_blocks_new_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            broker=BrokerFake(status='PARTIAL_FILLED');db,s,e,plan=self.execute_fixture(tmp,broker)
            result=e.execute(plan,NOW)
            self.assertEqual(result[0]['execution']['filledQuantity'],'1')
            plan['report_id']='report-2'
            with self.assertRaises(ValueError):e.execute(plan,NOW)
            db.close()

    def test_kill_switch_and_disabled_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            db,s,e,plan=self.execute_fixture(tmp,BrokerFake());Path(tmp,'STOP').touch()
            with self.assertRaises(ValueError):e.execute(plan,NOW)
            Path(tmp,'STOP').unlink();e.policy['live_enabled']=False
            with self.assertRaises(ValueError):e.execute(plan,NOW)
            db.close()

    def test_daily_limit_includes_previous_account_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            db,s,e,plan=self.execute_fixture(tmp,BrokerFake());other=db.session(db.create_user('other'))
            iid=other.append('broker_intent',{'account_seq':1,'report_id':'old','notional_krw':'2900000'},'2026-11-14')
            other.append('broker_status',{'intent_id':iid,'order':{'status':'FILLED'}},'2026-11-14')
            with self.assertRaisesRegex(ValueError,'Daily'):e.execute(plan,NOW)
            db.close()

    def test_official_token_form_cache_and_account_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            def transport(method,path,headers,body=None):
                calls.append((method,path,headers,body))
                if path=='/oauth2/token':return {'access_token':'fake','expires_in':86400,'token_type':'Bearer'}
                return {'result':{'items':[]}}
            client=TossClient({'client_id':'id','client_secret':'secret','account_seq':1},Path(tmp)/'token.json',transport)
            client.holdings();client.holdings()
            self.assertEqual(len([c for c in calls if c[1]=='/oauth2/token']),1)
            self.assertIn(b'grant_type=client_credentials',calls[0][3])
            self.assertEqual(calls[1][2]['X-Tossinvest-Account'],'1')
            self.assertEqual((Path(tmp)/'token.json').stat().st_mode&0o777,0o600)


class ServiceTests(unittest.TestCase):
    def test_demo_crash_lock_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Application(tmp)
            db=Store(app.path); db.session(app.token).lock('crashed-demo'); db.close()
            app.recover_after_restart(); app.run_demo()
            self.assertEqual(len(app.state()['history']),1)

    def test_restart_persistence_weekly_demo_and_no_broker_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Application(tmp);app.run_demo();first=app.state()['latest']
            self.assertEqual(app.run_demo()['skipped'],'not due')
            app.run_demo(next_week=True)
            again=Application(tmp);state=again.state()
            self.assertEqual(len(state['history']),2)
            self.assertEqual(state['latest']['body']['previous_id'],first['id'])
            self.assertFalse(state['live_trading'])

    def test_http_csrf_host_and_demo_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Application(tmp);app.run_demo();server=make_server(app,0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            try:
                with urllib.request.urlopen(base+'/health') as r:self.assertFalse(json.load(r)['live_trading'])
                with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(urllib.request.Request(base+'/api/demo-next',data=b''))
                req=urllib.request.Request(base+'/api/demo-next',data=b'',headers={'Origin':base,'X-Mara-CSRF':app.nonce})
                with urllib.request.urlopen(req) as r:self.assertIn('event_id',json.load(r))
                with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(base+'/api/trade')
                req=urllib.request.Request(base+'/api/state',headers={'Host':'evil.test'})
                with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(req)
            finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
