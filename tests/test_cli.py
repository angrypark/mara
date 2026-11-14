import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mara.feeds import fetch_market
from mara.domain import market
from mara.engine import Engine
from mara.agents import DemoModel
from mara.store import Store

ROOT=Path(__file__).resolve().parent.parent


class OperationalTests(unittest.TestCase):
    def test_cli_onboard_run_export_and_tenant_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            db=str(Path(folder)/'app.sqlite3')
            env=dict(os.environ)
            def cli(*args,ok=True):
                p=subprocess.run([sys.executable,'-m','mara','--db',db,*args],cwd=str(ROOT),env=env,text=True,capture_output=True)
                self.assertEqual(p.returncode,0 if ok else 2,p.stderr)
                return json.loads(p.stdout) if ok else None
            alice=cli('create-user','alice'); bob=cli('create-user','bob')
            env['MARA_TOKEN']=alice['token']
            cli('profile','examples/profile.json','--as-of','2026-11-14')
            cli('holdings','examples/holdings.json'); cli('market','examples/market.json')
            report=cli('run','--demo','--as-of','2026-11-14')
            self.assertEqual(report['mode'],'demo')
            self.assertEqual(cli('tick','--demo','--as-of','2026-11-15')['skipped'],'not due')
            path=str(Path(folder)/'export.json'); cli('export',path)
            self.assertEqual(Path(path).stat().st_mode & 0o777,0o600)
            env['MARA_TOKEN']=bob['token']
            cli('report','--id',report['event_id'],ok=False)
            exported=cli('export',str(Path(folder)/'bob.json'))
            self.assertNotIn(report['event_id'],Path(exported['export']).read_text())

    def test_retirement_cash_constraint_defers(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Store(Path(folder)/'retirement.sqlite3'); s=db.session(db.create_user('retired'))
            e=Engine(s,DemoModel())
            p=json.loads((ROOT/'examples/profile.json').read_text())
            p.update(monthly_income=0,monthly_expenses=4000,cash_need=48000,max_loss_fraction=0.1)
            e.set_profile(p,'2026-11-14'); e.set_holdings(json.loads((ROOT/'examples/holdings.json').read_text()))
            mid=db.publish_market(json.loads((ROOT/'examples/market.json').read_text()))
            r=e.run('2026-11-14',mid)
            self.assertEqual(r['proposal']['action'],'defer')
            self.assertIn('Cash reserve below stated cash need',r['validation']['final_numeric']['errors'])
            db.close()

    def test_first_portfolio_from_cash(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Store(Path(folder)/'cash.sqlite3'); s=db.session(db.create_user('new'))
            e=Engine(s,DemoModel()); e.set_profile(json.loads((ROOT/'examples/profile.json').read_text()),'2026-11-14')
            h=json.loads((ROOT/'examples/holdings.json').read_text()); h.update(cash=80000,positions={})
            e.set_holdings(h)
            mid=db.publish_market(json.loads((ROOT/'examples/market.json').read_text()))
            self.assertEqual(e.run('2026-11-14',mid)['proposal']['weights'],{'CASH':1.0})
            db.close()

    def test_feed_requires_https_and_valid_market(self):
        with self.assertRaises(ValueError): fetch_market('http://untrusted.example')
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,size): return (ROOT/'examples/market.json').read_bytes()
        class Opener:
            def open(self,*args,**kwargs): return Response()
        with patch('urllib.request.build_opener',return_value=Opener()):
            self.assertEqual(fetch_market('https://trusted.example/feed')['as_of'],'2026-11-14')

    def test_original_market_fact_expiry_not_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Store(Path(folder)/'expiry.sqlite3'); s=db.session(db.create_user('user'))
            e=Engine(s,DemoModel()); e.set_profile(json.loads((ROOT/'examples/profile.json').read_text()),'2026-11-14')
            e.set_holdings(json.loads((ROOT/'examples/holdings.json').read_text()))
            m=json.loads((ROOT/'examples/market.json').read_text()); m['facts'][0]['valid_until']='2026-11-13'
            mid=db.publish_market(m); e.run('2026-11-14',mid)
            inputs=s.events('agent_input')
            self.assertEqual(inputs[0]['body']['payload']['market']['facts'],[])
            self.assertEqual(len(s.get(mid)['body']['facts']),1)
            db.close()

if __name__=='__main__': unittest.main()
