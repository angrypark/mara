import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from mara.store import Store
from mara.fact_catalog import snapshots,graph,persist,present,series_view,authoritative_facts

DAY='2026-11-14'
def fact(**extra):return dict(id='same-logical-id',topic='Synthetic evidence',text='Observed 5 USD',source='https://example.com/source',published_at=DAY,known_at=DAY,valid_until=DAY,uncertainty='Synthetic test',**extra)
def series():return {'schema_version':'mara.price-series/1.0','symbol':'TEST','currency':'USD','unit':'currency_per_share','price_kind':'close','frequency':'irregular','requested_start':'2026-08-14','requested_end':DAY,'source':'https://example.com/source','observations':[{'date':'2026-08-15','value':10},{'date':'2026-09-16','value':12},{'date':'2026-11-13','value':8}]}
class FactCatalogTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db';self.db=Store(self.path);self.token=self.db.create_user('alice');self.s=self.db.session(self.token);self.b=self.db.session(self.db.create_user('bob'))
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def report(self,facts,claim_ids=None):
  market=json.loads((Path(__file__).resolve().parent.parent/'examples/market.json').read_text());market['facts']=facts;mid=self.db.publish_market(market)
  r={'as_of':DAY,'market_id':mid,'run_id':'synthetic-run','proposal':{'investment_case':{'claims':[{'id':'claim-1','statement':'Synthetic conditional judgment','fact_ids':claim_ids or [facts[0]['id']],'status':'conditional'}]}}}
  eid=self.s.append('completed',r,DAY,r['run_id']);return self.s.get(eid)
 def test_same_logical_id_metadata_and_parent_versions_remain_distinct(self):
  f=fact();v=dict(f,id='valuation',research_tool='company_valuation',text=json.dumps({'assumptions':{'source_ids':[f['id']]}}))
  a=snapshots([f,v],DAY)[0];changed=dict(f,source='https://example.com/revised');b=snapshots([changed,v],DAY)[0]
  self.assertNotEqual(a[0]['snapshot_id'],b[0]['snapshot_id']);self.assertNotEqual(a[1]['snapshot_id'],b[1]['snapshot_id']);self.assertEqual(a[1]['original'],b[1]['original'])
  for key,value in [('text','Observed 5 KRW'),('known_at','2026-11-13'),('valid_until','2026-11-15')]:
   self.assertNotEqual(a[0]['snapshot_id'],snapshots([dict(f,**{key:value})],DAY)[0][0]['snapshot_id'])
 def test_persist_reopen_and_join_keep_old_versions_without_tenant_leak(self):
  old=self.report([fact()]);persist(self.s,old['id'],[fact()]);newfact=dict(fact(),text='Observed 9 USD');new=self.report([newfact]);persist(self.s,new['id'],[newfact])
  oldview=present(self.s,old['body'],[],old['id']);self.assertEqual(oldview['storage_status'],'stored_verified');self.assertEqual(oldview['facts'][0]['original']['text'],'Observed 5 USD')
  with self.assertRaises(PermissionError):present(self.b,old['body'],[],old['id'])
  rows=self.db.db.execute('SELECT c.completed_id,f.body FROM claim_facts c JOIN fact_snapshots f ON c.owner=f.owner AND c.snapshot_id=f.snapshot_id WHERE c.owner=?',('alice',)).fetchall();self.assertEqual(len(rows),2)
  self.assertEqual(len(self.db.db.execute('SELECT * FROM judgment_evidence WHERE owner=?',('alice',)).fetchall()),2)
  self.db.close();self.db=Store(self.path);self.s=self.db.session(self.token);self.assertEqual(present(self.s,old['body'],[],old['id']),oldview)
  with self.assertRaises(sqlite3.IntegrityError):self.db.db.execute("UPDATE fact_snapshots SET body='{}'")
 def test_authority_boundary_rejects_invented_facts_and_future_event_injection(self):
  row=self.report([fact()]);bad=dict(fact(),text='Invented')
  with self.assertRaises(ValueError):persist(self.s,row['id'],[bad])
  self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM fact_snapshots').fetchone()[0],0)
  self.s.append('research_evidence',{'fact':dict(fact(),id='later')},DAY,row['run_id'])
  self.assertEqual(len(authoritative_facts(self.s,row)),1)
  persist(self.s,row['id'],[fact()]);self.assertEqual(present(self.s,row['body'],[],row['id'])['storage_status'],'stored_verified')
 def test_missing_claim_ids_are_preserved_and_transaction_rolls_back_all(self):
  row=self.report([fact()],['missing']);value=persist(self.s,row['id'],[fact()]);self.assertEqual(value['claims'][0]['fact_refs'][0]['snapshot_id'],None);self.assertEqual(value['issues'][0]['code'],'missing_claim_fact')
  changed=dict(fact(),text='New value');r=self.report([changed]);before=self.db.db.execute('SELECT COUNT(*) FROM fact_snapshots').fetchone()[0]
  with self.assertRaises(RuntimeError):
   with self.db.transaction():persist(self.s,r['id'],[changed]);raise RuntimeError('rollback')
  self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM fact_snapshots').fetchone()[0],before)
 def test_series_return_is_not_continuous_decline_and_keeps_sampling_rules(self):
  value=series_view(series(),DAY);self.assertAlmostEqual(value['calculation']['period_return'],-.2);self.assertFalse(value['calculation']['each_observed_step_down']);self.assertFalse(value['calculation']['continuous_decline_verified'])
  decline=series();decline['observations'][1]['value']=9;value=series_view(decline,DAY);self.assertTrue(value['calculation']['each_observed_step_down']);self.assertFalse(value['calculation']['continuous_decline_verified'])
  self.assertEqual(value['calculation']['actual_start'],'2026-08-15');self.assertEqual(value['requested_start'],'2026-08-14');self.assertEqual(value['calculation']['missing_policy'],'no_interpolation')
  for key,value in [('value',True),('value',float('nan')),('date','2026-11-15')]:
   bad=series();bad['observations'][1][key]=value
   with self.assertRaises(ValueError):series_view(bad,DAY)
 def test_role_projection_keeps_canonical_identity_and_exact_delivery_digest(self):
  from mara.fact_catalog import derivation_binding,fingerprint
  from mara.research import project_fact
  original=dict(fact(),research_tool='sec_financials',raw_refs=[{'sha256':'a'*64}],text=json.dumps({'metrics':{}}))
  self.s.append('research_evidence',{'fact':original},DAY,'synthetic-run')
  delivered=project_fact(original,'buffett');self.assertNotEqual(original,delivered)
  parent=derivation_binding(self.s,'synthetic-run',DAY,'buffett',[delivered],[original['id']])[0]
  self.assertEqual(parent['content_sha256'],fingerprint(original));self.assertEqual(parent['delivered_content_sha256'],fingerprint(delivered));self.assertEqual(parent['delivery_scope'],'role_projection')
  self.assertEqual(parent['snapshot_id'],snapshots([original],DAY)[0][0]['snapshot_id'])
  with self.assertRaises(ValueError):derivation_binding(self.s,'synthetic-run',DAY,'buffett',[dict(delivered,text='changed')],[original['id']])
 def test_recorded_derivation_keeps_parent_version_and_flags_rebinding(self):
  f=fact();parent=snapshots([f],DAY)[0][0]
  value={'assumptions':{'source_ids':[f['id']]},'derivation':{'parents':[{'fact_id':f['id'],'snapshot_id':parent['snapshot_id'],'content_sha256':parent['content_sha256']}]}}
  v=dict(f,id='valuation',research_tool='company_valuation',text=json.dumps(value));a=snapshots([f,v],DAY)[0]
  self.assertEqual(a[1]['derivation_status'],'bound_parent_snapshots')
  b,issues=snapshots([dict(f,text='Revised source'),v],DAY)
  self.assertEqual(a[1]['snapshot_id'],b[1]['snapshot_id']);self.assertEqual(a[1]['parents'],b[1]['parents']);self.assertEqual(b[1]['derivation_status'],'parent_snapshot_mismatch')
  self.assertIn('parent_snapshot_mismatch',{i['code'] for i in issues})
  legacy=dict(v,text=json.dumps({'assumptions':value['assumptions']}));self.assertEqual(snapshots([f,legacy],DAY)[0][1]['derivation_status'],'legacy_report_citations')
 def test_invalid_series_fails_visible_without_fabricating_chart_and_past_validity_is_preserved(self):
  f=fact(series=series());nodes,issues=snapshots([f],DAY);self.assertIsNotNone(nodes[0]['series']);self.assertEqual(issues,[])
  for invalid in (None,[], 'broken'):
   n,i=snapshots([fact(series=invalid)],DAY);self.assertIsNone(n[0]['series']);self.assertEqual(i[0]['code'],'invalid_price_series')
  f['series']['source']='https://example.com/other';nodes,issues=snapshots([f],DAY);self.assertIsNone(nodes[0]['series']);self.assertEqual(issues[0]['code'],'invalid_price_series')
  nodes,_=snapshots([fact()],DAY);self.assertTrue(nodes[0]['current_at_report'])
  nodes,issues=snapshots([fact()],'2026-11-15');self.assertFalse(nodes[0]['current_at_report']);self.assertEqual(issues[0]['code'],'outside_report_time')
if __name__=='__main__':unittest.main()
