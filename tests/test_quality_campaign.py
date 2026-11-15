import copy,json,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from mara.store import Store
from mara.engine import Engine
from mara.agents import DemoModel
from mara.quality_campaign import Campaign,projection
from mara.contracts import validate,schema

ROOT=Path(__file__).resolve().parent.parent


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Store(Path(self.tmp.name)/'db');self.s=self.db.session(self.db.create_user('test'))
        self.engine=Engine(self.s,DemoModel())
        p=json.loads((ROOT/'examples/profile.json').read_text());h=json.loads((ROOT/'examples/holdings.json').read_text());m=json.loads((ROOT/'examples/market.json').read_text())
        self.engine.set_profile(p,m['as_of']);self.engine.set_holdings(h)
        self.baseline=self.engine.run(m['as_of'],self.db.publish_market(m));self.day=m['as_of']
        self.original_actual=self.s.latest('actual');self.original_report=self.s.get(self.baseline['event_id'])
    def tearDown(self):self.db.close();self.tmp.cleanup()

    def test_evaluation_fingerprint_includes_appended_guide_and_coverage_dependencies(self):
        from mara.evaluation import evaluator_fingerprint,resource
        from mara.quality_campaign import frozen_rules
        model=DemoModel();before=evaluator_fingerprint(self.s,model,self.day)
        target='guides/roles/research-tools.md';changed=Path(self.tmp.name)/'guide.md';changed.write_text(resource(target).read_text()+'\nSynthetic dependency change')
        with patch('mara.evaluation.resource',side_effect=lambda p:changed if p==target else resource(p)):
            self.assertNotEqual(before,evaluator_fingerprint(self.s,model,self.day))
        self.assertIn('mara/coverage.py',frozen_rules());self.assertIn('mara/decision.py',frozen_rules())

    def test_five_actual_cycles_and_idempotent_resume_preserve_originals(self):
        c=Campaign(self.s,DemoModel());c.start(self.baseline['event_id'],'test');result=c.run('test')
        validate(result,schema('quality-campaign'))
        self.assertEqual(result['G6'],'pass');self.assertEqual(result['completed_improvements'],5)
        self.assertFalse(result['strict_quality_pass'])  # Running five times does not certify quality.
        self.assertEqual(len({x['evaluator_output_id'] for x in result['rounds']}),6)
        count=len(self.s.events('completed'));c.run('test');self.assertEqual(len(self.s.events('completed')),count)
        self.assertEqual(self.s.latest('actual'),self.original_actual);self.assertEqual(self.s.get(self.baseline['event_id']),self.original_report)
        for row in result['rounds']:
            p=self.s.get(row['evaluator_input_id'])['body']['payload']
            self.assertNotIn('improvement',p['report']);self.assertNotIn('revision_reason',p['report'])
        validate(projection(self.s,self.s.latest('completed')['id']),schema('quality-campaign'))

    def test_failed_evaluation_resumes_same_generated_report(self):
        class BreakOnce(DemoModel):
            broken=False
            def complete(model,role,guide,p,contract):
                if role=='evaluator' and p['report'].get('revision_of') and not model.broken:
                    model.broken=True;raise RuntimeError('Synthetic interruption')
                return super(BreakOnce,model).complete(role,guide,p,contract)
        model=BreakOnce();c=Campaign(self.s,model);c.start(self.baseline['event_id'],'resume')
        with self.assertRaises(RuntimeError):c.run('resume')
        target=self.s.latest('completed')['id'];self.assertEqual(c.status('resume')['checkpoint']['stage'],'evaluation')
        result=c.run('resume');self.assertEqual(result['G6'],'pass');self.assertEqual(result['rounds'][1]['completed_id'],target)
        self.assertEqual(len(self.s.events('completed')),6)
        self.assertTrue(any(x['body']['status']=='failed' for x in self.s.events('quality_checkpoint')))

    def test_new_user_decision_is_not_overwritten_and_tenant_cannot_resume(self):
        c=Campaign(self.s,DemoModel());c.start(self.baseline['event_id'],'branch')
        newer=self.engine.run(self.day,revision_reason='user new decision')
        with self.assertRaisesRegex(ValueError,'Newer user decision'):c.run('branch')
        self.assertEqual(self.s.latest('completed')['id'],newer['event_id'])
        other=self.db.session(self.db.create_user('other'))
        with self.assertRaises(ValueError):Campaign(other,DemoModel()).run('branch')

    def test_frozen_rules_reject_changed_provider(self):
        c=Campaign(self.s,DemoModel());c.start(self.baseline['event_id'],'frozen')
        model=DemoModel();model.identity={**model.identity,'model':'different'}
        with self.assertRaisesRegex(ValueError,'rules or model'):Campaign(self.s,model).run('frozen')
