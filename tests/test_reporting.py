import copy
import json
import tempfile
import unittest
from pathlib import Path
from mara.agents import DemoModel
from mara.engine import Engine
from mara.reporting import present
from mara.store import Store

ROOT=Path(__file__).resolve().parent.parent

class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Store(Path(self.tmp.name)/'test.sqlite3')
        self.s=self.db.session(self.db.create_user('report-owner'));self.e=Engine(self.s,DemoModel())
        self.p=json.loads((ROOT/'examples/profile.json').read_text())
        self.h=json.loads((ROOT/'examples/holdings.json').read_text())
        self.m=json.loads((ROOT/'examples/market.json').read_text())
        self.e.set_profile(self.p,'2026-11-14');self.e.set_holdings(self.h)
        self.first=self.e.run('2026-11-14',self.db.publish_market(self.m))
    def tearDown(self):self.db.close();self.tmp.cleanup()

    def test_initial_join_preserves_original_and_all_agent_records(self):
        row=self.s.get(self.first['event_id']);view=present(self.s,row)['view']
        self.assertEqual(view['kind'],'initial');self.assertIsNone(view['previous'])
        self.assertEqual(view['base_currency'],'USD')
        self.assertEqual(view['market_analysis']['facts'],['demo-1'])
        self.assertEqual(len(view['agent_records']['validation']),2)
        for records in view['agent_records'].values():
            for record in records:
                output=self.s.get(record['output_id'])['body']
                self.assertEqual(output['input_id'],record['input_id'])
                self.assertEqual(len(record['guide_hash']),64)
        self.assertEqual(present(self.s,row)['body'],row['body']);self.assertNotIn('view',row['body']);self.assertNotIn('view',self.s.get(row['id'])['body'])
        self.assertIsNone(view['prices'][0]['price_change'])

    def test_weekly_price_lineage_and_unreconciled_return_remains_missing(self):
        m=copy.deepcopy(self.m);m['as_of']='2026-11-21';m['prices']['BROAD']['price']=440
        for q in m['prices'].values():q.update(observed_at='2026-11-20',known_at='2026-11-21')
        h=dict(self.h,as_of='2026-11-21',cashflows_reconciled=False);self.e.set_holdings(h)
        result=self.e.run('2026-11-21',self.db.publish_market(m))
        row=present(self.s,self.s.get(result['event_id']));v=row['view']
        self.assertEqual(v['kind'],'weekly');self.assertEqual(v['previous']['id'],self.first['event_id'])
        quote=next(q for q in v['prices'] if q['symbol']=='BROAD')
        self.assertAlmostEqual(quote['price_change'],.1)
        self.assertEqual(quote['previous_observed_at'],'2026-11-13')
        self.assertIsNone(row['body']['performance']['modified_dietz'])
        self.assertTrue(v['memory']);self.assertIn('changes',v['pruning'])

    def test_old_role_shape_supported_without_rewriting_and_expired_source_filtered(self):
        # Historical completed records may lack the newly requested narrative fields.
        body=copy.deepcopy(self.first);body.pop('event_id');body['run_id']='old-run-without-outputs'
        market=copy.deepcopy(self.m);market['facts'][0]['valid_until']='2026-11-13'
        body['market_id']=self.db.publish_market(market)
        for p in body['perspectives'].values():p.pop('decision_basis');p.pop('changes_since_previous')
        eid=self.s.append('completed',body,'2026-11-14',body['run_id'])
        row=present(self.s,self.s.get(eid));self.assertIsNone(row['view']['market_analysis'])
        self.assertEqual(row['view']['sources'],[])
        self.assertEqual(row['view']['expired_source_count'],1)
        self.assertNotIn('decision_basis',row['body']['perspectives']['buffett'])

    def test_tenant_isolation_and_read_original_by_id(self):
        row=self.s.get(self.first['event_id']);other=self.db.session(self.db.create_user('other'))
        with self.assertRaises(PermissionError):present(other,row)
        forged=copy.deepcopy(row);forged['body']['proposal']['rationale']='forged'
        self.assertNotEqual(present(self.s,forged)['body']['proposal']['rationale'],'forged')
        with self.assertRaises(PermissionError):present(self.s,self.s.latest('profile'))
