import copy
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from mara import research_sources as src
from mara.research import Research,PublicArchive,compact_market
from mara.contracts import schema,validate
from mara.toss import BrokerError,TossClient
from mara.onboarding import PortfolioSetup
from mara.engine import Engine
from mara.agents import DemoModel
from mara.store import Store
from mara.workbench import project
import test_onboarding_risk as fixture

ASOF='2026-11-15';NOW=datetime(2026,11,15,12,tzinfo=timezone.utc)

def observation(value,end='2025-12-31',start='2025-01-01',filed='2026-02-01',**kw):
 r={'val':value,'end':end,'filed':filed,'form':'10-K','accn':'0000000001-26-000001',**kw}
 if start:r['start']=start
 return r

def financial():
 return {'cik':1,'entityName':'Fixture','facts':{'us-gaap':{
   'Revenues':{'units':{'USD':[observation(100),observation(70,end='2024-12-31',start='2024-01-01',filed='2025-02-01')] }},
   'NetCashProvidedByUsedInOperatingActivities':{'units':{'USD':[observation(35)]}},
   'PaymentsToAcquirePropertyPlantAndEquipment':{'units':{'USD':[observation(8)]}},
   'Assets':{'units':{'USD':[observation(300,end='2026-09-30',start=None,filed='2026-11-01',form='10-Q')]}},
 }}}

def market():
 return {'as_of':ASOF,'base_currency':'USD','prices':{'AAPL':{'price':100,'observed_at':ASOF,'known_at':ASOF,'source':'https://example.com/quote'}},
 'assets':{'AAPL':{'kind':'STOCK','asset_class':'equity','market':'US','currency':'USD','stress_loss':.5,'liquid':False,'expense_ratio':0}},'facts':[]}

