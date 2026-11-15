import copy
import json
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from mara.agents import DemoModel,Agents
from mara.company_research import CompanyLibrary,ResearchTools,owner_value,research_loop,quality
from mara.decision_actions import DecisionActions
from mara.dialogue import DialogueError
from mara.engine import Engine
from mara.evaluation import evaluate_report,score
from mara.contracts import validate,schema,ContractError
from mara.store import Store
from mara.workbench import project
from test_research import financial
from mara.research_sources import sec_financials

ROOT=Path(__file__).resolve().parent.parent
DAY='2026-11-14'


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db.sqlite3'
        self.db=Store(self.path);self.token=self.db.create_user('alice');self.s=self.db.session(self.token)
        self.e=Engine(self.s,DemoModel())
        for name in ('profile','holdings','market'):setattr(self,name,json.loads((ROOT/('examples/'+name+'.json')).read_text()))
        self.e.set_profile(self.profile,DAY);self.e.set_holdings(self.holdings)
        self.r=self.e.run(DAY,self.db.publish_market(self.market))
        self.actions=DecisionActions(self.session,DemoModel)

    def tearDown(self):
        if self.actions.thread:self.actions.thread.join(5)
        self.db.close();self.tmp.cleanup()

    @contextmanager
    def session(self):
        db=Store(self.path)
        try:yield db.session(self.token)
        finally:db.close()

    def dialogue(self,role='buffett',scope='reasoning'):
        rid=uuid.uuid4().hex
        output=next(e for e in self.s.events('agent_output') if e['run_id']==self.r['run_id'] and e['body']['role']==role)
        self.s.append('dialogue_request',{'request_id':rid,'agent_id':role,'message':'Reconsider concentration',
            'source_output_id':output['id']},DAY,self.r['run_id'])
        self.s.append('dialogue_result',{'request_id':rid,'agent_id':role,'status':'completed','answer':{
            'answer':'Proposed change','evidence_ids':[],'uncertainties':[],'next_questions':[],
            'proposed_change':{'scope':scope,'summary':'Reconsider concentration','reason':'Compare the alternative explicitly'}}},DAY,self.r['run_id'])
        return rid

    def test_frozen_dialogue_revision_revalidates_all_and_does_not_mutate_actual_or_profile(self):
        class DownstreamResponse(DemoModel):
            def complete(self,role,*args):
                out=super().complete(role,*args)
                if role in ('validation','leader'):
                    out['change_response']={'status':'partial','reason':'Downstream review preserves the amendment response.'}
                return out
        self.actions=DecisionActions(self.session,DownstreamResponse)
        before=self.s.get(self.r['event_id']);actual=self.s.events('actual');profile=self.s.events('profile')
        rid=self.dialogue();body={'action':'revise','run_id':self.r['run_id'],'request_id':uuid.uuid4().hex,'dialogue_request_id':rid}
        self.actions.start(body);self.actions.thread.join(10)
        status=self.s.latest('decision_action_result')['body'];self.assertEqual(status['status'],'completed')
        new=self.s.latest('completed')['body'];self.assertNotEqual(new['run_id'],self.r['run_id'])
        self.assertEqual(new['market_id'],self.r['market_id']);self.assertEqual(self.s.get(self.r['event_id']),before)
        self.assertEqual(self.s.events('actual'),actual);self.assertEqual(self.s.events('profile'),profile)
        inputs=[e['body'] for e in self.s.events('agent_input') if e['run_id']==new['run_id']]
        target=next(e for e in inputs if e['role']=='buffett')['payload'];self.assertEqual(target['adopted_dialogue_change']['dialogue_request_id'],rid)
        self.assertFalse(any('adopted_dialogue_change' in e['payload'] for e in inputs if e['role']=='marks'))
        self.assertEqual(len([e for e in inputs if e['role']=='validation']),2)
        self.assertTrue(next(e for e in inputs if e['role']=='evidence')['payload']['context_analysis'])
        doc=project(self.s,new['run_id']);self.assertEqual(doc['extensions']['lineage']['change_response']['status'],'rejected')
        self.assertTrue(doc['extensions']['evaluation']);self.assertTrue(self.actions.start(body)['duplicate'])
        self.assertEqual(doc['portfolio']['validation']['final_critique']['change_response']['status'],'partial')
        self.assertEqual(doc['portfolio']['proposal']['change_response']['status'],'partial')
        next_market=copy.deepcopy(self.market);next_market['as_of']='2026-11-21'
        for quote in next_market['prices'].values():quote.update(observed_at='2026-11-21',known_at='2026-11-21')
        weekly=Engine(self.s,DemoModel()).run('2026-11-21',self.db.publish_market(next_market))
        self.assertEqual(project(self.s,weekly['run_id'])['portfolio']['previous']['proposal']['change_response']['status'],'partial')
        with self.assertRaises(DialogueError):self.actions.start(dict(body,request_id=uuid.uuid4().hex))

    def test_settings_are_not_reasoning_and_cross_tenant_references_fail(self):
        rid=self.dialogue(scope='settings')
        with self.assertRaises(DialogueError):self.actions.start({'action':'revise','run_id':self.r['run_id'],'request_id':uuid.uuid4().hex,'dialogue_request_id':rid})
        other=self.db.session(self.db.create_user('bob'))
        with self.assertRaises(PermissionError):project(other,self.r['run_id'])

    def test_stage_output_pins_dialogue_and_invalid_stage_never_looks_completed(self):
        from mara.dialogue import Dialogues
        doc=project(self.s,self.r['run_id']);review=next(x for x in doc['extensions']['flow'] if x['id']=='review')
        manager=Dialogues(self.session,DemoModel)
        rid=uuid.uuid4().hex;manager.start({'run_id':self.r['run_id'],'agent_id':'validation','request_id':rid,'message':'Explain this stage','source_output_id':review['snapshot']['source_output_id']});manager.workers[rid].join(5)
        req=self.s.latest('dialogue_request')['body'];self.assertEqual(req['context']['role_input']['analysis_stage'],'perspective_validation')
        class Bad(DemoModel):
            def complete(self,role,*args):
                out=super().complete(role,*args)
                if role=='validation':out['unknown']='invalid'
                return out
        with self.assertRaises(ValueError):Engine(self.s,Bad()).run(DAY,self.r['market_id'],revision_reason='invalid stage fixture')
        failed=project(self.s,self.s.latest('run_started')['run_id']);step=next(x for x in failed['extensions']['flow'] if x['id']=='review')
        self.assertEqual(step['status'],'failed');self.assertIsNone(step['snapshot']['output'])

    def test_automatic_evaluation_restart_recovers_retry_state(self):
        self.s.append('evaluation_status',{'status':'running','completed_id':self.r['event_id'],'rubric_hash':'interrupted'},DAY,self.r['run_id'])
        self.actions.recover();doc=project(self.s,self.r['run_id']);self.assertEqual(next(c for c in doc['components'] if c['id']=='evaluator')['status'],'failed')
        evaluate_report(self.s,DemoModel(),self.r['event_id']);self.assertEqual(self.s.latest('evaluation_status')['body']['status'],'completed')

    def test_last_validation_collection_recomputes_input_and_final_gate(self):
        from mara.decision import POLICY,asset_requirements
        from mara.research import compact_market
        class LiveFixture(DemoModel):mode='live'
        s=self.db.session(self.db.create_user('late-evidence-fixture'));m=copy.deepcopy(self.market);m.pop('synthetic',None)
        m['coverage']={'proposal_policy':POLICY};m['assets']['BROAD'].update(kind='STOCK',asset_class='equity')
        fin=sec_financials(financial(),DAY)
        filing={'symbol':'BROAD','cik':1,'filings':[{'form':'10-K','filed':'2026-02-01','accession':'0000000001-26-000001','url':'https://www.sec.gov/Archives/edgar/data/1/000000000126000001/report.htm'}]}
        facts=[{'id':'research-'+tool+'-BROAD','topic':'fixture','research_tool':tool,'text':json.dumps(v),'source':'https://data.sec.gov','published_at':'2026-02-01','known_at':DAY,'valid_until':DAY,'uncertainty':'fixture'} for tool,v in [('sec_financials',fin),('sec_filings',filing)]]
        def tool(session,model,role,guide,payload,run_id,as_of,library):
            if role=='validation' and payload.get('final_proposal'):
                payload['market']['facts'].extend(facts)
                for f in facts:session.append('research_evidence',{'role':role,'fact':f},as_of,run_id)
            return payload
        e=Engine(s,LiveFixture(),object());e.set_profile(self.profile,DAY);h=copy.deepcopy(self.holdings);h['positions'].pop('BOND',None);e.set_holdings(h)
        with patch('mara.company_research.research_loop',tool):r=e.run(DAY,self.db.publish_market(m))
        final=next(e['body']['payload'] for e in reversed(s.events('agent_input')) if e['body']['role']=='validation')
        self.assertFalse(final['final_numeric_check']['missing']);self.assertFalse(r['validation']['final_numeric']['missing'])
        m['facts'].extend(facts);m['research']={'schema_version':'fixture','selection':{},'budget':{},'collected_at':DAY,'calls':[]}
        self.assertFalse(asset_requirements(compact_market(m,'validation'),'BROAD')['missing'])

    def test_evaluation_is_frozen_deterministic_and_does_not_override_veto(self):
        current=self.s.latest('report_evaluation')['body'];validate(current,schema('evaluation'))
        count=len(self.s.events('report_evaluation'));evaluate_report(self.s,DemoModel(),self.r['event_id']);self.assertEqual(len(self.s.events('report_evaluation')),count)
        inp=next(e['body']['payload'] for e in self.s.events('agent_input') if e['body']['role']=='evaluator')
        out=copy.deepcopy(current['output'])
        for row in out['criteria']:row.update(score=4,evidence_paths=['/report/proposal/rationale'])
        self.assertEqual(score(out,inp)['total'],100)
        inp['report']['proposal']['eligibility']='blocked';self.assertTrue(score(out,inp)['proposal_blocked'])
        out['criteria'][0]['evidence_paths']=['/report/invented'];self.assertRaises(ContractError,score,out,inp)
        out['criteria'][0]['evidence_paths']=['/profile']
        with self.assertRaisesRegex(ContractError,'/profile/goal'):score(out,inp)
        out['criteria'][0]=copy.deepcopy(out['criteria'][1]);self.assertRaises(ContractError,score,out,inp)

    def test_prior_run_tools_cannot_collect_today_or_read_later_dossiers(self):
        lib=CompanyLibrary(Path(self.tmp.name)/'library',today='2026-11-16')
        p={'market':self.market,'profile':self.profile};model=DemoModel();model.mode='live'
        with patch.object(lib,'universe',side_effect=AssertionError('Network forbidden')):
            out=research_loop(self.s,model,'buffett','guide',p,self.r['run_id'],DAY,lib)
        self.assertEqual(out['research_access']['status'],'frozen_snapshot')
        self.assertRaises(ValueError,lib.collect,['AAPL'],DAY)

    def test_evaluator_repairs_whole_object_reference_with_specific_feedback(self):
        payload=next(e['body']['payload'] for e in self.s.events('agent_input') if e['body']['role']=='evaluator')
        class Repair(DemoModel):
            def complete(self,role,guide,p,contract):
                out=super().complete(role,guide,p,contract)
                feedback=p.get('output_feedback')
                if feedback:
                    assert '/profile/goal' in feedback['validation_error']
                    out['criteria'][0].update(score=1,evidence_paths=['/profile/goal'])
                else:out['criteria'][0].update(score=1,evidence_paths=['/profile'])
                return out
        output,_=Agents(self.s,Repair(),DAY,self.r['run_id']).call('evaluator',payload)
        self.assertEqual(output['criteria'][0]['evidence_paths'],['/profile/goal'])
        self.assertEqual(self.s.latest('agent_validation')['body']['attempt'],2)

    def test_tool_facts_reach_synthesis_validation_and_quality_evaluator(self):
        class Reader(DemoModel):
            mode='live'
            def complete(self,role,guide,p,c):
                if c.get('$id')=='urn:mara:research-plan:1.0.0':return {'reason':'fixture','calls':[]}
                return super().complete(role,guide,p,c)
        # One exact, signed fact supplied by the planner's tool, no opinion sharing.
        fact=dict(self.market['facts'][0],id='fresh-tool-fact')
        def tool(s,model,role,guide,payload,run_id,as_of,library):
            if role=='buffett':
                payload['market']['facts'].append(fact)
                s.append('research_evidence',{'role':role,'fact':fact},as_of,run_id)
            return payload
        # Use a separate live tenant; the synthetic integration data is explicitly made non-demo.
        s=self.db.session(self.db.create_user('live-fixture'));e=Engine(s,Reader(),object())
        e.set_profile(self.profile,DAY);e.set_holdings(self.holdings);m=copy.deepcopy(self.market);m.pop('synthetic',None)
        with patch('mara.company_research.research_loop',tool):r=e.run(DAY,self.db.publish_market(m))
        for event in s.events('agent_input'):
            if event['body']['role'] in ('leader','validation','evaluator'):
                self.assertIn('fresh-tool-fact',{f['id'] for f in event['body']['payload']['market']['facts']})
        self.assertIn('fresh-tool-fact',{f['id'] for f in project(s,r['run_id'])['sources']})

    def test_batch_200_checkpoints_resume_pages_and_unknown_company(self):
        lib=CompanyLibrary(Path(self.tmp.name)/'library',today=DAY)
        universe=[{'symbol':'C'+str(i),'name':'Company '+str(i),'cik':1} for i in range(200)]
        class Archive:
            def get(self,url):
                if 'submissions' in url:
                    raw={'cik':1,'name':'Fixture','tickers':[x['symbol'] for x in universe],
                        'filings':{'recent':{'form':['10-K'],'filingDate':['2026-02-01'],'accessionNumber':['0000000001-26-000001'],'primaryDocument':['report.htm'],'reportDate':['2025-12-31']}}}
                else:raw=financial()
                return json.dumps(raw).encode(),{'retrieved_at':DAY+'T12:00:00+00:00','source':url,'sha256':'a'*64}
        with patch.object(lib,'universe',return_value=(universe,'fixture')),patch.object(lib,'archive',return_value=Archive()):
            names=[r['symbol'] for r in universe];result=lib.collect(names,DAY);self.assertEqual(result['completed'],200)
            again=lib.collect(names,DAY);self.assertTrue(all(x['status']=='cached' for x in again['receipts']))
            runner=ResearchTools(lib,self.s,self.r['run_id'],DAY)
            a=runner.execute('buffett',{'tool':'compare','arguments':{'symbols':names,'offset':180,'limit':20}},self.market)
            self.assertEqual(len(a['result']['companies']),20);self.assertIsNone(a['result']['next_offset'])
            self.market['assets']['C0']=dict(self.market['assets']['BROAD'],kind='STOCK',asset_class='equity')
            self.market['prices']['C0']=dict(self.market['prices']['BROAD'])
            from mara.decision import asset_requirements
            self.assertTrue(asset_requirements(self.market,'C0')['missing'])
            runner.execute('buffett',{'tool':'company','arguments':{'symbol':'C0'}},self.market)
            self.assertFalse(asset_requirements(self.market,'C0')['missing'])
            # A ticker or source-identity mismatch cannot borrow another firm's evidence.
            wrong=copy.deepcopy(self.market)
            for f in wrong['facts']:
                if f.get('company_identity'):f['company_identity']['symbol']='C1'
            self.assertTrue(asset_requirements(wrong,'C0')['missing'])
        self.assertIsNone(lib.latest('C0','2026-11-13'));self.assertRaises(ValueError,lib.collect,names+['C200'],DAY)

    def test_per_share_sensitivity_and_period_matching(self):
        q=quality(sec_financials(financial(),DAY));self.assertEqual(q['annual_comparison'][0]['fcf_proxy_usd'],27)
        a={'owner_earnings_per_share':4,'currency':'USD','earnings_period':'FY2025','share_basis':'diluted split-adjusted analyst assumption',
            'normalization':'fixture: normalized owner earnings, not raw CFO','price':50,'price_as_of':DAY,'source_ids':['source'],
            'margin_of_safety':.2,'scenarios':[{'name':name,'growth':g,'discount':.1,'terminal_growth':.02,'years':5,'reason':'explicit scenario'} for name,g in [('bear',0),('base',.05),('bull',.1)]]}
        r=owner_value(a,{'source'},DAY);values=[x['value_per_share'] for x in r['scenarios']];self.assertEqual(values,sorted(values))
        self.assertAlmostEqual(r['scenarios'][1]['buy_ceiling'],values[1]*.8)
        bad=copy.deepcopy(a);bad['scenarios'][0]['terminal_growth']=.1;self.assertRaises(ValueError,owner_value,bad,{'source'},DAY)
        bad=copy.deepcopy(a);bad['currency']='KRW';self.assertRaises(ValueError,owner_value,bad,{'source'},DAY)
        bad=copy.deepcopy(a);bad['source_ids']=['invented'];self.assertRaises(ValueError,owner_value,bad,{'source'},DAY)

    def test_recent_metric_tag_wins_without_summing_aliases(self):
        from test_research import observation
        data=financial();data['facts']['us-gaap']['RevenueFromContractWithCustomerExcludingAssessedTax']={'units':{'USD':[observation(9,end='2021-12-31',start='2021-01-01',filed='2022-02-01')]}}
        result=sec_financials(data,DAY);series=result['metrics']['revenue']
        self.assertEqual(len(series),1);self.assertEqual(series[0]['tag'],'Revenues');self.assertEqual(series[0]['observations'][0]['value'],100)

    def test_active_evidence_cap_archives_original_and_shape_failure_is_local(self):
        lib=CompanyLibrary(Path(self.tmp.name)/'library',today=DAY);runner=ResearchTools(lib,self.s,self.r['run_id'],DAY)
        for i in range(10):
            fact=dict(self.market['facts'][0],id='bounded-'+str(i),text='x'*12000)
            runner.activate('buffett',fact,self.market)
        active=[e['body']['fact'] for e in self.s.events('research_evidence') if e['run_id']==self.r['run_id']]
        self.assertLessEqual(sum(len(json.dumps(f,ensure_ascii=False)) for f in active),80000);self.assertEqual(len(active),6)
        class Invalid:
            def get(self,url):return b'[]',{}
        with patch.object(lib,'archive',return_value=Invalid()):
            rows,mode=lib.universe();self.assertTrue(rows);self.assertIn('partial',mode)


if __name__=='__main__':unittest.main()
