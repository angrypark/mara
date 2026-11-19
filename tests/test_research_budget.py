import copy,tempfile,unittest
from contextlib import contextmanager
from unittest.mock import patch
from pathlib import Path
from mara.company_research import CompanyLibrary,ResearchTools
from mara.research_budget import TOTAL,ROLES,size
from mara.store import Store

DAY='2026-11-18'


def fact(fid,characters,tool='company_filing_read'):
    f={'id':fid,'text':'','topic':'Synthetic budget fixture','source':'https://www.sec.gov/fixture',
        'published_at':DAY,'known_at':DAY,'valid_until':DAY,'uncertainty':'Synthetic; not investment evidence','research_tool':tool}
    f['text']='x'*(characters-size(f));assert size(f)==characters;return f


class ResearchBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Store(Path(self.tmp.name)/'db.sqlite3');self.addCleanup(self.db.close)
        self.s=self.db.session(self.db.create_user('fixture'));self.lib=CompanyLibrary(Path(self.tmp.name)/'public',today=DAY)
    def runner(self,run):return ResearchTools(self.lib,self.s,run,DAY)
    def inherited(self,run,characters,parent='parent',fid='old',role='wood'):
        f=fact(fid,characters);eid=self.s.append('research_evidence',{'role':role,'fact':f,'budget_bucket':'role_reserved'},DAY,parent)
        completed=self.s.append('completed',{'fixture':True},DAY,parent)
        body=copy.deepcopy(self.s.get(eid)['body']);body['carried_from']={'event_id':eid,'run_id':parent,'completed_id':completed}
        self.s.append('research_evidence',body,DAY,run);return f
    def close(self,run,role,stage=None):
        iid=self.s.append('agent_input',{'role':role,'payload':{'analysis_stage':stage or role}},DAY,run)
        self.s.append('agent_validation',{'role':role,'status':'accepted','input_id':iid},DAY,run)
    def test_inherited_occupancy_is_paid_once_and_remaining_shares_are_frozen(self):
        old=self.inherited('run',148835);market={'facts':[old]};runner=self.runner('run')
        self.assertTrue(runner.activate('wood',fact('new',14000),market))
        plan=self.s.events('research_budget_plan')[-1]['body']
        self.assertEqual(plan['inherited_characters'],148835)
        self.assertEqual(148835+plan['general_limit']+6*plan['role_limit'],TOTAL)
        before=copy.deepcopy(plan)
        self.assertTrue(runner.activate('buffett',fact('second',5000),market))
        self.assertEqual(self.s.events('research_budget_plan')[-1]['body'],before)
        self.assertEqual(runner.activation_budget['run_used'],162835)
        self.assertEqual(self.s.events('research_evidence')[0]['body']['fact'],old)
    def test_three_generations_keep_unique_original_facts_and_never_refresh_global_capacity(self):
        old=self.inherited('B',100000,parent='A');b=self.runner('B');m={'facts':[old]}
        self.assertTrue(b.activate('wood',fact('new-B',20000),m));end=self.s.append('completed',{'fixture':True},DAY,'B')
        for event in [e for e in self.s.events('research_evidence') if e['run_id']=='B']:
            body=copy.deepcopy(event['body']);body['carried_from']={'event_id':event['id'],'run_id':'B','completed_id':end}
            self.s.append('research_evidence',body,DAY,'C')
        c=self.runner('C');self.assertTrue(c.activate('wood',fact('new-C',10000),copy.deepcopy(m)))
        plans=[e['body'] for e in self.s.events('research_budget_plan') if e['run_id']=='C']
        self.assertEqual(plans[0]['inherited_characters'],120000);self.assertEqual(plans[0]['remaining_at_start'],248000)
    def test_general_own_and_released_shares_can_fund_one_fact_atomically(self):
        runner=self.runner('run');m={'facts':[]}
        self.assertTrue(runner.activate('evidence',fact('general',79000,'company_compare'),m))
        self.close('run','evidence')
        self.assertTrue(runner.activate('wood',fact('combined',70000),m))
        row=self.s.events('research_evidence')[-1]['body'];self.assertEqual(row['budget_allocation'],{'general':1000,'role_reserved':48000,'borrowed':21000})
        self.assertEqual(sum(row['budget_allocation'].values()),size(row['fact']))
        self.assertEqual(runner.activation_budget['protected_other_roles'],4*48000)
        before=len(self.s.events('research_evidence'))
        self.assertFalse(runner.activate('wood',fact('cannot-use-protected',30000),m))
        self.assertEqual(len(self.s.events('research_evidence')),before)
        self.assertTrue(runner.activate('marks',fact('marks-share',48000),m))
    def test_first_validation_and_retries_keep_final_validation_share_protected(self):
        r=self.runner('run');m={'facts':[]}
        self.assertTrue(r.activate('evidence',fact('general',80000,'company_compare'),m))
        self.s.append('research_stop',{'role':'evidence'},DAY,'run')
        self.close('run','validation','perspective_validation')
        self.assertFalse(r.activate('wood',fact('too-large',49000),m))
        self.assertEqual(r.activation_budget['closed_roles'],[])
        self.assertTrue(r.activate('validation',fact('first',24000),m))
        again=self.runner('run');self.assertFalse(again.activate('validation',fact('overspend',25000),m))
        self.assertTrue(again.activate('validation',fact('final',24000),m))
        self.close('run','validation','final_validation')
        self.assertFalse(again.activate('validation',fact('after-closed',500),m))
        self.assertEqual(again.activation_budget['blocked_reason'],'research_role_already_closed')
    def test_exhausted_or_oversized_inheritance_has_no_new_capacity(self):
        for total in (TOTAL,TOTAL+1):
            run='case'+str(total);old=self.inherited(run,total,parent='parent'+run)
            r=self.runner(run);m={'facts':[old]}
            self.assertFalse(r.activate('wood',fact('extra'+run,500),m))
            self.assertEqual(r.activation_budget['blocked_reason'],'supplemental_global_limit')
            self.assertEqual(r.activation_budget['general_limit'],0);self.assertEqual(r.activation_budget['role_reserved_limit'],0)
    def test_idempotence_and_collisions_do_not_recharge_or_replace_evidence(self):
        r=self.runner('run');m={'facts':[]};f=fact('same',1000)
        self.assertTrue(r.activate('wood',f,m));count=len(self.s.events('research_evidence'))
        self.assertTrue(self.runner('run').activate('wood',copy.deepcopy(f),m));self.assertEqual(len(self.s.events('research_evidence')),count)
        with self.assertRaisesRegex(ValueError,'evidence_id_collision'):r.activate('wood',dict(f,text='changed'),m)
        self.assertEqual(m['facts'][0],f)
    def test_new_inheritance_cannot_change_an_already_frozen_pool(self):
        r=self.runner('run');m={'facts':[]};self.assertTrue(r.activate('wood',fact('first',500),m))
        self.inherited('run',1000)
        with self.assertRaisesRegex(ValueError,'after_budget_freeze'):r.activate('wood',fact('second',500),m)
    def test_tampered_inherited_source_is_rejected(self):
        old=self.inherited('run',1000);event=self.s.events('research_evidence')[-1]
        other=copy.deepcopy(event['body']);other['fact']=dict(old,id='tampered')
        self.s.append('research_evidence',other,DAY,'bad')
        with self.assertRaisesRegex(ValueError,'inherited_evidence_changed'):self.runner('bad').activate('wood',fact('new',500),{'facts':[]})
    def test_canonical_reread_restores_allowed_role_projection_without_recharge(self):
        from mara.research import project_fact
        from mara.domain import dumps
        f=fact('financial',1000,'sec_financials');f['text']=dumps({'entity':'Fixture','metrics':{'cash':[{'value':123}]}})
        f['raw_refs']=[{'sha256':'a'*64,'source':f['source']}]
        r=self.runner('run');market={'facts':[]};self.assertTrue(r.activate('bogle',f,market))
        projected={'facts':[project_fact(f,'bogle')]};count=len(self.s.events('research_evidence'))
        self.assertNotIn('metrics',__import__('json').loads(projected['facts'][0]['text']))
        self.assertTrue(r.activate('bogle',copy.deepcopy(f),projected));self.assertEqual(projected['facts'][0],f)
        self.assertEqual(len(self.s.events('research_evidence')),count)
        changed={'facts':[dict(project_fact(f,'bogle'),source='https://invalid.example')]}
        with self.assertRaisesRegex(ValueError,'collision'):r.activate('bogle',f,changed)
    def test_append_and_commit_failure_leave_payload_and_budget_unmodified_for_retry(self):
        for fail_commit in (False,True):
            run='failure-'+str(fail_commit);r=self.runner(run);market={'facts':[]};f=fact(run,1000)
            append=self.s.append;transaction=self.s.store.transaction
            def broken_append(kind,*args,**kwargs):
                if kind=='research_evidence':raise OSError('synthetic append failure')
                return append(kind,*args,**kwargs)
            @contextmanager
            def broken_transaction():
                with transaction():
                    yield
                    raise OSError('synthetic commit failure')
            context=patch.object(self.s.store,'transaction',broken_transaction) if fail_commit else patch.object(self.s,'append',side_effect=broken_append)
            with context:
                with self.assertRaises(OSError):r.activate('wood',f,market)
            self.assertEqual(market['facts'],[])
            self.assertEqual([e for e in self.s.events('research_evidence') if e['run_id']==run],[])
            self.assertEqual([e for e in self.s.events('research_budget_plan') if e['run_id']==run],[])
            self.assertTrue(r.activate('wood',f,market));self.assertEqual(len(market['facts']),1)
    def test_activation_must_own_commit_before_publishing_to_payload(self):
        market={'facts':[]}
        with self.s.store.transaction():
            with self.assertRaisesRegex(ValueError,'owned_transaction'):self.runner('nested').activate('wood',fact('nested',500),market)
        self.assertEqual(market['facts'],[])
    def test_engine_rejects_conflicting_parent_id_before_skipping_inheritance(self):
        from test_evidence_resolution import EvidenceResolutionTests,DAY as fixture_day
        from mara.engine import Engine
        from mara.agents import DemoModel
        fixture=EvidenceResolutionTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        report=fixture.run_demo();original=fixture.s.get(report['event_id'])
        conflicting=dict(fixture.m['facts'][0],text='Conflicting synthetic observation')
        fixture.s.append('research_evidence',{'role':'wood','fact':conflicting,'budget_bucket':'general'},fixture_day,report['run_id'])
        parent=fixture.s.append('completed',original['body'],fixture_day,report['run_id'])
        with self.assertRaisesRegex(ValueError,'Inherited evidence ID collision'):
            Engine(fixture.s,DemoModel()).run(fixture_day,force=True,revision_reason='synthetic collision',improvement={'parent_completed_id':parent})
    def recovery_dispatch(self,run,request_id='fix',valid=True):
        oid=self.s.append('recovery_leader_output',{'output':{'requests':[{'id':request_id,'needs_research':True,'historical_sources':[]}]}},DAY,run)
        self.s.append('recovery_leader_validation',{'output_id':oid,'status':'accepted' if valid else 'rejected'},DAY,run)
        return self.s.append('recovery_research_dispatch',{'leader_output_id':oid,'request_id':request_id,'target_role':'bogle'},DAY,run)
    def test_cancelled_recovery_dispatch_closes_supplier_without_refunding_budget(self):
        r=self.runner('cancel');m={'facts':[]}
        self.assertTrue(r.activate('evidence',fact('base',80000),m));self.close('cancel','evidence')
        dispatch=self.recovery_dispatch('cancel')
        self.assertTrue(r.activate('evidence',fact('before-cancel',2000),m))
        count=len(self.s.events('research_evidence'));plan=copy.deepcopy(self.s.latest('research_budget_plan')['body'])
        self.s.append('recovery_research_cancelled',{'dispatch_id':dispatch,'status':'cancelled_before_delivery'},DAY,'cancel')
        self.assertFalse(r.activate('evidence',fact('after-cancel',1000),m))
        self.assertFalse(r.activation_budget['recovery_supplier']);self.assertEqual(r.activation_budget['blocked_reason'],'research_role_already_closed')
        self.assertEqual(r.activation_budget['run_used'],82000)
        self.assertEqual(len(self.s.events('research_evidence')),count);self.assertEqual(self.s.latest('research_budget_plan')['body'],plan)
    def test_verified_recovery_supplier_uses_same_residual_budget_then_closes(self):
        r=self.runner('run');m={'facts':[]}
        self.assertTrue(r.activate('evidence',fact('base',80000),m));self.close('run','evidence')
        self.assertFalse(r.activate('evidence',fact('denied',1000),m))
        self.recovery_dispatch('run',valid=False)
        self.assertFalse(r.activate('evidence',fact('invalid-leader',1000),m))
        dispatch=self.recovery_dispatch('run','accepted')
        self.assertTrue(r.activate('evidence',fact('response',2000),m))
        row=self.s.events('research_evidence')[-1]['body']
        self.assertEqual(row['budget_allocation'],{'general':0,'role_reserved':0,'borrowed':2000})
        self.assertEqual(r.activation_budget['run_used'],80000)
        self.s.append('recovery_research_return',{'dispatch_id':dispatch},DAY,'run')
        self.assertFalse(r.activate('evidence',fact('closed-again',1000),m))
        self.assertEqual(r.activation_budget['blocked_reason'],'research_role_already_closed')
        self.assertEqual(len(self.s.events('research_budget_plan')),1)
