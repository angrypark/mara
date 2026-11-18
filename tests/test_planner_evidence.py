import copy
import hashlib
import json
import unittest
from mara.domain import dumps
from mara.planner_evidence import overview
from mara.research_read import read


class Session:
    def __init__(self,events=()):self.rows=list(events)
    def events(self,kind):return [e for e in self.rows if e['kind']==kind]


def fact(id,text,**extra):
    return dict(id=id,topic='Synthetic '+id,source='https://example.org/source',text=text,
        published_at='2026-11-18',known_at='2026-11-18',uncertainty='Synthetic source scope',**extra)


def event(id,role,run_id,call,result,kind='research_tool_result',fact_id=None,**extra):
    return dict(id=id,seq=int(id.rsplit('-',1)[-1]),kind=kind,run_id=run_id,
        body=dict(role=role,call=call,result=result,fact_id=fact_id,**extra))


class PlannerEvidenceTests(unittest.TestCase):
    def test_complete_small_facts_preserve_values_and_no_input_mutation(self):
        payload={'market':{'facts':[fact('b','A complete short source statement.'),fact('a',dumps({'zero':0,'flag':False,'missing':None,'unit':'USD'}))]}}
        before=copy.deepcopy(payload);result=overview(Session(),payload,'run','marks')
        self.assertEqual(payload,before);self.assertEqual(result,overview(Session(),payload,'run','marks'))
        self.assertEqual([x['fact_id'] for x in result['facts']],['a','b'])
        self.assertEqual(result['facts'][0]['body'],{'zero':0,'flag':False,'missing':None,'unit':'USD'})
        self.assertEqual(result['facts'][1]['body'],'A complete short source statement.')
        self.assertTrue(all(x['content_status']=='complete_input_body' for x in result['facts']))
        for item in result['facts']:
            response=read(payload,item['original_read'])
            self.assertEqual(item['input_sha256'],response['sha256'])
    def test_large_json_contains_complete_original_values_and_explicit_omissions(self):
        raw={'unit':'USD','period':'quarter','observations':[{'date':'2026-%02d-01'%i,'value':i,'currency':'USD','note':'row '+str(i)} for i in range(1,100)],'unread_text':'secret long source '*1000}
        payload={'market':{'facts':[fact('large',dumps(raw))]}}
        entry=overview(Session(),payload,'run','marks')['facts'][0]
        self.assertEqual(entry['content_status'],'partial_input_body');self.assertNotIn('body',entry)
        projection=entry['projection'];self.assertGreater(projection['omitted_paths_count'],0)
        self.assertTrue(any(x['path']=='/observations' and x['reason']=='sampled_array' for x in projection['omitted']))
        self.assertTrue(any(x['path']=='/unread_text' for x in projection['omitted']))
        self.assertNotIn('secret long source',dumps(entry))
        for item in projection['values']:
            actual=raw
            for segment in item['path'].split('/')[1:]:actual=actual[int(segment)] if isinstance(actual,list) else actual[segment]
            self.assertEqual(item['value'],actual)
        self.assertTrue(any(x['path'].startswith('/observations/') and isinstance(x['value'],dict) for x in projection['values']))
    def test_long_plain_text_is_not_truncated_into_evidence(self):
        result=overview(Session(),{'market':{'facts':[fact('long','BEGIN '+('X'*20000)+' END')]}},'run','marks')
        self.assertEqual(result['facts'],[]);self.assertEqual(result['omitted_facts']['ids'],['long'])
        self.assertEqual(result['omitted_facts']['full_index'],'existing_evidence')
        self.assertEqual(result['selection']['metadata_only_excluded'],1)
        self.assertNotIn('BEGIN',dumps(result))
    def test_manifest_is_run_scoped_receipt_only_and_preserves_ranges_failures(self):
        payload={'market':{'facts':[fact('own','source')]}}
        call={'tool':'evidence_read','arguments':{'fact_id':'own','offset':0,'limit':500},'question_ids':['q-risk']}
        receipt=read(payload,call)
        events=[event('e-1','buffett','run',call,receipt),event('e-2','bogle','old-run',call,receipt),
            event('e-3','marks','run',call,receipt),event('e-4','buffett','run',{'tool':'filing_read','arguments':{'symbol':'TEST','accession':'a','offset':10},'question_ids':['q-value']},{'start':10,'end':200,'raw_ref':{'sha256':'raw'},'text':'DO NOT COPY OTHER ROLE BODY'},fact_id='not-delivered'),
            event('e-5','wood','run',{'tool':'company','arguments':{'symbol':'TEST'},'question_ids':['q-value']},{'status':'unavailable','reason':'source_down'},kind='research_tool_failure')]
        result=overview(Session(events),payload,'run','marks');rows=result['cross_role_reads']
        self.assertEqual([r['event_id'] for r in rows],['e-5','e-4','e-1'])
        self.assertEqual(rows[0]['status'],'failed');self.assertEqual(rows[0]['failure_reason'],'source_down')
        self.assertFalse(rows[1]['available_in_current_input']);self.assertEqual(rows[1]['ranges'],[{'start':10,'end':200}])
        self.assertTrue(rows[2]['matches_current_input']);self.assertTrue(rows[2]['available_in_current_input'])
        self.assertEqual(rows[2]['question_ids'],['q-risk']);self.assertTrue(all(r['receipt_only'] for r in rows))
        self.assertNotIn('DO NOT COPY',dumps(result));self.assertNotIn('e-2',dumps(result))
        payload['market']['facts'][0]['text']='changed projection'
        self.assertFalse(overview(Session(events),payload,'run','marks')['cross_role_reads'][-1]['matches_current_input'])
    def test_hard_budget_omitted_index_and_determinism_under_many_sources(self):
        payload={'market':{'facts':[fact('f%04d'%i,dumps({'unit':'USD','rows':list(range(500))})) for i in range(100)]}}
        events=[event('e-'+str(i),'bogle','run',{'tool':'filing_read','arguments':{'symbol':'TEST'},'question_ids':['q']},{'start':i*100,'end':(i+1)*100,'raw_ref':{'sha256':'raw'}}) for i in range(80)]
        for budget in (4000,32000):
            result=overview(Session(events),payload,'run','marks',budget)
            self.assertLessEqual(len(dumps(result)),budget);self.assertGreater(result['omitted_facts']['count'],0)
            self.assertEqual(len(result['facts'])+result['omitted_facts']['count'],100)
            self.assertGreater(result['omitted_receipts'],0)
            self.assertEqual(result,overview(Session(events),payload,'run','marks',budget))
    def test_duplicate_reads_collapse_without_inflating_source_coverage(self):
        payload={'market':{'facts':[fact('own','source')]}}
        call={'tool':'evidence_read','arguments':{'fact_id':'own'},'question_ids':['q']}
        receipt=read(payload,call)
        events=[event('e-'+str(i),'bogle','run',call,receipt) for i in range(42)]
        rows=overview(Session(events),payload,'run','marks')['cross_role_reads']
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['matching_receipts'],42)
        self.assertEqual(rows[0]['event_id'],'e-41');self.assertEqual(len(rows[0]['ranges']),1)
    def test_catalog_and_quote_volume_cannot_starve_market_and_company_source_bodies(self):
        catalogs=[fact('a-company-%03d'%i,'Unexcerpted source '+('x'*15000),research_tool='company_company') for i in range(100)]
        quotes=[fact('b-quote-%03d'%i,dumps({'instrument':'TEST'+str(i),'quote':{'price':100},'sector_tags':['Synthetic']})) for i in range(25)]
        candles=[fact('c-price-%03d'%i,dumps({'rows':[{'date':'2026-11-18','close':100}], 'unit':'USD'}),research_tool='candles') for i in range(25)]
        macro=[fact('z-market-%02d'%i,dumps({'observation_period':'2026-08-18/2026-11-18','unit':'percent',
            'observations':[{'period':'2026-10','value':i+1}], 'limits':'Synthetic macro source '+('context '*60)})) for i in range(13)]
        company=[fact('z-financial-%02d'%i,dumps({'unit':'USD','observations':[{'start':'2026-01-01','end':'2026-09-30','value':1000}]}),research_tool='sec_financials') for i in range(3)]
        payload={'market':{'facts':catalogs+quotes+candles+macro+company}}
        result=overview(Session(),payload,'run','evidence');selected=result['facts']
        self.assertGreaterEqual(sum(x['fact_id'].startswith('z-market-') for x in selected),8)
        self.assertGreaterEqual(sum(x['research_tool']=='sec_financials' for x in selected),1)
        if sum(x['research_tool']=='candles' for x in selected)>5:
            # Price data may borrow unused quota only after source bodies fit.
            self.assertEqual(sum(x['fact_id'].startswith('z-market-') for x in selected),13)
        self.assertTrue(all(x['content_status']!='metadata_only' for x in selected))
        self.assertEqual(result['selection']['metadata_only_excluded'],100)
        self.assertEqual(len(selected)+result['omitted_facts']['count'],len(payload['market']['facts']))
        self.assertLessEqual(len(dumps(result)),32000)
    def test_small_budget_counts_fixed_metadata_before_accepting_final_body(self):
        for size in range(2700,3201,50):
            with self.subTest(size=size):
                source=fact('f','x'*size);source['uncertainty']=''
                result=overview(Session(),{'market':{'facts':[source]}},'run','evidence',4000)
                self.assertLessEqual(len(dumps(result)),4000)
                self.assertEqual(len(result['facts'])+result['omitted_facts']['count'],1)


