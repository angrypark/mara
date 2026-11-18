import copy,unittest
from mara.research_read import read
from mara.research_questions import validate_reviews,QuestionReviewError
from mara.contracts import ContractError
from mara.company_research import research_loop
from mara.agents import DemoModel
import test_evidence_resolution as fixture


class ReadTests(unittest.TestCase):
    def setUp(self):
        self.p={'market':{'facts':[{'id':'own','topic':'ETF exposure','source':'https://example.org/issuer',
            'text':'ETF holdings '+('x'*20000)}]},'analysis':{'zero':0,'flag':False,'missing':None,'comparison':{'fee':.001}}}

    def test_pages_are_exact_scoped_and_hash_pinned(self):
        call={'tool':'evidence_read','arguments':{'fact_id':'own','limit':500}}
        first=read(self.p,call);self.assertEqual(first['offset'],0);self.assertEqual(first['next_offset'],500)
        call['arguments'].update(offset=500)
        with self.assertRaisesRegex(ContractError,'hash'):read(self.p,call)
        call['arguments']['expected_sha256']=first['sha256'];second=read(self.p,call)
        self.assertEqual(second['sha256'],first['sha256']);self.assertEqual(second['offset'],500)
        changed=copy.deepcopy(self.p);changed['market']['facts'][0]['text']+='changed'
        with self.assertRaisesRegex(ContractError,'changed'):read(changed,call)
        call['arguments']['fact_id']='not-delivered'
        with self.assertRaisesRegex(ContractError,'not delivered'):read(self.p,call)

    def test_analysis_never_reads_other_payloads_and_retains_zero_false(self):
        for key,text in [('zero','0'),('flag','false'),('missing','null')]:
            self.assertEqual(read(self.p,{'tool':'analysis_read','arguments':{'path':'/analysis/'+key}})['text'],text)
        for path in ('/profile/goal','/analysis/../profile','/analysis/nonexistent'):
            with self.assertRaises(ContractError):read(self.p,{'tool':'analysis_read','arguments':{'path':path}})
        for args in ({'offset':-1},{'offset':True},{'limit':12001},{'limit':True},{'offset':999999,'expected_sha256':'a'*64}):
            with self.assertRaises(ContractError):read(self.p,{'tool':'analysis_read','arguments':dict(path='/analysis/zero',**args)})

    def test_stage_and_empty_calculation_diagnostics_preserve_gate(self):
        self.p['decision_scope']={'questions':[{'id':'q'}]}
        row={'question_id':'q','status':'unresolved','fact_ids':[],'calculation_paths':[]}
        validate_reviews({'question_reviews':[row]},self.p)
        for path in ('/analysis/zero','/analysis/flag'):
            row['calculation_paths']=[path];validate_reviews({'question_reviews':[row]},self.p)
        row['calculation_paths']=['/analysis/missing']
        with self.assertRaises(QuestionReviewError) as err:validate_reviews({'question_reviews':[row]},self.p)
        self.assertEqual(err.exception.diagnostic['path'],'/analysis/missing')
        self.assertEqual(err.exception.diagnostic['reason_code'],'empty_calculation')
        row['status']='supported';row['calculation_paths']=['/analysis/zero']
        with self.assertRaises(QuestionReviewError) as err:validate_reviews({'question_reviews':[row]},self.p)
        self.assertEqual(err.exception.diagnostic['reason_code'],'before_final_proposal')
        self.p['final_proposal']={'weights':{'CASH':1}};validate_reviews({'question_reviews':[row]},self.p)
        row['calculation_paths']=['/analysis/missing']
        with self.assertRaises(QuestionReviewError):validate_reviews({'question_reviews':[row]},self.p)


class ReadLoopTests(unittest.TestCase):
    setUp=fixture.EvidenceResolutionTests.setUp
    def test_read_receipts_do_not_activate_or_resolve_evidence(self):
        fact=self.m['facts'][0];qid=self.scope['questions'][0]['id']
        class Reader(DemoModel):
            mode='live'
            def complete(inner,role,g,p,c):
                if p['round']==1:return {'reason':'Read existing data','calls':[
                    {'tool':'evidence_read','arguments':{'fact_id':fact['id']},'question_ids':[qid]},
                    {'tool':'analysis_read','arguments':{'path':'/analysis/comparison'},'question_ids':[qid]}]}
                self.assertEqual(p['research_results'][0]['answer']['result']['fact_id'],fact['id'])
                return {'reason':'Read requested scope','calls':[],'stop_reason':'evidence_sufficient'}
        payload={'profile':self.p,'market':copy.deepcopy(self.m),'analysis':{'comparison':{'fee':.001}},'decision_scope':self.scope}
        result=research_loop(self.s,Reader(),'bogle','guide',payload,'read-existing',fixture.DAY,self.lib)
        self.assertEqual(result['market']['facts'],self.m['facts']);self.assertFalse(self.s.events('research_evidence'))
        from mara.research_questions import ledger
        value=ledger(self.s,'read-existing',self.scope)
        self.assertTrue(all(q['state']=='awaiting_analysis_review' for q in value['questions']))
        self.assertEqual(len(self.s.events('research_tool_result')),2)
        self.assertTrue(all(e['body']['fact_id'] is None for e in self.s.events('research_activity')))


class PlanningBoundaryTests(unittest.TestCase):
    setUp=fixture.EvidenceResolutionTests.setUp
    def payload(self,facts=True):return {'profile':self.p,'market':dict(copy.deepcopy(self.m),facts=copy.deepcopy(self.m['facts']) if facts else []),'analysis':{},'decision_scope':self.scope}
    def test_capability_stop_gets_one_bounded_reading_check_with_original_plan_preserved(self):
        fact=self.m['facts'][0];qid=self.scope['questions'][0]['id'];seen=[]
        class Planner(DemoModel):
            mode='live'
            def complete(inner,role,g,p,c):
                seen.append(p)
                if p['round']==1:return {'reason':'Only catalog supplied','calls':[],'stop_reason':'capability_gap'}
                if p['round']==2:
                    self.assertEqual(p['planning_feedback']['code'],'check_readable_payload_before_capability_stop')
                    return {'reason':'Read available scope','calls':[{'tool':'evidence_read','arguments':{'fact_id':fact['id']},'question_ids':[qid]}]}
                return {'reason':'Observed scope remains insufficient','calls':[],'stop_reason':'capability_gap'}
        result=research_loop(self.s,Planner(),'buffett','guide',self.payload(),'bounded-read-check',fixture.DAY,self.lib)
        self.assertEqual(len(seen),3);self.assertEqual(result['research_access']['calls'],1);self.assertEqual(result['research_access']['stop_reason'],'capability_gap')
        self.assertEqual(len(self.s.events('research_planning_feedback')),1);self.assertEqual(len(self.s.events('research_plan')),3)
        self.assertFalse(self.s.events('research_evidence'))
    def test_no_retry_for_sufficient_or_no_data_and_second_capability_stop_is_respected(self):
        for stop,has_facts,expected in [('evidence_sufficient',True,1),('capability_gap',False,1),('capability_gap',True,2)]:
            seen=[]
            class Planner(DemoModel):
                mode='live'
                def complete(inner,role,g,p,c):seen.append(p);return {'reason':'Explicit stop','calls':[],'stop_reason':stop}
            result=research_loop(self.s,Planner(),'buffett','guide',self.payload(has_facts),'stop-'+str(expected)+stop,fixture.DAY,self.lib)
            self.assertEqual(len(seen),expected);self.assertEqual(result['research_access']['calls'],0);self.assertEqual(result['research_access']['extensions'],[])
