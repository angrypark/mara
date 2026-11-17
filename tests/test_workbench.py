import copy
import json
import tempfile
import threading
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from mara import registry
from mara.agents import DemoModel,validate_output
from mara.contracts import schema,validate,validate_workbench,ContractError
from mara.dialogue import Dialogues,DialogueError
from mara.domain import valuation
from mara.engine import Engine,ContextNeedsInput
from mara.knowledge import Knowledge
from mara.store import Store
from mara.workbench import runs,project,run_state

ROOT=Path(__file__).resolve().parent.parent

class WorkbenchTests(unittest.TestCase):
    def test_recovery_status_follows_latest_transition(self):
        events=[{'seq':1,'kind':'failed','body':{'error_type':'CodexError'}}]
        self.assertEqual(run_state(events),'failed')
        events.append({'seq':2,'kind':'recovery','body':{'status':'resuming'}})
        self.assertEqual(run_state(events),'running')
        events.append({'seq':3,'kind':'recovery','body':{'reason':'service restart'}})
        self.assertEqual(run_state(events),'interrupted')
        events.append({'seq':4,'kind':'failed','body':{'error_type':'ValueError'}})
        self.assertEqual(run_state(events),'failed')
        events.append({'seq':5,'kind':'recovery','body':{'status':'resuming'}})
        events.append({'seq':6,'kind':'completed','body':{}})
        self.assertEqual(run_state(events),'completed')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.sqlite3'
        self.db=Store(self.path);self.token=self.db.create_user('alice');self.s=self.db.session(self.token)
        self.e=Engine(self.s,DemoModel())
        self.p=json.loads((ROOT/'examples/profile.json').read_text());self.h=json.loads((ROOT/'examples/holdings.json').read_text());self.m=json.loads((ROOT/'examples/market.json').read_text())
        self.e.set_profile(self.p,'2026-11-14');self.e.set_holdings(self.h)
        self.r=self.e.run('2026-11-14',self.db.publish_market(self.m));self.run_id=self.r['run_id']
        self.manager=Dialogues(self.session,DemoModel)
    def tearDown(self):
        for t in self.manager.workers.values():t.join(5)
        self.db.close();self.tmp.cleanup()
    @contextmanager
    def session(self):
        db=Store(self.path)
        try:yield db.session(self.token)
        finally:db.close()
    def ask(self,role='evidence',message='왜 그렇게 판단했나요?',rid=None):
        body=dict(run_id=self.run_id,agent_id=role,message=message,request_id=rid or uuid.uuid4().hex)
        result=self.manager.start(body)
        self.manager.workers[body['request_id']].join(5)
        return body,result
    def test_projection_contract_lineage_and_historical_records_unchanged(self):
        original=self.s.export();doc=project(self.s,self.run_id);validate_workbench(doc)
        self.assertEqual(doc['run']['status'],'completed');self.assertEqual(len(doc['components']),11)
        self.assertEqual(doc['portfolio']['actual']['nav'],self.r['valuation']['nav'])
        self.assertEqual(next(c for c in doc['components'] if c['id']=='reflection')['status'],'skipped')
        validation=next(c for c in doc['components'] if c['id']=='validation')
        self.assertEqual(len(validation['records']),2);self.assertIn('final_numeric',[b['key'] for b in validation['blocks']])
        self.assertEqual(validation['inputs']['analysis_stage'],'final_validation')
        first=self.s.get(validation['records'][0]['input_id'])['body']['payload']
        self.assertEqual(first['analysis_stage'],'perspective_validation');self.assertNotIn('final_proposal',first)
        perspective=next(c for c in doc['components'] if c['kind']=='perspective')
        self.assertNotIn('perspectives',perspective['inputs']);self.assertEqual(perspective['inputs']['analysis_flow']['perspectives'],'independent; no current peer outputs')
        leader=next(c for c in doc['components'] if c['id']=='leader')
        self.assertEqual(leader['inputs']['analysis_stage'],'proposal_synthesis');self.assertNotIn('final_numeric_check',leader['inputs'])
        self.assertEqual(original,self.s.export())
        self.assertEqual(runs(self.s)[0]['id'],self.run_id)
    def test_partial_needs_input_failed_and_restarted_runs(self):
        class Missing(DemoModel):
            def complete(self,role,*args):
                value=super().complete(role,*args)
                if role=='context':value['missing']=['자금 사용 시점을 알려주세요.']
                return value
        e=Engine(self.s,Missing())
        with self.assertRaises(ContextNeedsInput):e.run('2026-11-14',self.db.publish_market(self.m),revision_reason='context')
        run_id=runs(self.s)[0]['id'];doc=project(self.s,run_id)
        self.assertEqual(doc['run']['status'],'needs_input');self.assertIsNone(doc['portfolio'])
        self.assertEqual(doc['components'][0]['status'],'needs_input');self.assertEqual(doc['components'][1]['status'],'pending')
        class Broken(DemoModel):
            def complete(self,role,*args):
                if role=='evidence':raise RuntimeError('failed')
                return super().complete(role,*args)
        with self.assertRaises(RuntimeError):Engine(self.s,Broken()).run('2026-11-14',self.db.publish_market(self.m),revision_reason='failure')
        doc=project(self.s,runs(self.s)[0]['id']);self.assertEqual(doc['components'][1]['status'],'failed');self.assertEqual(doc['components'][0]['status'],'completed')
        start=self.s.latest('run_started');rid=uuid.uuid4().hex;self.s.append('run_started',start['body'],'2026-11-14',rid)
        self.s.lock(rid);self.s.recover('restart','2026-11-14');self.assertEqual(project(self.s,rid)['run']['status'],'interrupted')
    def test_previously_recovered_context_question_is_not_displayed_as_generic_failure(self):
        rid=uuid.uuid4().hex;start=self.s.latest('run_started')['body'];self.s.append('run_started',start,'2026-11-14',rid)
        original_input=next(e for e in self.s.events('agent_input') if e['body']['role']=='context')
        source=self.s.append('agent_input',original_input['body'],'2026-11-14',rid)
        value={'summary':'Need context','constraints':[],'missing':['Confirm funding date']}
        output=self.s.append('agent_output',{'role':'context','input_id':source,'output':value},'2026-11-14',rid)
        failed=self.s.append('failed',{'error_type':'ValueError'},'2026-11-14',rid)
        self.assertEqual(project(self.s,rid)['run']['status'],'failed')
        self.s.append('onboarding_job',{'status':'needs_input','context_output_id':output},'2026-11-14')
        original=self.s.export();doc=project(self.s,rid)
        self.assertEqual(doc['run']['status'],'needs_input');self.assertEqual(runs(self.s)[0]['status'],'needs_input')
        self.assertEqual(doc['components'][0]['status'],'needs_input');self.assertEqual(self.s.get(failed)['body']['error_type'],'ValueError')
        self.assertEqual(original,self.s.export())
    def test_unknown_version_refs_weights_and_extra_agent_fields_rejected(self):
        doc=project(self.s,self.run_id)
        for mutate in [lambda d:d.update(schema_version='mara.workbench/2.0.0'),lambda d:d['edges'].append({'from':'unknown','to':'leader','label':'bad'}),lambda d:d['components'][0]['source_ids'].append('invented'),lambda d:d['components'].append(d['components'][0]),lambda d:d['components'][2]['output'].update(weights={'CASH':2})]:
            bad=copy.deepcopy(doc);mutate(bad)
            with self.assertRaises(ValueError):validate_workbench(bad)
        c=doc['components'][0];bad=dict(c['output'],schema_version='999')
        with self.assertRaises(ContractError):validate_output('context',bad,c['inputs'])
        for mutate in [lambda d:d.update(portfolio={}),lambda d:d['components'][0].update(output=None,status='completed'),
                       lambda d:d['components'][0].update(output={'unexpected':True}),
                       lambda d:d['components'][0]['blocks'].append({'key':'bad','title':'bad','kind':'weights','value':'not-a-map'}),
                       lambda d:d['portfolio']['proposal'].update(action='defer',eligibility='review_now')]:
            bad=copy.deepcopy(doc);mutate(bad)
            with self.assertRaises(ContractError):validate_workbench(bad)
    def test_catalogue_extension_runs_and_renders_without_engine_changes(self):
        extra=dict(registry.agent('buffett'),id='research_test',label='Synthetic research perspective')
        self.m['research']={'schema_version':'mara.research/1.0.0','selection':{},'budget':{},'collected_at':'2026-11-14T12:00:00+00:00','calls':[]}
        with patch.object(registry,'REGISTRY',registry.REGISTRY+[extra]):
            result=self.e.run('2026-11-14',self.db.publish_market(self.m),revision_reason='extension')
            doc=project(self.s,result['run_id'])
            self.assertIn('research_test',result['perspectives']);self.assertEqual(len(doc['components']),12)
            c=next(c for c in doc['components'] if c['id']=='research_test');self.assertEqual(c['kind'],'perspective')
            self.assertTrue(any(e['from']=='research_test' and e['to']=='validation' for e in doc['edges']))
        # Recorded catalogue remains visible after plugin removal.
        self.assertEqual(len(project(self.s,result['run_id'])['components']),12)
    def test_all_roles_two_turns_persist_and_never_mutate_proposal(self):
        original_actual=self.s.latest('actual');original_completed=self.s.latest('completed')
        for role in [a['id'] for a in registry.catalogue()]:
            self.ask(role);self.ask(role,'앞선 답변에서 모르는 점을 알려주세요.')
            history=Dialogues(self.session,DemoModel).read(self.run_id,role)
            self.assertEqual(len(history['messages']),4);self.assertFalse(history['pending'])
        self.assertEqual(original_actual,self.s.latest('actual'));self.assertEqual(original_completed,self.s.latest('completed'))
        requests=self.s.events('dialogue_request');last=requests[-1]['body']
        self.assertEqual(len(last['context']['history']),2);self.assertEqual(last['context']['role'],'evaluator')

    def test_dialogue_retains_original_numeric_context_and_citation_uncertainty(self):
        self.ask('validation');self.ask('validation','그 수치의 근거는 무엇인가요?')
        request=self.s.events('dialogue_request')[-1]['body'];context=request['context']
        source=self.s.get(self.s.get(request['source_output_id'])['body']['input_id'])['body']['payload']
        for field in ('profile','actual','valuation','previous','performance','knowledge','perspectives','numeric_checks','final_numeric_check'):
            self.assertEqual(context['role_input'][field],source[field])
        self.assertTrue(context['history'][-1]['uncertainties']);self.assertEqual(context['history'][-1]['evidence_ids'],['demo-1'])

    def test_rejected_role_output_remains_inspectable_as_failure_not_valid_result(self):
        class Invalid(DemoModel):
            def complete(self,role,*args):
                value=super().complete(role,*args)
                if role=='evidence':value['unexpected']=True
                return value
        with self.assertRaises(ContractError):Engine(self.s,Invalid()).run('2026-11-14',self.db.publish_market(self.m),revision_reason='invalid')
        doc=project(self.s,runs(self.s)[0]['id']);c=next(c for c in doc['components'] if c['id']=='evidence')
        self.assertIsNone(c['output']);self.assertEqual(c['status'],'failed');self.assertIn('contract_error',[b['key'] for b in c['blocks']])

    def test_legacy_defer_is_projected_consistently_without_rewriting(self):
        body=copy.deepcopy(self.r);body.pop('event_id');body['run_id']=uuid.uuid4().hex;body['proposal'].update(action='defer',eligibility='review_now')
        eid=self.s.append('completed',body,'2026-11-14',body['run_id'])
        doc=project(self.s,body['run_id']);self.assertEqual(doc['portfolio']['proposal']['eligibility'],'blocked')
        self.assertEqual(self.s.get(eid)['body']['proposal']['eligibility'],'review_now');self.assertTrue(doc['extensions']['projection_corrections'])
    def test_legacy_output_links_to_the_schema_that_accepts_it(self):
        body=copy.deepcopy(self.r);body.pop('event_id');body['run_id']=uuid.uuid4().hex
        for perspective in body['perspectives'].values():
            perspective.pop('decision_basis');perspective.pop('changes_since_previous')
        self.s.append('completed',body,'2026-11-14',body['run_id'])
        doc=project(self.s,body['run_id'])
        for component in doc['components']:
            if component['output'] is not None:
                validate(component['output'],schema(component['contract'].rsplit('/',1)[-1]))
            if component['kind']=='perspective':
                self.assertEqual(component['status'],'completed')
                self.assertEqual(component['contract'],'/api/contracts/legacy-agent-perspective')
    def test_conversation_run_agent_tenant_isolation(self):
        self.ask('buffett','Alice private question')
        self.assertEqual(self.manager.read(self.run_id,'marks')['messages'],[])
        revised=self.e.run('2026-11-14',self.db.publish_market(self.m),revision_reason='new run')
        self.assertEqual(self.manager.read(revised['run_id'],'buffett')['messages'],[])
        token=self.db.create_user('bob')
        @contextmanager
        def other():
            db=Store(self.path)
            try:yield db.session(token)
            finally:db.close()
        other_manager=Dialogues(other,DemoModel)
        with self.assertRaises(PermissionError):other_manager.read(self.run_id,'buffett')
        with self.assertRaises(PermissionError):other_manager.start(dict(run_id=self.run_id,agent_id='buffett',request_id=uuid.uuid4().hex,message='get it'))
        with self.assertRaises(PermissionError):self.manager.read(self.run_id,'unknown')
    def test_duplicate_concurrent_and_invalid_output(self):
        gate=threading.Event()
        class Wait(DemoModel):
            def complete(self,*args):gate.wait(3);return super().complete(*args)
        self.manager.model_factory=Wait
        body=dict(run_id=self.run_id,agent_id='context',request_id=uuid.uuid4().hex,message='waiting')
        self.manager.start(body);self.assertTrue(self.manager.start(body)['duplicate'])
        with self.assertRaises(DialogueError):self.manager.start(dict(body,message='changed'))
        with self.assertRaises(DialogueError):self.manager.start(dict(body,request_id=uuid.uuid4().hex))
        gate.set();self.manager.workers[body['request_id']].join(5)
        self.assertEqual(len(self.manager.read(self.run_id,'context')['messages']),2)
        class Bad(DemoModel):
            def complete(self,*args):return {'answer':'fake','evidence_ids':['invented'],'uncertainties':[],'next_questions':[]}
        self.manager.model_factory=Bad;self.ask('context')
        self.assertEqual(self.manager.read(self.run_id,'context')['messages'][-1]['status'],'failed')
        self.assertNotIn('fake',self.manager.read(self.run_id,'context')['messages'][-1]['text'])
    def test_recovery_marks_pending_and_does_not_call_model(self):
        self.s.append('dialogue_request',{'request_id':uuid.uuid4().hex,'agent_id':'context','message':'unfinished'},'2026-11-14',self.run_id)
        self.manager.recover();self.manager.recover()
        history=self.manager.read(self.run_id,'context');self.assertFalse(history['pending']);self.assertEqual(len(history['messages']),2)
        self.assertEqual(history['messages'][-1]['status'],'interrupted')
    def test_leader_defer_is_never_ready_even_if_validation_passes(self):
        class Defer(DemoModel):
            def complete(self,role,*args):
                out=super().complete(role,*args)
                if role=='leader':out['action']='defer'
                return out
        result=Engine(self.s,Defer()).run('2026-11-14',self.db.publish_market(self.m),revision_reason='defer')
        self.assertEqual(result['proposal']['eligibility'],'blocked')
    def test_expired_facts_stop_live_before_model_call(self):
        class Live(DemoModel):mode='live'
        token=self.db.create_user('live');s=self.db.session(token);e=Engine(s,Live());e.set_profile(self.p,'2026-11-14');e.set_holdings(self.h)
        m=copy.deepcopy(self.m);m.pop('synthetic',None)
        for f in m['facts']:f['valid_until']='2026-11-13'
        with self.assertRaisesRegex(ValueError,'currently valid'):e.run('2026-11-14',self.db.publish_market(m))
        self.assertEqual(s.events('agent_input'),[]);self.assertEqual(s.events('completed'),[])
    def test_old_merged_foreign_cash_is_explicitly_rejected(self):
        h=copy.deepcopy(self.h);h['base_currency']='KRW';h['cash_components']={'KRW':0,'USD':100};m=copy.deepcopy(self.m);m['base_currency']='KRW'
        with self.assertRaisesRegex(ValueError,'Foreign cash'):valuation(h,m)
    def test_protected_expiry_visible_for_revalidation_and_not_deleted(self):
        k=Knowledge(self.s);ref=self.s.latest('completed')['id']
        eid=k.apply({'action':'add','reason':'risk','text':'rare loss scenario','topic':'risk','condition':'stress','perspective':'all','category':'rare_risk','roles':['*'],'refs':[ref],'valid_until':'2026-11-14','priority':10},'2026-11-14')
        k.prune('2026-11-21');items=k.retrieve('2026-11-21','leader')['items'];self.assertEqual(len(items),1);self.assertTrue(items[0]['needs_revalidation']);self.assertEqual(self.s.get(eid)['body']['status'],'active')

if __name__=='__main__':unittest.main()
