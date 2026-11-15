"""Output repair boundaries and evidence provenance, using synthetic inputs only."""
import copy
import uuid
import unittest
from contextlib import contextmanager
from datetime import date
import test_system as system_fixture
import test_onboarding_risk as setup_fixture
from mara.agents import Agents, DemoModel
from mara.engine import Engine,ContextNeedsInput
from mara.output_validation import AgentOutputError,failed_job_diagnostic
from mara.workbench import project,runs
from mara.dialogue import Dialogues
from mara.reporting import present


class RecoveryTests(unittest.TestCase):
    setUp=system_fixture.Harness.setUp
    tearDown=system_fixture.Harness.tearDown
    initial=system_fixture.Harness.initial
    week=system_fixture.Harness.week

    def test_broker_record_id_is_repaired_once_with_originals_and_independence(self):
        class Correct(DemoModel):
            seen=[]
            def complete(model,role,guide,p,contract):
                Correct.seen.append((role,copy.deepcopy(p)))
                value=super().complete(role,guide,p,contract)
                if role=='buffett' and 'output_feedback' not in p:value['evidence_ids']=['broker-record-id']
                return value
        self.e.model=Correct();actual=self.s.latest('actual');r=self.initial()
        calls=[p for role,p in Correct.seen if role=='buffett']
        self.assertEqual(len(calls),2);self.assertEqual(calls[1]['output_feedback']['code'],'market_evidence_reference')
        for key in calls[0]:self.assertEqual(calls[0][key],calls[1][key])
        self.assertNotIn('perspectives',calls[1]);self.assertEqual(calls[0]['citation_scope']['market_fact_ids'],['demo-1'])
        marks=[p for role,p in Correct.seen if role=='marks'][0];self.assertNotIn('output_feedback',marks)
        checks=[e['body'] for e in self.s.events('agent_validation') if e['body']['role']=='buffett']
        self.assertEqual([x['status'] for x in checks],['rejected','accepted'])
        self.assertEqual(self.s.get(checks[0]['output_id'])['body']['output']['evidence_ids'],['broker-record-id'])
        self.assertEqual(r['perspectives']['buffett']['evidence_ids'],['demo-1']);self.assertEqual(self.s.get(actual['id']),actual)
        c=next(c for c in project(self.s,r['run_id'])['components'] if c['id']=='buffett')
        self.assertEqual(c['output']['evidence_ids'],['demo-1']);self.assertEqual(len(c['records']),2)
        self.assertEqual(len(c['extensions']['output_validation']),2)
        with self.assertRaises(PermissionError):self.other.get(checks[0]['output_id'])

    def test_persistent_invalid_reference_stops_after_two_and_is_not_adopted(self):
        class Bad(DemoModel):
            seen=[]
            def complete(model,role,*args):
                Bad.seen.append(role);value=super().complete(role,*args)
                if role=='buffett':value['evidence_ids']=['private-invalid-id']
                return value
        self.e.model=Bad()
        with self.assertRaises(AgentOutputError) as caught:self.initial()
        self.assertEqual(Bad.seen.count('buffett'),2);self.assertNotIn('marks',Bad.seen)
        self.assertNotIn('private-invalid-id',str(caught.exception));self.assertIn('Warren Buffett',str(caught.exception))
        self.assertFalse(self.s.events('completed'));self.assertFalse(self.s.events('proposal'))
        d=project(self.s,runs(self.s)[0]['id']);c=next(c for c in d['components'] if c['id']=='buffett')
        self.assertIsNone(c['output']);self.assertEqual(c['source_ids'],[]);self.assertEqual(c['status'],'failed')
        self.assertIn('시장 근거',d['run']['message']);self.assertEqual(self.s.latest('failed')['body']['output_validation']['code'],'market_evidence_reference')

    def test_provider_failure_is_not_retried_or_logged(self):
        class Provider(DemoModel):
            count=0
            def complete(model,*args):Provider.count+=1;raise RuntimeError('provider-secret-text')
        self.e.model=Provider()
        with self.assertRaises(RuntimeError):self.initial()
        self.assertEqual(Provider.count,1);self.assertNotIn('provider-secret-text',str(self.s.latest('failed')))
        self.assertFalse(self.s.events('agent_validation'))
        d=project(self.s,runs(self.s)[0]['id'])
        self.assertNotIn('응답 검증 실패',d['run']['message'])
        self.assertNotIn('provider-secret-text',str(d))

    def test_qualitative_rejection_and_personal_questions_are_not_repaired(self):
        class Missing(DemoModel):
            calls=0
            def complete(model,role,*args):
                Missing.calls+=1;v=super().complete(role,*args)
                if role=='context':v['missing']=['현금 필요를 확인해주세요.']
                return v
        self.e.model=Missing()
        with self.assertRaises(ContextNeedsInput):self.initial()
        self.assertEqual(Missing.calls,1)
        class Risk(DemoModel):
            feedback_seen=False
            def complete(model,role,guide,p,contract):
                Risk.feedback_seen|='output_feedback' in p;v=super().complete(role,guide,p,contract)
                if role=='validation':v.update(qualitative_pass=False,reason='자료 부족',issues=['미확인 위험'])
                return v
        self.e.model=Risk();r=self.initial()
        self.assertFalse(Risk.feedback_seen);self.assertEqual(r['proposal']['eligibility'],'blocked')

    def test_provider_failure_during_repair_is_separate_from_prior_rejection(self):
        class Interrupted(DemoModel):
            calls=0
            def complete(model,role,guide,p,contract):
                v=super().complete(role,guide,p,contract)
                if role=='buffett':
                    Interrupted.calls+=1
                    if 'output_feedback' in p:raise RuntimeError('private-provider-detail')
                    v['evidence_ids']=['wrong-record']
                return v
        self.e.model=Interrupted()
        with self.assertRaises(RuntimeError):self.initial()
        doc=project(self.s,runs(self.s)[0]['id'])
        self.assertIn('교정 응답을 받는 중',doc['run']['message'])
        self.assertNotIn('private-provider-detail',str(doc));self.assertEqual(Interrupted.calls,2)
        c=next(c for c in doc['components'] if c['id']=='buffett')
        self.assertIsNone(c['output']);self.assertEqual(len(c['extensions']['output_validation']),1)

    def test_nonobject_invalid_output_stays_inspectable_as_failure(self):
        class Broken(DemoModel):
            def complete(model,*args):return ['unexpected-output']
        self.e.model=Broken()
        with self.assertRaises(AgentOutputError):self.initial()
        c=project(self.s,runs(self.s)[0]['id'])['components'][0]
        self.assertIsNone(c['output']);self.assertEqual(c['status'],'failed')
        self.assertEqual(len(c['extensions']['output_validation']),2)

    def test_rejected_memory_operations_not_presented_as_accepted_plan(self):
        first=self.initial()
        class BadMemory(DemoModel):
            def complete(model,role,guide,p,contract):
                v=super().complete(role,guide,p,contract)
                if role=='memory' and 'output_feedback' not in p:v.update(summary='rejected memory plan',unexpected=True)
                return v
        self.e.model=BadMemory();r=self.e.run('2026-11-21',self.week())
        view=present(self.s,self.s.get(r['event_id']))['view']
        self.assertEqual(len(view['memory']),1);self.assertNotIn('rejected memory plan',str(view['memory']))

    def test_dialogue_context_uses_adopted_result_and_validation_history(self):
        class Correct(DemoModel):
            def complete(model,role,guide,p,contract):
                v=super().complete(role,guide,p,contract)
                if role=='buffett' and 'output_feedback' not in p:v['evidence_ids']=['wrong-record']
                return v
        self.e.model=Correct();r=self.initial()
        database_path=self.s.store.db.execute('PRAGMA database_list').fetchone()['file']
        @contextmanager
        def session():
            from mara.store import Store
            db=Store(database_path)
            try:yield db.session(self.token)
            finally:db.close()
        manager=Dialogues(session,DemoModel);rid=uuid.uuid4().hex
        manager.start({'run_id':r['run_id'],'agent_id':'buffett','request_id':rid,'message':'어떤 근거를 사용했나요?'})
        manager.workers[rid].join(5)
        self.assertEqual(self.s.latest('dialogue_result')['body']['status'],'completed')
        ctx=self.s.latest('dialogue_request')['body']['context']
        self.assertNotIn('output_feedback',ctx['role_input']);self.assertEqual(ctx['role_output']['evidence_ids'],['demo-1'])
        self.assertEqual([x['status'] for x in ctx['output_validation']],['rejected','accepted'])


