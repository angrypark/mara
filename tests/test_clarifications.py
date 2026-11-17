"""Personal answer ledger and bounded R1 clarification regression tests, synthetic only."""
import copy
import json
import tempfile
import unittest
import uuid
from datetime import date
from pathlib import Path
from mara.agents import validate_output, DemoModel
from mara.clarifications import answers, questions, notes_history, save_answers, ClarificationError, repeated_questions
from mara.engine import Engine, ContextNeedsInput, ContextRepeatError
from mara.store import Store
import test_onboarding_risk as fixtures
from test_onboarding_risk import TestModel


def question(qid='funding_timing',prompt='추가 자금은 언제 준비되나요?',reason=''):
    return {'id':qid,'topic':'funding_timing','prompt':prompt,'reason':'투입 가능한 시점과 현금 필요를 구분해요.','revisit_reason':reason,
        'options':[{'id':'ready','label':'이미 준비되어 있어요','description':'현재 별도로 보유한 현금이에요.','requires_text':False},
                   {'id':'later','label':'추후 준비돼요','description':'예정일을 알려주세요.','requires_text':True}]}


def output(q=None):
    return {'summary':'합성 개인 맥락 확인','constraints':[],'missing':[q['prompt']] if q else [],'questions':[q] if q else []}


def request(source,qid='funding_timing',choice='ready',text='',expected=None):
    return {'context_output_id':source,'request_id':uuid.uuid4().hex,'answers':[
        {'question_id':qid,'option_id':choice,'text':text,'expected_answer_id':expected}]}


class AnswerLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Store(Path(self.tmp.name)/'answers.sqlite3')
        self.token=self.db.create_user('a');self.s=self.db.session(self.token)
        self.other=self.db.session(self.db.create_user('b'))
        self.source=self.s.append('agent_output',{'role':'context','output':output(question())},date.today().isoformat(),'run-a')
    def tearDown(self):self.db.close();self.tmp.cleanup()

    def test_reload_versions_idempotence_and_ownership(self):
        original=self.s.get(self.source);r=request(self.source)
        first=save_answers(self.s,r);self.assertEqual(len(first['answers']),1)
        self.assertTrue(save_answers(self.s,r)['duplicate'])
        with self.assertRaises(PermissionError):save_answers(self.other,request(self.source))
        self.assertFalse(answers(self.other));self.assertFalse(answers(self.s,'2000-01-01'))
        old=first['answers'][0]['answer_id']
        edited=save_answers(self.s,request(self.source,choice=None,text='2027년 3월로 변경',expected=old))
        self.assertEqual(edited['answers'][0]['supersedes'],old)
        self.assertEqual(len(self.s.events('clarification_answer')),2)
        self.assertEqual(self.s.get(self.source),original)
        self.assertEqual(answers(self.db.session(self.token))[0]['text'],'2027년 3월로 변경')
        with self.assertRaises(ClarificationError):save_answers(self.s,request(self.source,expected=old))
        with self.assertRaises(ClarificationError):save_answers(self.s,dict(r,answers=[dict(r['answers'][0],text='changed')]))

    def test_choice_required_text_and_unknown_fields(self):
        for r in [request(self.source,choice='invented'),request(self.source,choice='later'),
                  request(self.source,choice=None),request(self.source,qid='debt'),
                  dict(request(self.source),extra='x')]:
            with self.assertRaises(ClarificationError):save_answers(self.s,r)
        self.assertFalse(answers(self.s))
        self.assertEqual(save_answers(self.s,request(self.source,choice='later',text='2027년 3월'))['answers'][0]['answer'],'추후 준비돼요 — 2027년 3월')

    def test_schema_stable_fact_slots_and_aligned_missing(self):
        good=output(question());validate_output('context',good,{})
        for change in [output(dict(question(),topic='invented_topic')),dict(good,missing=['다른 질문']),
                       dict(good,questions=[dict(question(),options=[question()['options'][0]]*2)])]:
            with self.assertRaises(ValueError):validate_output('context',change,{})
        saved={'question_id':'funding_timing','question':question()}
        self.assertTrue(repeated_questions(output(question(prompt='언제 입금할 예정이세요?')),{'clarification_answers':[saved]}))
        self.assertFalse(repeated_questions(output(question(reason='기존 3월 답변과 현재 1월 현금 필요가 충돌해요.')),{'clarification_answers':[saved]}))
        legacy={'question_id':'legacy_test','question':question()}
        self.assertTrue(repeated_questions(output(question('funding_source',prompt='자금의 준비 시점은요?')),{'clarification_answers':[legacy]}))

    def test_distinct_facts_share_topic_without_losing_either(self):
        ids=['family_emergency_support','employer_trading_restriction']
        for qid,text in zip(ids,['가족의 추가 지원은 불가능해요','회사 관련 주식은 거래할 수 없어요']):
            q=dict(question(qid),topic='other_context',revisit_reason='앞선 사실과 별개인 제약을 확인해요.')
            validate_output('context',output(q),{})
            src=self.s.append('agent_output',{'role':'context','output':output(q)},date.today().isoformat())
            save_answers(self.s,request(src,qid=qid,choice=None,text=text))
        self.assertEqual({a['question_id'] for a in answers(self.s)},set(ids))
        self.assertTrue(all(a['supersedes'] is None for a in answers(self.s)))
        # Renaming the same fact cannot bypass the mandatory prior-context comparison.
        self.assertTrue(repeated_questions(output(question('renamed_fact')),{'clarification_answers':answers(self.s)}))

    def test_historical_notes_accumulate_without_duplicate_weight_and_bounded(self):
        for note in ['별도 저축이에요','별도 저축이에요','내년 3월 투입해요']:
            self.s.append('onboarding_draft',{'context_notes':note},date.today().isoformat())
        h=notes_history(self.s,'내년 3월 투입해요')
        self.assertEqual([x['text'] for x in h],['별도 저축이에요','내년 3월 투입해요'])
        for i in range(20):self.s.append('onboarding_draft',{'context_notes':str(i)*1000},date.today().isoformat())
        self.assertLessEqual(len(json.dumps(notes_history(self.s,''),ensure_ascii=False)),12000)
        self.assertEqual(len(self.s.events('onboarding_draft')),23)

    def test_legacy_question_accepts_freeform_and_retains_original(self):
        old={'summary':'기존 맥락','constraints':[],'missing':['자금 출처는요?']}
        src=self.s.append('agent_output',{'role':'context','output':old},date.today().isoformat())
        q=questions(old)[0];self.assertTrue(q['id'].startswith('legacy_'))
        saved=save_answers(self.s,request(src,qid=q['id'],choice=None,text='급여 저축'))
        self.assertEqual(saved['answers'][0]['text'],'급여 저축')
        self.assertEqual(self.s.get(src)['body']['output'],old)


