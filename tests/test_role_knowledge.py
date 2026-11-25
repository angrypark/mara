from pathlib import Path
import json
import tempfile
import unittest

from mara.agents import Agents, DemoModel
from mara.engine import Engine
from mara.knowledge import Knowledge
from mara.role_knowledge import FIELD, record
from mara.store import Store


class RoleKnowledgeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(Path(tmp.name) / 'test.sqlite')
        self.addCleanup(self.store.close)
        self.session = self.store.session(self.store.create_user('owner'))
        self.knowledge = Knowledge(self.session)
        self.day = '2026-01-04'
        self.run = 'run'
        self.add = dict(action='add', reason='Recurring source discrepancy',
                        text='Prefer first publication when revision changes the conclusion.',
                        topic='source design', condition='When judging an historical decision',
                        category='lesson', valid_until=None)

    def submit(self, role, update, facts=()):
        class Provider(DemoModel):
            def complete(self, name, guide, payload, contract):
                return {'summary':'Accepted analysis', FIELD:update}
        task = Agents(self.session, Provider(), self.day, self.run)
        packet = {'knowledge': self.knowledge.retrieve(self.day,role), 'market':{'facts':list(facts)}}
        contract = {'type':'object','additionalProperties':False,'required':['summary'],
                    'properties':{'summary':{'type':'string'}}}
        result, oid = task.submit_scoped(role,'Test',packet,contract,lambda _:None,role_knowledge=True)
        self.assertEqual(result, {'summary':'Accepted analysis'})
        return oid

    def record(self, *ids):
        with self.store.transaction():
            return record(self.knowledge,self.day,self.run,ids)

    def test_own_updates_deliver_to_next_role_input_and_archive(self):
        oid = self.submit('evidence', self.add)
        self.assertEqual(self.record(oid)[0]['status'], 'applied')
        self.assertEqual(self.record(oid), [])
        item, = self.knowledge.retrieve(self.day,'evidence')['items']
        self.assertEqual(item['source_output_id'], oid)
        self.assertEqual(self.knowledge.retrieve(self.day,'leader')['items'], [])
        archive = dict(action='archive',key=item['key'],reason='Obsolete after source behavior changed')
        stolen = self.submit('leader',archive)
        self.assertEqual(self.record(stolen)[0]['status'], 'rejected')
        own = self.submit('evidence',archive)
        self.assertEqual(self.record(own)[0]['status'], 'applied')
        self.assertEqual(self.knowledge.retrieve(self.day,'evidence')['items'], [])
        self.assertEqual(self.knowledge.current(self.day)[item['key']]['previous_event'], item['event_id'])

    def test_older_submission_cannot_overwrite_new_version_and_duplicate_add_is_rejected(self):
        self.record(self.submit('evidence',self.add))
        item, = self.knowledge.retrieve(self.day,'evidence')['items']
        change = dict(action='revise', key=item['key'], text='Decisive comparison requires a frozen release.',
                      reason='Clarify judgment', condition=item['condition'],valid_until=None)
        first = self.submit('evidence',change)
        later = self.submit('evidence',dict(change,text='Different wording'))
        self.assertEqual(self.record(first)[0]['status'],'applied')
        self.assertEqual(self.record(later)[0]['status'],'rejected')
        updated = dict(self.add,text=change['text'])
        self.assertEqual(self.record(self.submit('evidence',updated))[0]['status'],'rejected')
        other = self.submit('leader',updated)
        self.assertEqual(self.record(other)[0]['status'],'applied')

    def test_retiring_a_principle_requires_delivered_invalidating_evidence(self):
        self.record(self.submit('evidence',dict(self.add,category='principle')))
        item, = self.knowledge.retrieve(self.day,'evidence')['items']
        archive = dict(action='archive',key=item['key'],reason='Replaced by direct publication',
                       invalidating_fact_ids=['publication'])
        self.assertEqual(self.record(self.submit('evidence',archive))[0]['status'],'rejected')
        revise = dict(action='revise',key=item['key'],reason='Changed publication policy',
                      text='Use later revisions.',condition=item['condition'],valid_until=None)
        self.assertEqual(self.record(self.submit('evidence',revise))[0]['status'],'rejected')
        oid = self.submit('evidence', archive, [{'id':'publication'}])
        self.assertEqual(self.record(oid)[0]['invalidating_fact_ids'],['publication'])
        self.assertFalse(self.knowledge.retrieve(self.day,'evidence')['items'])

    def test_engine_commits_early_roles_when_a_portfolio_is_completed(self):
        from narrative_fixture import ReportingDemoModel
        update = self.add
        class LiveFixture(ReportingDemoModel):
            mode='live'
            def complete(self, role, guide, payload, contract):
                out = super().complete(role,guide,payload,contract)
                if role in ('context','evidence','evaluator') and FIELD in contract.get('properties',{}):
                    out[FIELD]=update
                return out
        engine = Engine(self.session, LiveFixture())
        root = Path(__file__).resolve().parents[1] / 'examples'
        data = {name:json.loads((root/(name+'.json')).read_text()) for name in ('profile','holdings','market')}
        data['market']['synthetic']=False  # Exercise the live-provider contract with synthetic fixtures.
        day = data['market']['as_of']
        engine.set_profile(data['profile'],day)
        engine.set_holdings(data['holdings'])
        report = engine.run(day,self.store.publish_market(data['market']),evaluate_after=False)
        self.assertEqual({r['role'] for r in report['role_knowledge_updates'] if r['status']=='applied'},
                         {'context','evidence'})
        for role in ('context','evidence'):
            item, = self.knowledge.retrieve(day,role)['items']
            self.assertEqual(item['owner_role'],role)
        from mara.evaluation import evaluate_report
        frozen = evaluate_report(self.session,engine.model,report['event_id'])
        self.assertEqual(self.knowledge.retrieve('9999-12-31','evaluator')['items'],[])
        normal = evaluate_report(self.session,engine.model,report['event_id'],learn_role=True)
        self.assertNotEqual(frozen['evaluator_spec_hash'],normal['evaluator_spec_hash'])
        item, = self.knowledge.retrieve('9999-12-31','evaluator')['items']
        self.assertEqual(item['source_output_id'],normal['output_id'])

    def test_dated_snapshot_cannot_be_saved_as_a_principle(self):
        dated = dict(self.add, category='principle', text='Use the 2026-01-04 quote as a permanent anchor.')
        self.assertEqual(self.record(self.submit('evidence',dated))[0]['status'],'rejected')
        relative = dict(dated, condition='today only', text='The sample asset traded at 123.45.')
        self.assertEqual(self.record(self.submit('evidence',relative))[0]['status'],'rejected')
