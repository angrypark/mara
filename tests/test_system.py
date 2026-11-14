import copy
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mara import domain as d
from mara.agents import DemoModel, HTTPModel
from mara.engine import Engine
from mara.knowledge import Knowledge
from mara.store import Store, Session, SHARED

ROOT=Path(__file__).resolve().parent.parent


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Store(Path(self.tmp.name)/'test.sqlite3')
        self.token=self.db.create_user('alice')
        self.s=self.db.session(self.token)
        self.other=self.db.session(self.db.create_user('bob'))
        self.model=DemoModel()
        self.e=Engine(self.s,self.model)
        self.p=json.loads((ROOT/'examples/profile.json').read_text())
        self.h=json.loads((ROOT/'examples/holdings.json').read_text())
        self.m=json.loads((ROOT/'examples/market.json').read_text())
        self.e.set_profile(self.p,'2026-11-14'); self.e.set_holdings(self.h)
        self.mid=self.db.publish_market(self.m)

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def initial(self): return self.e.run('2026-11-14',self.mid)

    def week(self,confirm=True):
        m=copy.deepcopy(self.m); m['as_of']='2026-11-21'
        for q in m['prices'].values(): q.update(observed_at='2026-11-20',known_at='2026-11-21')
        m['prices']['BROAD']['price']=404
        if confirm:
            h=copy.deepcopy(self.h); h['as_of']='2026-11-21'; self.e.set_holdings(h)
        return self.db.publish_market(m)

    def lesson(self,**kw):
        op={'action':'add','reason':'observed','text':'Review liquidity','topic':'liquidity','condition':'cash need',
            'perspective':'all','category':'lesson','roles':['*'],'refs':[self.mid], 'valid_until':None,'priority':5}
        op.update(kw); return op

    def test_initial_weekly_lineage_and_actual_separation(self):
        first=self.initial(); actual=self.s.latest('actual')['id']
        second=self.e.run('2026-11-21',self.week())
        self.assertEqual(second['previous_id'],first['event_id'])
        self.assertEqual(len(self.s.events('proposal')),2)
        self.assertEqual(second['proposal']['action'],'hold')
        self.assertAlmostEqual(second['performance']['pnl'],400)
        self.assertFalse(second['rebalance_due'])
        self.assertEqual(second['next_evaluation'],'2026-11-28')
        self.assertEqual(self.s.get(actual)['body'],self.h)
        self.assertEqual(len(self.s.events('anchor_check')),1)

    def test_independent_perspectives_and_guide_snapshots(self):
        self.initial()
        calls=[e['body'] for e in self.s.events('agent_input') if e['body']['role'] in ('buffett','marks','bogle')]
        self.assertEqual(len(calls),3)
        self.assertEqual(len({x['guide_hash'] for x in calls}),3)
        for x in calls:
            self.assertNotIn('perspectives',x['payload'])
            self.assertTrue(x['guide']); self.assertEqual(x['provider']['mode'],'demo')

    def test_tenant_read_write_export_isolation(self):
        r=self.initial()
        with self.assertRaises(PermissionError): self.other.get(r['event_id'])
        self.assertFalse(self.other.events('completed'))
        with self.assertRaises(PermissionError): self.db.session('wrong-token')
        self.assertNotIn(r['event_id'],d.dumps(self.other.export()))
        with self.assertRaises(PermissionError): Knowledge(self.other).apply(self.lesson(refs=[r['event_id']]),'2026-11-14')

    def test_raw_events_immutable(self):
        for sql in ['DELETE FROM events WHERE id=?','UPDATE events SET body=\'{}\' WHERE id=?']:
            with self.assertRaises(sqlite3.IntegrityError): self.db.db.execute(sql,(self.mid,))
        self.db.db.rollback()
        self.assertEqual(self.s.get(self.mid)['body'],self.m)

    def test_deposits_not_returns(self):
        self.initial(); mid=self.week()
        h=copy.deepcopy(self.h); h.update(as_of='2026-11-21',cash=21000); self.e.set_holdings(h)
        self.e.cashflow({'date':'2026-11-18','amount':1000,'reference':'bank-1'})
        r=self.e.run('2026-11-21',mid)
        self.assertAlmostEqual(r['performance']['pnl'],400)
        self.assertAlmostEqual(r['performance']['modified_dietz'],400/(80000+1000*3/7))

    def test_unconfirmed_actual_has_no_performance_claim(self):
        self.initial(); r=self.e.run('2026-11-21',self.week(False))
        self.assertIsNone(r['performance']['modified_dietz']); self.assertIsNone(r['performance']['pnl'])

    def test_flow_duplicate_and_late_correction_rejected(self):
        f={'date':'2026-11-15','amount':1000,'reference':'bank-1'}
        self.e.cashflow(f)
        with self.assertRaises(ValueError): self.e.cashflow(f)
        self.initial()
        with self.assertRaises(ValueError): self.e.cashflow(dict(f,date='2026-11-14',reference='late'))

    def test_future_and_stale_evidence(self):
        m=copy.deepcopy(self.m); m['facts'][0]['known_at']='2026-11-15'
        with self.assertRaises(ValueError): self.db.publish_market(m)
        m=copy.deepcopy(self.m); m['prices']['BROAD']['observed_at']='2026-10-01'
        with self.assertRaises(ValueError): self.db.publish_market(m)

    def test_duplicate_execution_and_weekly_due(self):
        self.initial()
        self.assertFalse(self.e.due('2026-11-20')['due']); self.assertTrue(self.e.due('2026-11-21')['due'])
        with self.assertRaises(ValueError): self.initial()
        self.assertEqual(len(self.s.events('completed')),1)

    def test_numeric_and_qualitative_veto(self):
        class Bad(DemoModel):
            def complete(self,role,*args):
                v=super().complete(role,*args)
                if role=='leader': v.update(action='adjust',weights={'BROAD':1})
                return v
        self.e.model=Bad(); r=self.initial()
        self.assertEqual(r['proposal']['action'],'defer'); self.assertEqual(r['proposal']['eligibility'],'blocked')
        self.assertEqual(self.s.latest('actual')['body'],self.h)

    def test_qualitative_veto_for_unquantified_constraint(self):
        class Bad(DemoModel):
            def complete(self,role,*args):
                v=super().complete(role,*args)
                if role=='validation': v.update(qualitative_pass=False,issues=['Tax evidence missing'])
                return v
        self.e.model=Bad(); self.assertEqual(self.initial()['proposal']['action'],'defer')

    def test_provider_failure_does_not_publish_or_change_actual(self):
        class Broken(DemoModel):
            def complete(self,*args): raise RuntimeError('network unavailable')
        self.e.model=Broken()
        with self.assertRaises(RuntimeError): self.initial()
        self.assertFalse(self.s.events('completed')); self.assertTrue(self.s.events('failed'))
        self.assertEqual(self.s.latest('actual')['body'],self.h)
        self.e.model=DemoModel(); self.initial()  # released lock; retry succeeds

    def test_malformed_and_invented_evidence_rejected(self):
        class Bad(DemoModel):
            def complete(self,role,*args):
                v=super().complete(role,*args)
                if role=='buffett': v['evidence_ids']=['invented']
                return v
        self.e.model=Bad()
        with self.assertRaises(ValueError): self.initial()
        self.assertFalse(self.s.events('completed')); self.assertTrue(self.s.events('agent_output'))

    def test_knowledge_duplicate_expiry_restore_and_provenance(self):
        k=Knowledge(self.s)
        first=k.apply(self.lesson(),'2026-11-14')
        k.apply(self.lesson(),'2026-11-14')
        exp=k.apply(self.lesson(text='Old assumption',valid_until='2026-11-15'),'2026-11-14')
        k.prune('2026-11-21')
        active=k.active('2026-11-21')
        self.assertEqual(len(active),1); self.assertEqual(active[0]['occurrences'],2)
        self.assertEqual(active[0]['refs'],[self.mid]); self.assertNotIn('confidence',active[0])
        key=self.s.get(exp)['body']['key']
        k.apply({'action':'restore','key':key,'version_event':exp,'reason':'Restore for review'},'2026-11-22')
        self.assertEqual(k.current('2026-11-22')[key]['text'],'Old assumption')
        self.assertEqual(self.s.get(first)['body']['version'],1)
        self.assertEqual(k.current('2026-11-22')[key]['version'],3)
        # Restoration preserves the old expiry; it cannot make expired evidence valid.
        self.assertNotIn(key,[x['key'] for x in k.active('2026-11-22')])

    def test_principles_rare_risk_not_evicted_for_recency(self):
        k=Knowledge(self.s); eid=k.apply(self.lesson(category='rare_risk'),'2026-11-14')
        key=self.s.get(eid)['body']['key']
        with self.assertRaises(ValueError): k.apply({'action':'archive','key':key,'reason':'Not used'},'2026-11-21')
        k.prune('2030-01-01'); self.assertTrue(k.active('2030-01-01'))

    def test_conflicts_preserved_and_context_bounded(self):
        k=Knowledge(self.s)
        k.apply(self.lesson(text='Liquidity strong',perspective='buffett'),'2026-11-14')
        k.apply(self.lesson(text='Liquidity fragile',perspective='marks'),'2026-11-14')
        audit=self.s.get(k.prune('2026-11-14'))['body']
        self.assertEqual(len(k.active('2026-11-14')),2); self.assertEqual(len(audit['unresolved_groups']),1)
        got=k.retrieve('2026-11-14','leader',limit=500)
        self.assertLessEqual(got['used_chars'],500)

    def test_shared_knowledge_cannot_reference_private_data(self):
        private=self.s.latest('profile')['id']; shared=Knowledge(Session(self.db,SHARED))
        with self.assertRaises(PermissionError): shared.apply(self.lesson(refs=[private]),'2026-11-14')
        shared.apply(self.lesson(),'2026-11-14')
        self.assertTrue(Knowledge(self.other).retrieve('2026-11-14','leader')['items'])

    def test_atomic_knowledge_batch_rollback(self):
        k=Knowledge(self.s)
        with self.assertRaises(ValueError):
            with self.db.transaction():
                k.apply(self.lesson(),'2026-11-14')
                k.apply({'action':'nonsense','reason':'test'},'2026-11-14')
        self.assertFalse(k.active('2026-11-14'))

    def test_weekly_learning_is_reused_next_perspective(self):
        class Learn(DemoModel):
            def complete(inner,role,guide,p,contract):
                out=super(Learn,inner).complete(role,guide,p,contract)
                if role=='memory': out['operations']=[self.lesson(refs=[p['reflection_id']])]
                return out
        self.e.model=Learn(); self.initial(); self.e.run('2026-11-21',self.week())
        calls=[e['body'] for e in self.s.events('agent_input') if e['effective']=='2026-11-21' and e['body']['role']=='buffett']
        self.assertTrue(calls[0]['payload']['knowledge']['items'])
        ref=calls[0]['payload']['knowledge']['items'][0]['refs'][0]
        self.assertEqual(self.s.get(ref)['body']['role'],'reflection')

    def test_locks_prevent_concurrent_user_run(self):
        self.s.lock('other-execution')
        with self.assertRaises(RuntimeError): self.initial()
        self.s.recover('Confirmed process stopped','2026-11-14'); self.initial()

    def test_demo_live_histories_separated(self):
        self.initial(); self.week(); self.e.model.mode='live'
        with self.assertRaises(ValueError): self.e.run('2026-11-21')

    def test_negative_nan_and_weight_errors(self):
        for value in [-1,float('nan'),float('inf'),True]:
            p=copy.deepcopy(self.p); p['cash_need']=value
            with self.assertRaises(ValueError): d.profile(p)
        with self.assertRaises(ValueError): d.weights({'CASH':0.9})

    def test_withdrawal_weighted_performance(self):
        r=d.performance(10000,9100,[{'date':'2026-11-18','amount':-1000}], '2026-11-14','2026-11-21')
        self.assertEqual(r['pnl'],100); self.assertAlmostEqual(r['modified_dietz'],100/(10000-1000*3/7))

    def test_guide_override_captured_without_editing_history(self):
        self.initial(); before=self.s.events('agent_input')[0]['body']['guide_hash']
        self.s.append('guide',{'role':'context','text':'New reviewed context guide','reason':'Evidence based update','version':1},'2026-11-21')
        self.e.run('2026-11-21',self.week())
        inp=[e for e in self.s.events('agent_input') if e['effective']=='2026-11-21' and e['body']['role']=='context'][0]
        self.assertNotEqual(inp['body']['guide_hash'],before)
        self.assertEqual(self.s.events('agent_input')[0]['body']['guide_hash'],before)

    def test_http_model_request_and_response_contract(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*a): return None
            def read(self): return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':'{"x": 1}'}}]}).encode()
        with patch.dict(os.environ,{'MARA_API_KEY':'secret','MARA_MODEL':'configured-model'}):
            model=HTTPModel()
            with patch('urllib.request.urlopen',return_value=Response()) as urlopen:
                self.assertEqual(model.complete('context','guide',{'a':1},{'x':1}),{'x':1})
                body=json.loads(urlopen.call_args[0][0].data)
                self.assertEqual(body['response_format'],{'type':'json_object'})
                self.assertNotIn('secret',d.dumps(body))

if __name__=='__main__': unittest.main()
