import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from mara.company_research import CompanyLibrary,ResearchTools
from mara.domain import dumps
from mara.xbrl_read import run
from mara.contracts import validate,schema
from mara.store import Store

DAY='2026-11-18'


class XbrlReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.lib=CompanyLibrary(Path(self.tmp.name)/'library',today=DAY)
        self.rows=[self.row(100,'2026-01-01','2026-09-30','2026-10-30','10-Q',1),
            self.row(30,'2026-07-01','2026-09-30','2026-10-30','10-Q',1),
            self.row(105,'2026-01-01','2026-09-30','2026-11-01','10-Q/A',2),
            self.row(999,'2026-01-01','2026-09-30','2026-11-19','10-Q/A',3)]
        self.raw={'cik':1,'entityName':'Fixture','facts':{'us-gaap':{
            'PaymentsToAcquireProductiveAssets':{'label':None,'description':'A broader concept; not automatically maintenance capex.',
                'units':{'USD':self.rows,'EUR':[self.row(777,'2026-01-01','2026-09-30','2026-11-19','10-Q',3)]}},
            'FutureConcept':{'label':'productive future','units':{'USD':[self.rows[-1]]}},
            'Assets':{'label':'Assets','description':'Instant balance','units':{'USD':[dict(self.rows[0],val=500)]}}}}}
        self.raw['facts']['us-gaap']['Assets']['units']['USD'][0].pop('start')
        self.body=self.save(self.raw)
    def row(self,val,start,end,filed,form,n):
        return {'val':val,'start':start,'end':end,'filed':filed,'form':form,'accn':f'0000000001-26-{n:06d}','fy':2026,'fp':'Q3','frame':'CY2026Q3'}
    def save(self,raw):
        data=dumps(raw).encode();meta=self.lib.archive().preserve(data,'https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json')
        body={'symbol':'FIX','cik':1,'entity':'Fixture','known_at':DAY,'retrieved_at':meta['retrieved_at'],'raw_refs':[meta]}
        body['version']=hashlib.sha256(dumps(body).encode()).hexdigest()
        folder=self.lib.root/'companies/FIX';folder.mkdir(parents=True,exist_ok=True)
        (folder/(body['version']+'.json')).write_text(dumps(body));return body
    def search(self,**kw):return run(self.lib,'xbrl_search',dict(symbol='FIX',query='productive',**kw),DAY)
    def args(self,result=None,**kw):
        result=result or self.search()
        return dict(symbol='FIX',dossier_version=result['dossier_version'],expected_sha256=result['raw_ref']['sha256'],
            namespace='us-gaap',tag='PaymentsToAcquireProductiveAssets',unit='USD',**kw)
    def test_search_excludes_future_concepts_units_and_counts(self):
        result=self.search();self.assertEqual(result['total'],1)
        concept=result['concepts'][0];self.assertEqual(set(concept['units']),{'USD'})
        self.assertEqual(concept['units']['USD']['observations'],3);self.assertEqual(result['status'],'discovery_only')
        self.assertNotIn('observations',result)
    def test_search_read_pins_original_snapshot_and_keeps_periods_amendments_units(self):
        found=self.search();changed=copy.deepcopy(self.raw);changed['facts']['us-gaap']['PaymentsToAcquireProductiveAssets']['units']['USD'][0]['val']=222
        self.save(changed)
        result=run(self.lib,'xbrl_read',self.args(found),DAY)
        self.assertEqual({r['val'] for r in result['observations']},{100,30,105})
        self.assertEqual({r['form'] for r in result['observations']},{'10-Q','10-Q/A'})
        self.assertEqual({r['start'] for r in result['observations']},{'2026-01-01','2026-07-01'})
        self.assertTrue(all(r['fp']=='Q3' for r in result['observations']))
        empty=run(self.lib,'xbrl_read',dict(self.args(found),unit='EUR'),DAY)
        self.assertEqual(empty['status'],'no_observations');self.assertEqual(empty['observations'],[])
    def test_cursor_is_bound_to_snapshot_query_unit_period_and_reader_version(self):
        args=self.args(limit=1);result=run(self.lib,'xbrl_read',args,DAY)
        continuation=dict(args,offset=result['next_offset'],query_sha256=result['query_sha256'])
        second=run(self.lib,'xbrl_read',continuation,DAY)
        self.assertNotEqual(result['observations'],second['observations'])
        for change in ({'unit':'EUR'},{'period_start':'2026-01-01'},{'expected_sha256':'a'*64},{'dossier_version':None},{'query_sha256':None}):
            with self.assertRaises(ValueError):run(self.lib,'xbrl_read',dict(continuation,**change),DAY)
        with patch('mara.xbrl_read.VERSION','changed'):
            with self.assertRaises(ValueError):run(self.lib,'xbrl_read',continuation,DAY)
        with self.assertRaises(ValueError):run(self.lib,'xbrl_read',{'symbol':'FIX','namespace':'us-gaap','tag':'Assets','unit':'USD'},DAY)
    def test_archive_identity_and_hash_are_checked(self):
        args=self.args();path=self.lib.root/'raw'/(args['expected_sha256']+'.raw');path.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'archive_hash'):run(self.lib,'xbrl_read',args,DAY)
        wrong=copy.deepcopy(self.raw);wrong['cik']=2;self.save(wrong)
        with self.assertRaisesRegex(ValueError,'identity_mismatch'):self.search()
    def test_read_fact_is_only_citable_after_delivery_and_search_is_not_a_fact(self):
        db=Store(Path(self.tmp.name)/'test.sqlite3');self.addCleanup(db.close);s=db.session(db.create_user('fixture'))
        tools=ResearchTools(self.lib,s,'run',DAY);market={'facts':[]}
        search={'tool':'xbrl_search','arguments':{'symbol':'FIX','query':'productive'}}
        answer=tools.execute('buffett',search,market);self.assertIsNone(answer['fact_id']);self.assertEqual(market['facts'],[])
        call={'tool':'xbrl_read','arguments':self.args()}
        validate({'reason':'Inspect raw concept','calls':[call]},schema('research-plan'))
        answer=tools.execute('buffett',call,market);fact=market['facts'][0]
        self.assertEqual(fact['id'],answer['fact_id']);self.assertEqual(fact['research_tool'],'company_xbrl_read')
        self.assertEqual(json.loads(fact['text'])['observations'],run(self.lib,'xbrl_read',call['arguments'],DAY)['observations'])
        with patch.object(tools,'activate',return_value=False):
            tools.activation_budget={'requested_characters':100}
            answer=tools.execute('marks',call,{'facts':[]})
            self.assertEqual(answer['status'],'stored_not_activated');self.assertIsNone(answer['fact_id'])
    def test_instant_and_explicit_duration_filters_do_not_infer_from_fp(self):
        result=run(self.lib,'xbrl_read',dict(self.args(),tag='Assets'),DAY)
        self.assertNotIn('start',result['observations'][0]);self.assertIn('instant',result['period_rule'])
        result=run(self.lib,'xbrl_read',self.args(period_start='2026-07-01',period_end='2026-09-30'),DAY)
        self.assertEqual([r['val'] for r in result['observations']],[30])
