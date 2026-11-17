import copy,json,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
from mara.company_research import CompanyLibrary,ResearchTools,research_loop,document_catalog
from mara.document_text import extract,excerpt_page,EXTRACTION_VERSION
from mara.research_questions import freeze,ledger,validate_reviews
from mara.contracts import ContractError,schema,validate
from mara.analysis_skills import for_role
from mara.engine import Engine
from mara.agents import DemoModel
from mara.store import Store
from mara.workbench import project
from test_research import financial,observation
from mara.research_sources import sec_financials

DAY='2026-11-17';ACC='0000000001-26-000001';HASH='a'*64
ROOT=Path(__file__).resolve().parents[1]

class EvidenceResolutionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.db=Store(Path(self.tmp.name)/'test.sqlite3');self.addCleanup(self.db.close)
  self.s=self.db.session(self.db.create_user('fixture'))
  self.p=json.loads((ROOT/'examples/profile.json').read_text());self.m=json.loads((ROOT/'examples/market.json').read_text());self.h=json.loads((ROOT/'examples/holdings.json').read_text())
  self.m['as_of']=DAY;self.h['as_of']=DAY
  for q in self.m['prices'].values():q.update(observed_at=DAY,known_at=DAY)
  for f in self.m['facts']:f.update(published_at=DAY,known_at=DAY,valid_until=DAY)
  self.lib=CompanyLibrary(Path(self.tmp.name)/'public',today=DAY)
  self.scope=freeze(self.p,self.m)
 def run_demo(self):
  engine=Engine(self.s,DemoModel());engine.set_profile(self.p,DAY);engine.set_holdings(self.h)
  return engine.run(DAY,self.db.publish_market(self.m))
 def dossier(self):
  return {'symbol':'FIX','entity':'Fixture Inc.','annual_filing':[{'form':'10-K','filed':DAY,'accession':ACC,'url':'https://www.sec.gov/Archives/edgar/data/1/000000000126000001/a.htm'}]}
 def test_later_matches_and_hash_pinned_read(self):
  text='<html><body>Fixture Inc. Form 10-K '+('diluted table of contents. '+'x'*1800)*8+'ACTUAL NOTE diluted shares and stock compensation.'+'</body></html>'
  raw=text.encode();sha=hashlib.sha256(raw).hexdigest()
  with patch.object(self.lib,'latest',return_value=self.dossier()),patch.object(self.lib,'archive') as ar:
   ar.return_value.get.return_value=(raw,{'sha256':sha,'source':'https://www.sec.gov/fixture'})
   first=self.lib.filing_search('FIX','diluted',DAY,ACC)
   second=self.lib.filing_search('FIX','diluted',DAY,ACC,first['next_offset'],sha,EXTRACTION_VERSION)
   self.assertTrue(any('ACTUAL NOTE' in h['excerpt'] for h in second['hits']))
   hit=second['hits'][-1];read=self.lib.filing_read('FIX',DAY,ACC,hit['start'],12000,sha,EXTRACTION_VERSION)
   self.assertIn('ACTUAL NOTE',read['text']);self.assertEqual(read['raw_ref']['sha256'],sha)
   with self.assertRaisesRegex(ValueError,'hash'):self.lib.filing_read('FIX',DAY,ACC,100)
   with self.assertRaisesRegex(ValueError,'document_changed'):self.lib.filing_read('FIX',DAY,ACC,100,1000,HASH,EXTRACTION_VERSION)
   with self.assertRaisesRegex(ValueError,'extraction_changed'):self.lib.filing_read('FIX',DAY,ACC,100,1000,sha,'old-extractor')
   with self.assertRaisesRegex(ValueError,'unknown_filing'):self.lib.filing_read('FIX',DAY,'0000000001-26-999999')
 def test_no_match_is_different_from_absent_document_and_historical_rejected(self):
  self.assertEqual(excerpt_page('plain disclosure '*100,'diluted')['status'],'no_matches')
  with self.assertRaisesRegex(ValueError,'company_not_collected'):self.lib.filing_list('FIX',DAY)
  with patch.object(self.lib,'latest',return_value=self.dossier()):
   with self.assertRaisesRegex(ValueError,'Historical'):self.lib.filing_read('FIX','2026-11-16',ACC)
 def test_form_catalog_keeps_annual_after_many_current_reports(self):
  forms=['8-K']*10+['10-Q','10-K','10-Q']
  sub={'filings':{'recent':{'form':forms,'filingDate':[DAY]*12+['2026-11-18'],
    'accessionNumber':['0000000001-26-'+str(i).zfill(6) for i in range(13)],'primaryDocument':['a.htm']*13,'reportDate':[DAY]*13}}}
  rows=document_catalog(sub,1,DAY)
  self.assertEqual(len(rows),5);self.assertEqual({r['form'] for r in rows},{'8-K','10-Q','10-K'})
 def test_annual_share_basis_and_cashflow_do_not_take_ytd(self):
  raw=financial();raw['facts']['us-gaap']['WeightedAverageNumberOfDilutedSharesOutstanding']={'units':{'shares':[observation(100),observation(40,end='2026-09-30',start='2026-01-01',filed='2026-11-01',form='10-Q')]}}
  raw['facts']['us-gaap']['ShareBasedCompensation']={'units':{'USD':[observation(3)]}}
  data=sec_financials(raw,DAY);shares=data['metrics']['diluted_shares'][0]
  self.assertEqual(shares['unit'],'shares');self.assertEqual(shares['period_type'],'annual');self.assertEqual(len(shares['observations']),1)
  self.assertEqual(shares['observations'][0]['value'],100);self.assertEqual(data['metrics']['stock_compensation'][0]['observations'][0]['value'],3)
 def test_model_stop_and_budget_are_distinct_and_no_automatic_resolution(self):
  class Stop(DemoModel):
   mode='live'
   def complete(inner,role,g,p,c):return {'reason':'Document read enough for hypothesis','calls':[],'stop_reason':'evidence_sufficient'}
  payload={'profile':self.p,'market':self.m,'decision_scope':self.scope}
  result=research_loop(self.s,Stop(),'buffett','guide',copy.deepcopy(payload),'stop',DAY,self.lib)
  self.assertEqual(result['research_access']['stop_reason'],'evidence_sufficient')
  self.assertTrue(all(q['state']=='awaiting_analysis_review' for q in ledger(self.s,'stop',self.scope)['questions']))
  class Repeat(DemoModel):
   mode='live'
   def complete(inner,role,g,p,c):return {'reason':'Keep looking','calls':[{'tool':'filing_list','arguments':{'symbol':'FIX'},'question_ids':['portfolio-allocation']}]}
  result=research_loop(self.s,Repeat(),'buffett','guide',copy.deepcopy(payload),'budget',DAY,self.lib)
  self.assertEqual(result['research_access']['stop_reason'],'round_budget')
  self.assertEqual(len([e for e in self.s.events('research_activity') if e['run_id']=='budget']),4)
 def test_foreign_question_rejected_before_tool(self):
  class Bad(DemoModel):
   mode='live'
   def complete(inner,*args):return {'reason':'bad ref','calls':[{'tool':'filing_list','arguments':{'symbol':'FIX'},'question_ids':['another-user-question']}]}
  with patch.object(ResearchTools,'execute') as execute:
   result=research_loop(self.s,Bad(),'buffett','guide',{'profile':self.p,'market':self.m,'decision_scope':self.scope},'bad',DAY,self.lib)
   execute.assert_not_called();self.assertEqual(result['research_access']['status'],'invalid_plan')
 def test_question_denominator_survives_cash_and_old_workbench(self):
  result=self.run_demo();doc=project(self.s,result['run_id'])
  self.assertEqual([q['id'] for q in result['decision_scope']['questions']],[q['id'] for q in doc['extensions']['research_questions']['questions']])
  self.assertEqual(result['research_questions']['scope']['candidates'],self.scope['candidates'])
  self.assertEqual(len(self.s.events('actual')),1)
  old=copy.deepcopy(doc);old['extensions'].pop('research_questions');validate(old,schema('workbench'))
  inputs=[e['body']['payload'] for e in self.s.events('agent_input') if e['body']['role']=='evaluator']
  self.assertIn('research_questions',inputs[-1]['report'])
 def test_source_skill_reaches_research_and_final_role_inputs(self):
  selected,text=for_role('buffett');self.assertIn('public-evidence',[r['id'] for r in selected]);self.assertIn('filing_read',text)
  result=self.run_demo()
  entry=next(e['body'] for e in self.s.events('agent_input') if e['body']['role']=='buffett')
  self.assertIn('public-evidence',[r['id'] for r in entry['skills']]);self.assertIn('decision_scope',entry['payload'])
 def test_supported_review_cannot_invent_refs_or_omit_evidence(self):
  row={'question_id':'portfolio-allocation','status':'supported','reason':'test','fact_ids':[],'calculation_paths':[],'next_action':'monitor'}
  payload={'decision_scope':self.scope,'market':self.m,'analysis':{'metric':2},'final_proposal':{'weights':{'CASH':1}}}
  with self.assertRaises(ContractError):validate_reviews({'question_reviews':[row]},payload)
  row['fact_ids']=['foreign'];self.assertRaises(ContractError,validate_reviews,{'question_reviews':[row]},payload)
  row['fact_ids']=[];row['calculation_paths']=['/analysis/metric'];validate_reviews({'question_reviews':[row]},payload)
  row['calculation_paths']=['/profile/goal'];self.assertRaises(ContractError,validate_reviews,{'question_reviews':[row]},payload)
 def test_tool_read_fact_is_linked_to_question_and_independently_reviewed(self):
  raw=b'<html><body>Fixture Inc. Form 10-K '+b'diluted shares note 100 million. '*120+b'</body></html>';sha=hashlib.sha256(raw).hexdigest()
  qid=self.scope['questions'][1]['id']
  class Read(DemoModel):
   mode='live'
   def complete(inner,role,g,p,c):
    return {'reason':'Read note','calls':[{'tool':'filing_read','arguments':{'symbol':'FIX','accession':ACC},'question_ids':[qid]}]} if p['round']==1 else {'reason':'Read sufficient','calls':[],'stop_reason':'evidence_sufficient'}
  with patch.object(self.lib,'latest',return_value=self.dossier()),patch.object(self.lib,'archive') as ar:
   ar.return_value.get.return_value=(raw,{'sha256':sha,'source':'https://www.sec.gov/fixture'})
   payload=research_loop(self.s,Read(),'buffett','guide',{'profile':self.p,'market':copy.deepcopy(self.m),'decision_scope':self.scope},'read',DAY,self.lib)
  fid=payload['market']['facts'][-1]['id'];review={'question_reviews':[{'question_id':qid,'status':'supported','reason':'Synthetic selected note checked','fact_ids':[fid],'calculation_paths':[],'next_action':'Compare next period'}]}
  validate_reviews(review,dict(payload,final_proposal={'weights':{'CASH':1}}))
  result=ledger(self.s,'read',self.scope,[{'role':'validation','fact_ids':[fid]}],review)
  row=next(q for q in result['questions'] if q['id']==qid)
  self.assertEqual(row['state'],'reviewed_supported');self.assertEqual(row['delivered_fact_ids'],[fid]);self.assertEqual(row['fact_ids'],[fid])

 def test_invalid_document_and_docx_limits(self):
  import io,zipfile
  for text in ('Access Denied '+('unavailable '*20),'Other Corporation Form 10-K '+('disclosure '*20)):
   with patch.object(self.lib,'latest',return_value=self.dossier()),patch.object(self.lib,'archive') as ar:
    ar.return_value.get.return_value=(('<html>'+text+'</html>').encode(),{'sha256':HASH})
    with self.assertRaisesRegex(ValueError,'source_access_failed'):self.lib.filing_read('FIX',DAY,ACC)
  def docx(xml):
   b=io.BytesIO()
   with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('word/document.xml',xml)
   return b.getvalue()
  xml='<w:document xmlns:w="urn:word"><w:p><w:r><w:t>'+('note '*30)+'</w:t></w:r></w:p></w:document>'
  self.assertEqual(extract(docx(xml))[1]['format'],'docx')
  with self.assertRaisesRegex(ValueError,'declarations'):extract(docx('<!DOCTYPE bad>'+xml))
  with self.assertRaisesRegex(ValueError,'XML limit'):extract(docx('x'*16_000_001))

 def test_activity_causes_and_existing_review_sources_reach_workbench(self):
  result=self.run_demo();doc=project(self.s,result['run_id']);qid=self.scope['questions'][0]['id'];fid=self.m['facts'][0]['id']
  for status,reason in [('unavailable','source_access_failed_no_verified_fallback'),('stored_not_activated','active_budget')]:
   self.s.append('research_activity',{'role':'buffett','question_ids':[qid],'discovery_reason':None,'tool':'filing_read','target':'FIX','status':status,'fact_id':None,'source_status':None,'reason':reason,'collection_failures':[],'sufficiency':'not_reviewed'},DAY,result['run_id'])
  review={'question_reviews':[{'question_id':qid,'status':'supported','reason':'Existing source inspected','fact_ids':[fid],'calculation_paths':['/analysis/metric'],'next_action':'check next period'}]}
  value=ledger(self.s,result['run_id'],self.scope,[{'role':'validation','fact_ids':[fid]}],review)
  self.assertIn('source_access_failed',json.dumps(value));self.assertIn('active_budget',json.dumps(value))
  row=value['questions'][0];self.assertEqual(row['review_fact_ids'],[fid]);self.assertEqual(row['activated_fact_ids'],[])
  doc['extensions']['research_questions']=value
  from mara.contracts import validate_workbench
  validate_workbench(doc)
  for change in (lambda d:d['questions'][0].pop('activity_ids'),lambda d:d['questions'][0].update(fact_ids=['foreign']),lambda d:d['questions'][0].update(state='awaiting_analysis_review')):
   bad=copy.deepcopy(doc);change(bad['extensions']['research_questions'])
   with self.assertRaises(ContractError):validate_workbench(bad)

 def test_new_scope_requires_attribution_and_preserves_collection_failure(self):
  class Plan(DemoModel):
   mode='live'
   def complete(inner,*args):return {'reason':'collect','calls':[{'tool':'collect','arguments':{'symbols':['FIX']}}]}
  payload={'profile':self.p,'market':self.m,'decision_scope':self.scope}
  with patch.object(ResearchTools,'execute') as execute:
   self.assertEqual(research_loop(self.s,Plan(),'buffett','g',copy.deepcopy(payload),'unlinked',DAY,self.lib)['research_access']['status'],'invalid_plan');execute.assert_not_called()
  class Linked(Plan):
   def complete(inner,*args):
    p=super().complete(*args);p['calls'][0]['question_ids']=['portfolio-allocation'];return p
  with patch.object(self.lib,'collect',return_value={'receipts':[{'symbol':'FIX','status':'unavailable','reason':'http_403'}]}):
   research_loop(self.s,Linked(),'buffett','g',copy.deepcopy(payload),'failedcollect',DAY,self.lib)
  q=ledger(self.s,'failedcollect',self.scope)['questions'][0]
  self.assertEqual(q['activities'][0]['source_status'],'collection_failed');self.assertIn('http_403',json.dumps(q))

 def test_public_text_to_valuation_allocation_final_review_and_q1(self):
  from narrative_fixture import ReportingDemoModel
  from mara.company_research import quality
  self.m['assets']['BROAD']['kind']='STOCK';self.m.pop('synthetic',None)
  fin=sec_financials(financial(),DAY);body=self.dossier();body['symbol']='BROAD'
  body.update(cik=1,known_at=DAY,version='fixture-version',financials=fin,quality=quality(fin),filings={'filings':body['annual_filing'],'limits':'synthetic'},raw_refs=[{'source':'https://data.sec.gov/submissions/CIK0000000001.json'},{'source':'https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json'}])
  for ref in body['raw_refs']:ref.update(sha256=HASH,retrieved_at=DAY+'T00:00:00Z',bytes=100,cache_hit=False)
  self.lib.quote_provider=lambda symbol:{'price':400,'currency':'USD','observed_at':DAY}
  raw=b'<html>Fixture Inc. Form 10-K '+b'normalized owner earnings 10 USD per diluted share. '*100+b'</html>'
  class Scenario(ReportingDemoModel):
   mode='live';identity={'mode':'live','model':'synthetic-public-tool-fixture'}
   def complete(inner,role,g,p,c):
    if c.get('$id')=='urn:mara:research-plan:1.0.0':
     if role!='buffett' or p['round']==4:return {'reason':'Fixture scope finished','calls':[],'stop_reason':'evidence_sufficient'}
     if p['round']==1:call={'tool':'company','arguments':{'symbol':'BROAD'}}
     elif p['round']==2:call={'tool':'filing_read','arguments':{'symbol':'BROAD','accession':ACC}}
     else:
      refs=[r['answer']['fact_id'] for r in p['research_results']]
      a={'owner_earnings_per_share':10,'currency':'USD','earnings_period':'synthetic annual','share_basis':'fixture diluted shares','normalization':'synthetic assumption, not automatic CFO-capex','price':400,'price_as_of':DAY,'source_ids':refs,'margin_of_safety':.2,'scenarios':[{'name':n,'growth':v,'discount':.1,'terminal_growth':.02,'years':5,'reason':'Synthetic sensitivity'} for n,v in [('bear',0),('base',.03),('bull',.06)]]}
      call={'tool':'valuation','arguments':{'symbol':'BROAD','assumptions':a}}
     call['question_ids']=['candidate-BROAD'];return {'reason':'Synthetic evidence chain','calls':[call]}
    out=super().complete(role,g,p,c)
    value=next((f for f in p.get('market',{}).get('facts',[]) if f.get('research_tool')=='company_valuation'),None)
    if value and role=='buffett':out['decision_basis']=['Synthetic value scenarios '+value['id']+' support retaining current weights only as fixture; no investment conclusion.']
    if value and role=='leader':out['rationale']='Synthetic valuation '+value['id']+' considered alongside unchanged current allocation; missing product evidence remains explicit.'
    if role=='validation' and p.get('final_proposal'):
     out['question_reviews']=[{'question_id':'candidate-BROAD','status':'unresolved','reason':'Value chain works; real assumptions and suitability not established','fact_ids':[value['id']] if value else [],'calculation_paths':[],'next_action':'Independently justify normalization and alternatives'}]
    return out
  with patch.object(self.lib,'latest',return_value=body),patch.object(self.lib,'archive') as ar:
   ar.return_value.get.return_value=(raw,{'sha256':hashlib.sha256(raw).hexdigest(),'source':'https://www.sec.gov/fixture','bytes':len(raw),'retrieved_at':DAY+'T00:00:00Z','cache_hit':False})
   e=Engine(self.s,Scenario(),self.lib);e.set_profile(self.p,DAY);e.set_holdings(self.h)
   result=e.run(DAY,self.db.publish_market(self.m))
  q=next(q for q in result['research_questions']['questions'] if q['id']=='candidate-BROAD')
  self.assertEqual([a['tool'] for a in q['activities']],['company','filing_read','valuation'])
  self.assertEqual(q['state'],'reviewed_unresolved');self.assertIn(q['review_fact_ids'][0],result['proposal']['rationale'])
  coverage=next(r for r in result['coverage_ledger'] if r['id']=='selection.quality_price')
  note=next(r for r in coverage['asset_requirements'] if r['target']=='BROAD' and r['evidence_type']=='company_filing_search')
  self.assertTrue(note['retrieved'])
  evaluator=next(e['body']['payload'] for e in self.s.events('agent_input') if e['body']['role']=='evaluator')
  self.assertEqual(evaluator['report']['research_questions'],result['research_questions'])
  doc=project(self.s,result['run_id']);self.assertTrue(doc['extensions']['evaluation']);self.assertEqual(len(self.s.events('actual')),1)

if __name__=='__main__':unittest.main()
