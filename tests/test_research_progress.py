import unittest
from mara.research_progress import Progress
from mara.research_read import read
from mara.domain import dumps


class ResearchProgressTests(unittest.TestCase):
    def test_reading_a_calculation_fact_cannot_become_source_progress(self):
        fact={'id':'model','research_tool':'company_valuation','topic':'Analyst assumptions','source':'fixture',
            'text':dumps({'assumptions':{'growth':.1},'value':123})}
        call={'tool':'evidence_read','arguments':{'fact_id':'model'},'question_ids':['candidate-FIX']}
        result=read({'market':{'facts':[fact]}},call)
        progress=Progress();observed=progress.observe(call,{'result':result},source_fact=fact)
        self.assertFalse(observed['eligible_for_extension']);self.assertEqual(observed['kind'],'calculation_read_or_assumption_model')
    def test_direct_and_wrapped_xbrl_share_observation_identity_in_both_orders(self):
        source={'raw_ref':{'sha256':'a'*64},'namespace':'us-gaap','tag':'A','unit':'USD','observations':[{'val':12,'accn':'original'}]}
        fact={'id':'row','research_tool':'company_xbrl_read','topic':'Original concept','source':'fixture','text':dumps(source)}
        direct={'tool':'xbrl_read','arguments':{},'question_ids':['candidate-FIX']}
        wrapper={'tool':'evidence_read','arguments':{'fact_id':'row'},'question_ids':['candidate-FIX']}
        result=read({'market':{'facts':[fact]}},wrapper)
        for reverse in (False,True):
            p=Progress()
            actions=[lambda:p.observe(direct,{'result':source,'fact_id':'row'}),lambda:p.observe(wrapper,{'result':result},source_fact=fact)]
            if reverse:actions.reverse()
            self.assertEqual([fn()['new_units'] for fn in actions],[1,0])
    def test_partial_metadata_is_not_progress_and_changing_wrapper_id_cannot_reset_source(self):
        source={'raw_ref':{'sha256':'a'*64},'namespace':'us-gaap','tag':'A','unit':'USD',
            'description':'Synthetic concept description. '*30,'observations':[{'val':12,'accn':'original'}]}
        fact={'id':'row','research_tool':'company_xbrl_read','topic':'Original concept','source':'fixture','text':dumps(source)}
        call={'tool':'evidence_read','arguments':{'fact_id':'row','limit':500},'question_ids':['candidate-FIX']};payload={'market':{'facts':[fact]}}
        p=Progress();result=read(payload,call);first=p.observe(call,{'result':result},source_fact=fact)
        self.assertFalse(first['eligible_for_extension']);self.assertEqual(first['kind'],'partial_source_wrapper_read')
        full=dict(call,arguments={'fact_id':'row','offset':500,'limit':12000,'expected_sha256':result['sha256']})
        self.assertEqual(p.observe(full,{'result':read(payload,full)},source_fact=fact)['new_units'],1)
        changed=dict(fact,id='another-wrapper');call=dict(call,arguments={'fact_id':'another-wrapper','limit':12000})
        self.assertEqual(p.observe(call,{'result':read({'market':{'facts':[changed]}},call)},source_fact=changed)['new_units'],0)
    def test_overlapping_document_ranges_ignore_new_fact_ids(self):
        progress=Progress();call={'tool':'filing_read','question_ids':['candidate-FIX'],'arguments':{'symbol':'FIX'}}
        def observe(start,end,fid,sha='a'*64):
            return progress.observe(call,{'fact_id':fid,'result':{'raw_ref':{'sha256':sha},'extraction_version':'v1','start':start,'end':end}})
        self.assertEqual(observe(0,100,'one')['new_units'],100)
        self.assertEqual(observe(25,75,'two')['new_units'],0)
        self.assertEqual(observe(50,150,'three')['new_units'],50)
        self.assertEqual(observe(0,150,'four')['new_units'],0)
        self.assertEqual(observe(0,100,'five','b'*64)['new_units'],100)
    def test_unactivated_failure_calculation_and_unlinked_calls_cannot_extend(self):
        p=Progress();call={'tool':'xbrl_read','question_ids':['candidate-FIX'],'arguments':{}}
        for answer in ({'status':'unavailable'},{'status':'stored_not_activated'}):
            r=p.observe(call,answer);self.assertFalse(r['eligible_for_extension']);self.assertFalse(r['delivered'])
        r=p.observe({'tool':'analysis_read','question_ids':['candidate-FIX']},{'result':{'sha256':'a'*64,'text':'new calculation'}})
        self.assertFalse(r['eligible_for_extension'])
        r=p.observe(dict(call,question_ids=[]),{'result':{}});self.assertFalse(r['eligible_for_extension'])
        p.finish_round([r]);self.assertIsNone(p.extend())
    def test_discovery_is_one_bridge_and_never_source_progress(self):
        p=Progress();call={'tool':'xbrl_search','arguments':{'symbol':'FIX'},'question_ids':['candidate-FIX']}
        def discover(tag):return p.observe(call,{'result':{'raw_ref':{'sha256':'a'*64},'concepts':[{'tag':tag}]}})
        r=discover('one');self.assertTrue(r['discovery_bridge']);self.assertFalse(r['eligible_for_extension'])
        p.finish_round([r]);self.assertEqual(p.extend(),'one_discovery_to_read_bridge')
        p.finish_round([discover('two')]);self.assertIsNone(p.extend())
        self.assertFalse(discover('one')['discovery_bridge'])
    def test_xbrl_progress_preserves_amendments_and_units_but_not_duplicate_pages(self):
        p=Progress();call={'tool':'xbrl_read','arguments':{},'question_ids':['candidate-FIX']}
        base={'raw_ref':{'sha256':'a'*64},'namespace':'us-gaap','tag':'A','unit':'USD','observations':[{'val':1,'accn':'original'}]}
        def observe(r):return p.observe(call,{'fact_id':'returned','result':r})
        self.assertEqual(observe(base)['new_units'],1);self.assertEqual(observe(base)['new_units'],0)
        self.assertEqual(observe(dict(base,observations=[{'val':2,'accn':'amended'}]))['new_units'],1)
        self.assertEqual(observe(dict(base,unit='EUR'))['new_units'],1)