# Reuse the real onboarding/service fixture, without inheriting its test cases.
class ClarificationFlowTests(unittest.TestCase):
    setUp=fixtures.SetupTests.setUp
    tearDown=fixtures.SetupTests.tearDown

    def ask(self, direct=False):
        class Asking(TestModel):
            def complete(model,role,guide,p,contract):
                return output(question()) if role=='context' else super().complete(role,guide,p,contract)
        self.app.model_factory=Asking
        self.app.start(self.value);self.app.thread.join(10)
        job=self.app.state()['job'];self.assertEqual(job['status'],'needs_input')
        if direct:
            with self.app.session() as s:save_answers(s,request(job['context_output_id']))
        else:self.app.answer_context(request(job['context_output_id']))
        return job

    def test_saved_answers_reach_all_agents_and_notes_survive_shorter_input(self):
        self.ask();self.app.draft(dict(self.value,context_notes='별도 저축으로 마련한 자금이에요'))
        self.app.model_factory=TestModel
        self.app.start(dict(self.value,context_notes='3월 입금'));self.app.thread.join(10)
        self.assertEqual(self.app.state()['job']['status'],'completed')
        with self.app.session() as s:
            report=s.latest('completed');profile=s.get(report['body']['profile_id'])['body']
            self.assertEqual(profile['clarification_answers'][0]['option_id'],'ready')
            self.assertEqual([x['text'] for x in profile['context_note_history']],['별도 저축으로 마련한 자금이에요','3월 입금'])
            for e in s.events('agent_input'):
                if e['run_id']==report['run_id']:
                    self.assertEqual(e['body']['payload']['profile']['clarification_answers'],profile['clarification_answers'])
            self.assertFalse(s.events('broker_intent'))
        restarted=type(self.app)(self.app.directory)
        self.assertEqual(restarted.state()['clarification_answers'][0]['option_id'],'ready')

    def test_bounded_repair_reuses_answer_instead_of_reasking(self):
        self.ask()
        class Repair(TestModel):
            calls=0
            def complete(model,role,guide,p,contract):
                if role=='context':
                    Repair.calls+=1
                    return output() if 'clarification_feedback' in p else output(question(prompt='언제 자금을 투입하실 예정인가요?'))
                return super().complete(role,guide,p,contract)
        self.app.model_factory=Repair
        self.app.start(self.value);self.app.thread.join(10)
        self.assertEqual(Repair.calls,2);self.assertEqual(self.app.state()['job']['status'],'completed')

    def test_persistent_repeat_fails_clearly_and_real_conflict_can_ask(self):
        self.ask();self.app.start(self.value);self.app.thread.join(10)
        job=self.app.state()['job'];self.assertEqual(job['status'],'failed');self.assertEqual(job['error_type'],'ContextRepeatError')
        self.assertEqual(len(self.app.state()['clarification_answers']),1)
        class Conflict(TestModel):
            def complete(model,role,guide,p,contract):
                return output(question(reason='준비된 자금이라는 답과 현재 현금 부족이 충돌해 실제 투입액을 확인해요.')) if role=='context' else super().complete(role,guide,p,contract)
        self.app.model_factory=Conflict
        self.app.start(self.value);self.app.thread.join(10)
        self.assertEqual(self.app.state()['job']['status'],'needs_input')
        self.assertTrue(self.app.state()['job']['structured_questions'][0]['revisit_reason'])

    def test_common_engine_freezes_updated_answers_even_without_onboarding(self):
        self.ask(direct=True)
        with self.app.session() as s:
            # The prior failed run's profile precedes the answer event.
            before=s.latest('profile');self.assertFalse(before['body']['clarification_answers'])
            e=Engine(s,TestModel());r=e.run(date.today().isoformat(),force=True)
            resolved=s.get(r['profile_id'])['body']
            self.assertEqual(len(resolved['clarification_answers']),1)
            self.assertEqual(s.get(before['id']),before)
            for row in s.events('agent_input'):
                if row['run_id']==r['run_id']:self.assertEqual(row['body']['payload']['profile']['clarification_answers'],resolved['clarification_answers'])

if __name__=='__main__':unittest.main()
