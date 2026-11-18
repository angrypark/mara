import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from mara.agents import Agents,DemoModel
from mara.evidence_feedback import validate_output,FeedbackContractError
from mara.company_research import research_loop,CompanyLibrary,ResearchTools
from mara.store import Store
from test_decision import market

class FeedbackRepairTests(unittest.TestCase):
    def test_pending_cannot_close_unanswered_or_skip_returned_request(self):
        p={'market':{'facts':[]},'evidence_feedback':[{'request_id':'pending','requester':'bogle'}, {'request_id':'returned','requester':'bogle','response':{'status':'unavailable'}}, {'request_id':'foreign','requester':'wood'}]}
        r=dict(request_id='returned',status='still_missing',reason='Missing',fact_ids=[])
        q=dict(request_id='pending',status='still_missing',reason='Waiting',fact_ids=[])
        for rows in ([r],[r,q]):validate_output('bogle',{'evidence_assessments':rows},p)
        for rows in ([],[q],[r,r],[r,dict(q,status='incorporated')],[r,dict(q,status='not_relevant')],[r,dict(q,request_id='foreign')],[r,dict(q,request_id='pending-typo')]):
            with self.subTest(rows=rows),self.assertRaises(FeedbackContractError) as caught:validate_output('bogle',{'evidence_assessments':rows},p)
            self.assertEqual(caught.exception.diagnostic['required_response_ids'],['returned'])
            self.assertEqual(caught.exception.diagnostic['pending_request_ids'],['pending'])

    def test_agent_repair_receives_exact_pending_ids(self):
        class Repair(DemoModel):
            def complete(inner,role,guide,p,contract):
                out=super().complete(role,guide,p,contract)
                if p.get('output_feedback'):
                    self.assertEqual(p['output_feedback']['evidence_feedback_error']['pending_request_ids'],['pending'])
                    out['evidence_assessments']=[dict(request_id='pending',status='still_missing',reason='Waiting',fact_ids=[])]
                else:out['evidence_assessments']=[dict(request_id='pending-typo',status='incorporated',reason='Wrong',fact_ids=[])]
                return out
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');self.addCleanup(db.close);s=db.session(db.create_user('fixture'))
            out,_=Agents(s,Repair(),'2026-11-15','run').call('bogle',{'market':market(),'valuation':{'weights':{'CASH':1}},'evidence_feedback':[{'request_id':'pending','requester':'bogle'}]})
            self.assertEqual(out['evidence_assessments'][0]['status'],'still_missing')
            self.assertEqual([x['body']['status'] for x in s.events('agent_validation')],['rejected','accepted'])

    def run_planner(self,plans,error=False):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        db=Store(Path(tmp.name)/'db');self.addCleanup(db.close);s=db.session(db.create_user('fixture'))
        class Planner:
            mode='live';identity={'provider':'fixture'}
            def __init__(inner):inner.inputs=[]
            def complete(inner,role,guide,p,contract):
                inner.inputs.append(copy.deepcopy(p))
                if error:raise RuntimeError('provider unavailable')
                return copy.deepcopy(plans[len(inner.inputs)-1])
        model=Planner();payload={'market':market()};lib=CompanyLibrary(Path(tmp.name)/'library',today=payload['market']['as_of'])
        with patch.object(ResearchTools,'execute',side_effect=AssertionError('No external tool permitted')):out=research_loop(s,model,'evidence','',payload,'run',lib.today,lib)
        return out,s,model

    def test_invalid_plan_repaired_once_before_any_tool_execution(self):
        invalid={'reason':'read filing','calls':[{'tool':'filing_search','arguments':{'symbol':'NVDA','query':'revenue','expected_sha256':'a'*62}}]}
        valid={'reason':'Read existing source','calls':[{'tool':'evidence_read','arguments':{'fact_id':market()['facts'][0]['id']}}]}
        stop={'reason':'Still missing','calls':[]}
        out,s,model=self.run_planner([invalid,valid,stop])
        self.assertEqual(out['research_access']['planning_repairs'],1);self.assertEqual(out['research_access']['calls'],1)
        self.assertIn('expected_sha256',' '.join(model.inputs[1]['planning_feedback']['errors']))
        self.assertEqual(len(s.events('research_tool_failure')),1);self.assertEqual(len(s.events('research_tool_result')),1)
        out,s,model=self.run_planner([invalid,invalid])
        self.assertEqual(len(model.inputs),2);self.assertEqual(out['research_access']['status'],'invalid_plan');self.assertFalse(s.events('research_tool_result'))

    def test_provider_exception_not_retried(self):
        with self.assertRaisesRegex(RuntimeError,'provider unavailable'):self.run_planner([],error=True)

    def test_one_repair_can_cross_base_rounds_but_never_hard_round_limit(self):
        valid={'reason':'Read existing source','calls':[{'tool':'evidence_read','arguments':{'fact_id':market()['facts'][0]['id']}}]}
        invalid={'reason':'bad shape','calls':[{'tool':'filing_search','arguments':{'symbol':'NVDA','query':'revenue','expected_sha256':'a'*62}}]}
        stop={'reason':'Missing','calls':[]}
        out,s,model=self.run_planner([valid,valid,valid,invalid,stop])
        self.assertEqual(len(model.inputs),5)
        self.assertEqual(out['research_access']['extensions'],[{'round':5,'reason':'one_contract_shape_repair'}])
        # The valid stop receipt must survive the subsequent leader/validator
        # ledger boundary, not only the research loop that produced it.
        from mara.research_questions import freeze,ledger
        from mara.contracts import schema,validate,ContractError
        result=ledger(s,'run',freeze({'goal':'fixture'},market()))
        self.assertEqual(result['research_stops'][0]['extensions'],out['research_access']['extensions'])
        def embedded(value):
            if isinstance(value,dict):
                if 'research_stops' in value.get('properties',{}):yield value
                for child in value.values():yield from embedded(child)
            elif isinstance(value,list):
                for child in value:yield from embedded(child)
        for contract in embedded(schema('workbench')):validate(result,contract)
        invalid_result=copy.deepcopy(result)
        invalid_result['research_stops'][0]['extensions'][0]['reason']='unbounded_research'
        with self.assertRaises(ContractError):validate(invalid_result,schema('research-questions'))
        with patch('mara.research_progress.Progress.extend',return_value='test_new_source_progress'):
            out,s,model=self.run_planner([valid]*7+[invalid])
        self.assertEqual(len(model.inputs),8)
        self.assertEqual(out['research_access']['status'],'invalid_plan')
        self.assertEqual(out['research_access']['planning_repairs'],0)
        self.assertEqual(len(s.events('research_tool_result')),7)

    def test_reference_diagnostics_cover_all_citation_fields_without_substitution(self):
        from mara.output_validation import evidence_reference_errors
        p={'market':{'facts':[{'id':'known'}]}}
        out={'evidence_ids':['known','typo'],'facts':['unknown'], 'nested':{'fact_ids':['other']},'explanation':'typo'}
        original=copy.deepcopy(out)
        self.assertEqual(evidence_reference_errors(out,p),[
            {'path':'/evidence_ids/1','undelivered_id':'typo'},
            {'path':'/facts/0','undelivered_id':'unknown'},
            {'path':'/nested/fact_ids/0','undelivered_id':'other'}])
        self.assertEqual(out,original)

    def test_repair_sees_nested_and_top_level_invalid_ids_together(self):
        class Repair(DemoModel):
            def complete(inner,role,guide,p,c):
                out=super().complete(role,guide,p,c)
                if p.get('output_feedback'):
                    self.assertEqual({r['undelivered_id'] for r in p['output_feedback']['evidence_reference_errors']},{'top-typo','assessment-typo'})
                    out['evidence_assessments']=[dict(request_id='pending',status='still_missing',reason='Unverified',fact_ids=[])]
                else:
                    out['evidence_ids'].append('top-typo')
                    out['evidence_assessments']=[dict(request_id='pending',status='still_missing',reason='Waiting',fact_ids=['assessment-typo'])]
                return out
        with tempfile.TemporaryDirectory() as tmp:
            db=Store(Path(tmp)/'db');self.addCleanup(db.close);s=db.session(db.create_user('fixture'))
            out,_=Agents(s,Repair(),'2026-11-15','run').call('wood',{'market':market(),'valuation':{'weights':{'CASH':1}},'evidence_feedback':[{'request_id':'pending','requester':'wood'}]})
            self.assertNotIn('top-typo',out['evidence_ids'])
            self.assertEqual([x['body']['status'] for x in s.events('agent_validation')],['rejected','accepted'])