class SourceTests(unittest.TestCase):
 def test_issuer_metrics_preserve_units_dates_and_missing_fields(self):
  import html
  graph=[{'alternateName':'ITOT','name':'Fixture','category':'Equity','additionalProperty':[
   {'name':'Expense Ratio:','value':'0.03'},{'name':'Benchmark Index','value':'Index'},
   {'name':'NAV as of','value':'100','valueReference':{'value':'Nov 13, 2026'}}]},
   {'@id':'x#fund-description','description':'Broad equity'},
   {'@id':'x#holdings','mainEntity':{'contentUrl':src.FUNDS['ITOT']+'/latest-holdings.csv'}}]
  component={'componentId':'keyFundFacts','dataPoints':{
   'thirtyDayMedianBidAskSpread':{'label':'Spread','formattedValue':'0.01%','formattedAsOfDate':'Nov 13, 2026'},
   'thirtyDayAverageVolume':{'label':'Volume','formattedValue':'1,500','formattedAsOfDate':'Nov 13, 2026'}}}
  def page():return '<script type="application/ld+json">'+json.dumps({'@graph':graph})+'</script><walrus-render-on-client componentprops="'+html.escape(json.dumps(component),quote=True)+'"></walrus-render-on-client>'
  r=src.fund_profile(page(),'ITOT',ASOF);self.assertEqual(r['issuer_metrics']['thirtyDayMedianBidAskSpread']['value'],.0001)
  self.assertEqual(r['issuer_metrics']['thirtyDayAverageVolume']['value'],1500)
  component['dataPoints']['thirtyDayMedianBidAskSpread']['formattedValue']='0.01'
  component['dataPoints']['thirtyDayAverageVolume']['formattedAsOfDate']='Nov 16, 2026'
  r=src.fund_profile(page(),'ITOT',ASOF);self.assertFalse(r['issuer_metrics'])
  self.assertIn('thirtyDayMedianBidAskSpread',r['missing_issuer_metrics'])

 def test_diagnostics_separate_source_time_identity_and_unit_failures(self):
  from mara.research import safe_code
  for date,expected in [('2026-11-16','future_observation'),('2025-01-01','stale_observation')]:
   try:src.dated(date,ASOF,10)
   except ValueError as e:self.assertEqual(safe_code(e),expected)
  self.assertEqual(safe_code(src.EvidenceError('currency_mismatch')),'currency_mismatch')
  self.assertEqual(safe_code(KeyError('provider secret')),'source_structure_changed')

 def test_annual_ytd_units_restatements_and_future_are_separate(self):
  v=financial();rows=v['facts']['us-gaap']['Revenues']['units']['USD']
  rows.extend([observation(60,end='2026-09-30',start='2026-01-01',filed='2026-11-01',form='10-Q'),observation(102,filed='2026-03-01'),observation(999,filed='2026-12-01')])
  v['facts']['us-gaap']['Revenues']['units']['USD/shares']=[observation(9999)]
  out=src.sec_financials(v,ASOF)['metrics']['revenue'][0]
  self.assertEqual([r['value'] for r in out['observations']],[102,70]);self.assertEqual(out['unit'],'USD')
  self.assertEqual(out['observations'][0]['filed'],'2026-03-01');self.assertIn('form',out['observations'][0])
  self.assertEqual(src.sec_financials(v,'2026-02-10')['metrics']['revenue'][0]['observations'][0]['value'],100)
 def test_debt_components_are_not_summed_and_stale_is_marked(self):
  v=financial();v['facts']['us-gaap'].update({tag:{'units':{'USD':[observation(n,end='2024-01-01',start=None)]}} for tag,n in [('LongTermDebtCurrent',1),('LongTermDebtNoncurrent',9),('LongTermDebt',10)]})
  out=src.sec_financials(v,ASOF)
  self.assertEqual(len(out['metrics']['long_term_debt']),3);self.assertIn('long_term_debt',out['stale_metrics'])
 def test_identity_mismatch_empty_and_future_filings_fail(self):
  r={'cik':1,'name':'Fixture','tickers':['OTHER'],'filings':{'recent':{}}}
  with self.assertRaises(ValueError):src.sec_filings(r,'AAPL',ASOF)
  with self.assertRaises(ValueError):src.sec_financials({'facts':{}},ASOF)
 def test_fund_partial_negative_and_future_holdings_fail(self):
  for date,w in [('Nov 12, 2026','60'),('Nov 16, 2026','100'),('Nov 12, 2026','-10')]:
   csv=f'Fund Holdings as of,"{date}"\nTicker,Name,Sector,Asset Class,Weight (%)\nAAA,Company,Technology,Equity,{w}\n'
   with self.assertRaises(ValueError):src.fund_holdings(csv,ASOF)
  csv='Fund Holdings as of,"Nov 12, 2026"\nTicker,Name,Sector,Asset Class,Weight (%)\nAAA,Company,Technology,Equity,100\n'
  self.assertEqual(src.fund_holdings(csv,ASOF)['top_holdings'][0]['weight'],1)
 def test_price_history_is_not_total_return_and_rejects_bad_currency(self):
  rows=[{'timestamp':(NOW-timedelta(days=i+1)).isoformat(),'closePrice':str(100+i),'volume':'1000','currency':'USD'} for i in range(61)]
  v=src.price_history({'candles':rows},'AAA',ASOF)
  self.assertEqual(v['observations'],61);self.assertAlmostEqual(v['price_changes']['60_sessions'],100/160-1)
  self.assertIn('총수익률 아님',v['limits']);self.assertNotIn('risk_history',v)
  rows[0]['currency']='KRW'
  with self.assertRaises(ValueError):src.price_history({'candles':rows},'AAA',ASOF)
 def test_one_sided_crossed_and_stale_books_fail(self):
  raw={'timestamp':NOW.isoformat(),'currency':'USD','asks':[{'price':'100','volume':'1'}],'bids':[{'price':'99','volume':'2'}]}
  self.assertAlmostEqual(src.orderbook(raw,ASOF,NOW)['spread_fraction'],1/99.5)
  for change in ({'asks':[]},{'bids':[{'price':'101','volume':'2'}]},{'timestamp':'2026-01-01T00:00:00+00:00'},{'timestamp':'2026-11-15T23:59:59+00:00'}):
   with self.assertRaises(ValueError):src.orderbook(dict(raw,**change),ASOF,NOW)
 def test_empty_provider_book_is_not_parse_failure_or_executable_quote(self):
  raw={'timestamp':None,'currency':'USD','asks':[],'bids':[]}
  value=src.orderbook(raw,ASOF,NOW)
  self.assertEqual(value['availability'],'no_quote');self.assertNotIn('spread_fraction',value)
  with tempfile.TemporaryDirectory() as tmp:
   r=Research(tmp,NOW);r.record('orderbook','AAA',lambda:value,'https://developers.tossinvest.com/docs/market-data')
   self.assertEqual(r.calls[-1]['status'],'skipped');self.assertEqual(r.calls[-1]['reason'],'quote_not_observed');self.assertFalse(r.facts)
  with self.assertRaises((ValueError,TypeError)):
   src.orderbook(dict(raw,asks=[{'price':'100','volume':'1'}]),ASOF,NOW)
 def test_macro_observation_is_not_publication_or_riskfree_daily_return(self):
  csv='Date,3 Mo,2 Yr,10 Yr,30 Yr\n11/13/2026,4.0,4.1,4.3,4.7\n11/16/2026,9,9,9,9\n'
  out=src.treasury(csv,ASOF);self.assertEqual(out['observations'][0]['date'],'2026-11-13')
  self.assertAlmostEqual(out['observations'][0]['10y_minus_2y_pp'],.2)
  b={'status':'REQUEST_SUCCEEDED','Results':{'series':[{'seriesID':'LNS14000000','data':[{'year':'2026','period':'M10','value':'4.1'},{'year':'2026','period':'M11','value':'999'}]}]}}
  self.assertEqual(src.bls(b,'LNS14000000',ASOF)['observations'],[{'month':'2026-10','value':4.1,'footnotes':[]}])
 def test_raw_cache_hash_and_request_allowlist(self):
  with tempfile.TemporaryDirectory() as tmp:
   calls=[];a=PublicArchive(tmp,NOW,lambda u:calls.append(u) or b'{"value":1}')
   url='https://data.sec.gov/submissions/CIK0000000001.json'
   raw,first=a.get(url);raw,cached=a.get(url)
   self.assertEqual(len(calls),1);self.assertTrue(cached['cache_hit']);self.assertEqual(first['retrieved_at'],cached['retrieved_at'])
   with self.assertRaises(ValueError):a.get('https://127.0.0.1/secret')
   with self.assertRaises(ValueError):a.get('https://data.sec.gov:444/secret')
   path=Path(tmp)/(first['sha256']+'.raw');path.write_text('tampered')
   with self.assertRaises(ValueError):a.get(url)
 def test_provider_failures_and_budget_are_visible_no_fake_evidence(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Research(tmp,NOW,lambda u:(_ for _ in ()).throw(urllib.error.HTTPError(u,429,'secret text',{},None)))
   m=market();r.enrich(m,['AAPL'])
   validate(m['research'],schema('research'))
   self.assertFalse(m['facts']);self.assertEqual(m['coverage']['status'],'limited')
   from mara.decision import assessment
   self.assertTrue(assessment({'AAPL':1},m)['blockers'])
   self.assertTrue(all(c['status'] in ('failed','skipped') for c in m['research']['calls']));self.assertNotIn('secret text',json.dumps(m))
   r.used_chars=160000
   r.record('fed','US',lambda:{'items':[],'limits':'x'},src.FED)
   self.assertEqual(r.calls[-1]['status'],'skipped')
 def test_malformed_feed_is_local_failure_and_raw_is_preserved(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Research(tmp,NOW,lambda u:b'<rss><channel>')
   r.record('fed','US',lambda:src.fed_news(r.fetch(src.FED),ASOF),src.FED)
   self.assertEqual(r.calls[-1]['status'],'failed');self.assertEqual(len(r.calls[-1]['raw_refs']),1)
   r.record('sec_financials','AAPL',lambda:src.sec_financials(financial(),ASOF),'https://data.sec.gov/test')
   self.assertEqual(r.calls[-1]['status'],'collected')
 def test_changed_linked_data_shape_and_dependency_failure_are_local(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Research(tmp,NOW,lambda u:b'<script type="application/ld+json">[]</script>')
   m=market();r.enrich(m,['AAPL'])
   self.assertTrue(all(c['status'] in ('failed','skipped') for c in r.calls))
   self.assertEqual(next(c for c in r.calls if c['tool']=='sec_financials')['reason'],'SEC_identity_source_failed')
   self.assertEqual(len([c for c in r.calls if c['tool']=='fund_holdings']),2)
 def test_invalid_live_cik_falls_back_to_reconfirmed_identity(self):
  with tempfile.TemporaryDirectory() as tmp:
   def transport(url):
    if url==src.SEC_TICKERS:return b'{"0":{"ticker":"AAPL","cik_str":"invalid"}}'
    raise urllib.error.HTTPError(url,503,'Unavailable',{},None)
   r=Research(tmp,NOW,transport);m=market();r.enrich(m,['AAPL'])
   self.assertEqual(m['research']['selection']['sec_identity_mode'],'dated_bootstrap_reconfirmed_by_submissions')
   self.assertFalse(m['facts'])
   self.assertEqual(next(c for c in r.calls if c['tool']=='sec_financials')['reason'],'SEC_identity_source_failed')
 def test_historical_evidence_budget_preserves_rationales_and_does_not_cut_claims(self):
  m=market();m['facts']=[{'id':'long','topic':'test','text':'A'*44000,'source':'https://example.com','published_at':ASOF,'known_at':ASOF,'valid_until':ASOF}]
  m['research']={'schema_version':'mara.research/1.0.0','selection':{},'budget':{},'collected_at':NOW.isoformat(),'calls':[]}
  prior=compact_market(m,'validation',historical=True)
  self.assertEqual(prior['facts'],[]);self.assertEqual(prior['evidence_projection']['omitted_fact_ids'],['long'])
  self.assertEqual(len(m['facts'][0]['text']),44000)
 def test_role_projection_keeps_original_and_explicit_scope(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=Research(tmp,NOW);r.record('sec_financials','AAPL',lambda:src.sec_financials(financial(),ASOF),'https://data.sec.gov/test')
   m=market();m['facts']=r.facts;m['research']={'schema_version':'mara.research/1.0.0','selection':{},'budget':{},'collected_at':NOW.isoformat(),'calls':r.calls}
   original=copy.deepcopy(m)
   b=compact_market(m,'buffett');g=compact_market(m,'bogle')
   self.assertIn('metrics',json.loads(b['facts'][0]['text']));self.assertNotIn('metrics',json.loads(g['facts'][0]['text']))
   self.assertEqual(m,original);self.assertEqual([f['id'] for f in b['facts']],[f['id'] for f in g['facts']])
 def test_official_toss_research_routes_are_account_free_GET(self):
  calls=[]
  b=TossClient({'client_id':'x','client_secret':'y','account_seq':1},'/tmp/mara-unused-test-token',transport=lambda *a:calls.append(a) or {'result':{}})
  with patch.object(b,'token',return_value='fake'):
   b.candles('AAPL');b.orderbook('AAPL')
  self.assertTrue(all(c[0]=='GET' and 'X-Tossinvest-Account' not in c[2] for c in calls));self.assertIn('adjusted=true',calls[0][1])

class IntegrationTests(unittest.TestCase):
 setUp=fixture.SetupTests.setUp
 tearDown=fixture.SetupTests.tearDown
 def test_research_enters_all_roles_and_workbench_preserves_rejected_sources(self):
  class Collector:
   def __init__(self,*args,**kwargs):pass
   def enrich(self,m,symbols,broker,progress):
    m['facts'].append({'id':'research-test','topic':'Test revenue','text':'Synthetic revenue fixture only','source':'https://example.com/report','published_at':m['as_of'],'known_at':m['as_of'],'valid_until':m['as_of'],'uncertainty':'Synthetic only'})
    m['coverage']['available'].append('합성 재무 검증 fixture')
    m['research']={'schema_version':'mara.research/1.0.0','selection':{'symbols':symbols},'budget':{},'collected_at':NOW.isoformat(),'calls':[],'tools':[]}
  self.app.research_factory=Collector
  r=self.app.generate(self.value,self.snapshot)
  with self.app.session() as s:
   for e in s.events('agent_input'):self.assertIn('research-test',[f['id'] for f in e['body']['payload']['market']['facts']])
   doc=project(s,r['run_id']);validate(doc,schema('workbench'))
   evidence=next(c for c in doc['components'] if c['id']=='evidence')
   self.assertTrue(any(b['key']=='research_tools' for b in evidence['blocks']));self.assertEqual(r['proposal']['eligibility'],'blocked')
 def test_raw_archive_is_owned_run_scoped_and_hash_verified(self):
  r=self.app.generate(self.value,self.snapshot)
  sha='a'*64
  with self.assertRaises(PermissionError):self.app.research_raw(r['run_id'],sha)
  with self.assertRaises(PermissionError):self.app.research_raw('b'*32,sha)
  with self.assertRaises(PermissionError):self.app.research_raw(r['run_id'],'../../secrets')

if __name__=='__main__':unittest.main()