class PlannerOverviewFlowTests(unittest.TestCase):
    from test_evidence_resolution import EvidenceResolutionTests
    setUp=EvidenceResolutionTests.setUp
    def test_next_role_can_use_delivered_body_and_prior_read_without_repeating_read(self):
        from mara.company_research import research_loop
        from mara.agents import DemoModel
        from test_evidence_resolution import DAY
        qid=self.scope['questions'][0]['id'];source=copy.deepcopy(self.m['facts'][0])
        source['text']=dumps({'date':DAY,'yield':4.25,'unit':'percent','scope':'synthetic'})
        payload={'profile':self.p,'market':dict(copy.deepcopy(self.m),facts=[source]),'decision_scope':self.scope}
        class Reader(DemoModel):
            mode='live'
            def complete(inner,role,guide,request,contract):
                if request['round']==1:return {'reason':'Read original source once','calls':[{'tool':'evidence_read','arguments':{'fact_id':source['id']},'question_ids':[qid]}]}
                return {'reason':'Original read complete','calls':[],'stop_reason':'evidence_sufficient'}
        research_loop(self.s,Reader(),'buffett','guide',copy.deepcopy(payload),'shared-overview',DAY,self.lib)
        class Reuser(DemoModel):
            mode='live'
            def complete(inner,role,guide,request,contract):
                view=request['evidence_overview']
                self.assertEqual(view['facts'][0]['body']['yield'],4.25)
                self.assertEqual(view['cross_role_reads'][0]['question_ids'],[qid])
                self.assertTrue(view['cross_role_reads'][0]['receipt_only'])
                self.assertEqual(view['cross_role_reads'][0]['role'],'buffett')
                return {'reason':'Current source body is already delivered; receipt is not a review','calls':[],'stop_reason':'evidence_sufficient'}
        result=research_loop(self.s,Reuser(),'marks','guide',copy.deepcopy(payload),'shared-overview',DAY,self.lib)
        self.assertEqual(result['research_access']['calls'],0)
        self.assertEqual(result['research_access']['sufficiency'],'requires_independent_review')
        self.assertEqual(len(self.s.events('research_tool_result')),1)
        self.assertFalse(self.s.events('research_evidence'))