class SetupFailureTests(unittest.TestCase):
    setUp=setup_fixture.SetupTests.setUp
    tearDown=setup_fixture.SetupTests.tearDown

    def test_failed_job_names_role_and_keeps_answers(self):
        class Bad(setup_fixture.TestModel):
            def complete(model,role,*args):
                v=super().complete(role,*args)
                if role=='buffett':v['evidence_ids']=['broker-event']
                return v
        self.app.model_factory=Bad;self.app.start(self.value);self.app.thread.join(10)
        job=self.app.state()['job'];self.assertEqual(job['error_type'],'AgentOutputError')
        self.assertIn('Warren Buffett',job['message']);self.assertNotIn('토스 연결',job['message'])
        self.assertEqual(job['output_validation']['code'],'market_evidence_reference')
        with self.app.session() as s:self.assertFalse(s.events('broker_intent'));self.assertFalse(s.events('completed'))

    def test_legacy_generic_failure_diagnosed_read_only_without_provider(self):
        self.app.job('old','running','분석 중')
        class Bad(setup_fixture.TestModel):
            def complete(model,role,*args):
                v=super().complete(role,*args)
                if role=='buffett':v['evidence_ids']=['old-broker-record']
                return v
        self.app.model_factory=Bad
        with self.assertRaises(AgentOutputError):self.app.generate(self.value,self.snapshot)
        self.app.job('old','failed','예전 일반 오류',error_type='ValueError')
        with self.app.session() as s:original=s.latest('onboarding_job');count=s.store.db.execute('SELECT count(*) FROM events').fetchone()[0]
        state=self.app.state()
        self.assertIn('Warren Buffett',state['job']['message']);self.assertEqual(state['job']['diagnostic_source'],'read_only_validation_of_original_output')
        with self.app.session() as s:
            self.assertEqual(s.get(original['id']),original);self.assertEqual(s.store.db.execute('SELECT count(*) FROM events').fetchone()[0],count)
        # A later unrelated job cannot inherit the previous role failure.
        self.app.job('unrelated','running','시세 조회');self.app.job('unrelated','failed','조회 오류',error_type='ValueError')
        self.assertNotIn('output_validation',self.app.state()['job'])

if __name__=='__main__':unittest.main()
