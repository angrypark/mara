"""Synthetic conversational provenance, concurrency and frozen handoff checks."""
import copy,json,threading,unittest,uuid
from datetime import date
from unittest.mock import patch
from mara.persona_chat import PersonaConversations,PersonaError,grounded,apply_updates
from mara.persona import build,ensure
from mara.engine import Engine
from mara.onboarding import InputError
from mara.workbench import project
from mara.reporting import present
import test_onboarding_risk as fixtures
from test_onboarding_risk import TestModel


def update(field,value,quote,certainty='explicit'):
    return dict(field=field,value=value,basis_quote=quote,certainty=certainty,reason='synthetic statement')

class GroundingTests(unittest.TestCase):
    def test_numbers_are_grounded_to_unit_period_scope_and_entire_sentence(self):
        cases=[('monthly_income',3000000,'월 소득 300만원'),('monthly_income',3000000,'월 실수령액 500만원이 아니라 300만원'),('monthly_expenses',2000000,'월 지출 200만원'),
            ('household.reported_liquid_cash',50000000,'전체 보유 현금 5천만원'),('max_loss_fraction',.2,'손실 20%를 감당합니다'),
            ('persona_preferences.sector_interests','반도체','반도체에 관심 있어요')]
        for f,v,q in cases:self.assertEqual(grounded(update(f,v,q),q)['value'],v)
        invalid=[('monthly_income',5000000,'월 소득 500만원','월 소득 500만원이 아니라 300만원입니다'),
            ('monthly_income',3000000,'월 소득 500만원, 월 지출 300만원','월 소득 500만원, 월 지출 300만원'),
            ('monthly_income',3000000,'월 소득 300만원','예를 들어 월 소득 300만원이면요'),
            ('monthly_income',3000000,'월 소득 300만원','과거 월 소득 300만원이었어요'),
            ('monthly_income',5000000,'연봉 6000만원', '연봉 6000만원'),
            ('max_loss_fraction',.5,'손실 50%를 감당','손실 50%를 감당 못합니다'),
            ('max_loss_fraction',.5,'공격적으로 투자해요','공격적으로 투자해요'),
            ('household.reported_liquid_cash',1000000,'증권 계좌에 현금 100만원 있어요','증권 계좌에 현금 100만원 있어요'),
            ('monthly_income',1000000,'월 소득 100만 달러','월 소득 100만 달러'),
            ('household.mortgage_rate',.3,'손실 30% 감수','손실 30% 감수'),
            ('max_loss_fraction',.5,'손실 50%를 감당할 수 있다면','손실 50%를 감당할 수 있다면'),
            ('monthly_income',8000000,'월급 800만원','승진하면 월급 800만원'),
            ('funding_source','current_assets','반도체에 관심','반도체에 관심'),
            ('household.debt_payment_in_expenses','yes','대출이 있어요','대출이 있어요'),
            ('horizon_purpose','review','생활비가 많아요','생활비가 많아요')]
        for f,v,q,m in invalid:
            with self.subTest(m=m),self.assertRaises(PersonaError):grounded(update(f,v,q),m)

    def test_soft_preference_cannot_raise_loss_or_deploy_household_cash(self):
        p={'max_loss_fraction':.2,'proposal_capital':1000,'total_assets':10000,'financial_assets_basis':'declared_cash_only_lower_bound'}
        q='매우 공격적인 성장주 투자를 원합니다'
        result,accepted,issues=apply_updates(p,[update('persona_preferences.risk_preference',q,q,'interpretation'),update('max_loss_fraction',.5,q)],q,dict(id='m',seq=9,effective='2026-11-17'))
        self.assertEqual(result['max_loss_fraction'],.2);self.assertNotIn('persona_loss_capacity_confirmed',result)
        self.assertEqual(len(issues),1);self.assertEqual(len(accepted),1)
        q='전체 보유 현금 5천만원'
        result,_,_=apply_updates(result,[update('household.reported_liquid_cash',50000000,q)],q,dict(id='n',seq=10,effective='2026-11-17'))
        self.assertEqual(result['proposal_capital'],1000);self.assertEqual(result['total_assets'],50000000)

    def test_withdrawn_fact_is_not_used_and_explicit_correction_resolves_it(self):
        p={'monthly_income':5000000};q='이전에 준 소득은 확정이 아니니 취소해주세요'
        p,accepted,_=apply_updates(p,[],q,dict(id='w',seq=1,effective='2026-11-17'))
        self.assertIn('monthly_income',p['contested_fields']);self.assertTrue(accepted)
        self.assertEqual(next(f for f in build(p,'p',1,'2026-11-17')['facts'] if f['id']=='monthly_income')['status'],'disputed')
        q='월 소득 300만원'
        p,_,_=apply_updates(p,[update('monthly_income',3000000,q)],q,dict(id='c',seq=2,effective='2026-11-17'))
        self.assertFalse(p['contested_fields']);self.assertEqual(p['monthly_income'],3000000)

    def test_additive_interests_and_currency_scope(self):
        p={'base_currency':'USD'};q='월 소득 300만원'
        result,applied,issues=apply_updates(p,[update('monthly_income',3000000,q)],q,dict(id='m',seq=1,effective='2026-11-17'))
        self.assertFalse(applied);self.assertTrue(issues)
        for seq,q in enumerate(['반도체 관심','바이오도 관심']):
            p,_,_=apply_updates(p,[update('persona_preferences.interests',q,q)],q,dict(id=str(seq),seq=seq,effective='2026-11-17'))
        self.assertIn('반도체',p['persona_preferences']['interests']['text']);self.assertIn('바이오',p['persona_preferences']['interests']['text'])

    def test_saved_facts_and_user_answer_memory_are_not_fresh_confirmation(self):
        p={'base_currency':'KRW','monthly_income':100,'max_loss_fraction':.2,'confirmed_answer_facts':[{'question_id':'x','topic':'debt','answer':'included','answer_context':'scope?','source_answer_id':'a','scope':'historical user answer','agent_reason':'secret-old-judgment'}]}
        persona=build(p,'p',1,'2026-11-17')
        self.assertEqual(next(x for x in persona['facts'] if x['id']=='monthly_income')['status'],'recorded')
        self.assertIsNone(persona['risk']['confirmed_loss_capacity_fraction'])
        self.assertEqual(persona['answer_memory'][0]['answer'],'included');self.assertNotIn('secret-old-judgment',json.dumps(persona))

class PersonaFlowTests(unittest.TestCase):
    setUp=fixtures.SetupTests.setUp
    tearDown=fixtures.SetupTests.tearDown

    def prepare(self):
        self.app.generate(self.value,self.snapshot)
        self.chat=PersonaConversations(self.app)
        self.addCleanup(lambda:self.chat.thread.join(10) if self.chat.thread else None)
        return self.chat.read()['persona']

    def send(self,message,output,wait=True):
        class Model:
            identity={'mode':'live','model':'synthetic-intake'}
            def complete(model,role,guide,payload,contract):
                self.payload=payload
                return output() if callable(output) else output
        self.app.analysis_model=lambda:Model()
        body={'request_id':uuid.uuid4().hex,'message':message,'persona_id':(self.chat.read()['persona'] or {}).get('id')}
        result=self.chat.start(body)
        if wait:self.chat.thread.join(10)
        return body,result

    def test_version_pair_atomic_deduplication_owner_and_no_actual_mutation(self):
        before=self.prepare()
        with self.app.session() as s:actual=s.latest('actual');original=s.get(before['body']['profile_id'])
        q='전체 보유 현금 5천만원'
        body,_=self.send(q,{'reply':'현금을 반영했어요','updates':[update('household.reported_liquid_cash',50000000,q)],'question':None})
        state=self.chat.read();after=state['persona'];self.assertEqual(state['turns'][-1]['result']['status'],'completed')
        self.assertNotEqual(before['id'],after['id']);self.assertEqual(after['body']['version'],before['body']['version']+1)
        self.assertTrue(self.chat.start(body)['duplicate'])
        with self.assertRaises(PersonaError):self.chat.start(dict(body,message='different'))
        with self.app.session() as s:
            self.assertEqual(s.get(original['id']),original);self.assertEqual(s.latest('actual'),actual)
            self.assertFalse(s.events('broker_intent'));self.assertEqual(ensure(s,s.latest('profile'))['id'],after['id'])
            other=s.store.session(s.store.create_user('other'))
            with self.assertRaises(PermissionError):other.get(after['id'])
            self.assertFalse(other.events('persona_message'))
        with self.assertRaises(InputError):self.app.draft(dict(self.value,profile_base_id=original['id']))

    def test_rejected_model_changes_do_not_claim_success_and_raw_output_survives(self):
        self.prepare();q='월 소득 500만원이 아니라 300만원'
        self.send(q,{'reply':'월 소득 500만원으로 변경했습니다','updates':[update('monthly_income',5000000,'월 소득 500만원')],'question':None})
        result=self.chat.read()['turns'][-1]['result'];self.assertEqual(result['updates'],[]);self.assertTrue(result['issues']);self.assertNotIn('500만원으로 변경',result['reply'])
        with self.app.session() as s:self.assertTrue(s.events('persona_model_output'))

    def test_late_model_response_cannot_overwrite_newer_profile(self):
        self.prepare();entered=threading.Event();release=threading.Event();q='월 소득 700만원'
        def output():entered.set();release.wait(5);return {'reply':'갱신','updates':[update('monthly_income',7000000,q)],'question':None}
        self.send(q,output,wait=False);self.assertTrue(entered.wait(5))
        with self.app.session() as s:
            p=copy.deepcopy(s.latest('profile')['body']);p['monthly_income']=8000000;pid=Engine(s,None).set_profile(p,date.today().isoformat())
        release.set();self.chat.thread.join(10)
        self.assertEqual(self.chat.read()['turns'][-1]['result']['status'],'failed')
        self.assertEqual(self.chat.read()['persona']['body']['profile_id'],pid)

    def test_partial_intake_and_restart_preserve_original_without_inventing_full_profile(self):
        self.chat=PersonaConversations(self.app);q='반도체에 관심 있어요'
        self.send(q,{'reply':'관심사를 기록했어요','updates':[update('persona_preferences.sector_interests','반도체',q)],'question':None})
        self.assertEqual(self.chat.read()['persona']['body']['status'],'draft')
        with self.app.session() as s:
            self.assertIsNone(s.latest('profile'));self.assertIsNone(s.latest('actual'))
            s.append('persona_message',{'request_id':'pending','message':'pending','persona_id':None},date.today().isoformat())
        self.chat.recover();self.assertEqual(self.chat.read()['turns'][-1]['result']['status'],'interrupted')

    def test_frozen_persona_reaches_roles_and_report_shows_version_difference(self):
        persona=self.prepare();pid=persona['body']['profile_id']
        with self.app.session() as s:
            actual=s.latest('actual')['id'];p=copy.deepcopy(s.get(pid)['body']);p['goal']='updated current goal'
            Engine(s,None).set_profile(p,date.today().isoformat())
            r=Engine(s,TestModel()).run(date.today().isoformat(),force=True,revision_reason='synthetic pinned',profile_id=pid,actual_id=actual)
            self.assertEqual(r['persona_id'],persona['id'])
            roles=set()
            for row in s.events('agent_input'):
                if row['run_id']==r['run_id']:
                    roles.add(row['body']['role']);self.assertEqual(row['body']['payload']['user_persona']['id'],persona['id'])
            self.assertTrue({'context','evidence','buffett','wood','marks','bogle','validation','leader'}<=roles)
            doc=project(s,r['run_id']);self.assertFalse(doc['extensions']['persona_is_current'])
            self.assertEqual(doc['extensions']['user_persona']['id'],persona['id'])
            self.assertFalse(present(s,s.get(r['event_id']))['view']['persona_is_current'])

if __name__=='__main__':unittest.main()
