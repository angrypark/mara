"""Production call envelopes: concise roles keep their structured accountability."""
import copy
import tempfile
import unittest
from pathlib import Path
from mara.agents import Agents
from mara.judgment_reports import VERSION
from mara.store import Store
from narrative_fixture import narrative


class EnvelopeCaptured(Exception):
    pass


class CaptureModel:
    mode='live'
    identity={'mode':'live','model':'synthetic-envelope-capture'}
    def complete(self,role,guide,payload,contract):
        self.call=(role,guide,payload,contract)
        raise EnvelopeCaptured()


class RoleOutputPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'db')
        self.session=self.store.session(self.store.create_user('synthetic'))
        self.model=CaptureModel()
        self.agents=Agents(self.session,self.model,'2026-11-18','synthetic-policy')
        self.payload={'as_of':'2026-11-18','market':{'facts':[]}}
    def tearDown(self):
        self.store.close();self.tmp.cleanup()
    def capture(self,role,payload=None):
        with self.assertRaises(EnvelopeCaptured):self.agents.call(role,payload or self.payload)
        return self.model.call
    def test_only_final_synthesis_and_evaluation_require_length_contract(self):
        for role in ('context','evidence','buffett','marks','bogle','wood','validation','reflection','memory'):
            with self.subTest(role=role):
                _,guide,payload,contract=self.capture(role)
                self.assertNotIn('narrative_contract',payload)
                self.assertNotIn('judgment_report',contract['required'])
                self.assertNotIn('judgment_report',contract['properties'])
                self.assertEqual(payload['role_output_policy']['format'],'structured_concise')
                self.assertIn('반대 근거',guide)
                self.assertNotIn('공백 제외 최소 1,400자',guide)
        for role in ('leader','evaluator'):
            _,guide,payload,contract=self.capture(role)
            self.assertEqual(payload['narrative_contract'],VERSION)
            self.assertIn('judgment_report',contract['required'])
            self.assertEqual(payload['role_output_policy']['format'],'detailed_report')
            self.assertIn('공백 제외 최소 1,400자',guide)
    def test_accountability_reaches_provider_and_saved_input_for_each_role(self):
        import json
        from mara.codex_model import build_prompt
        from mara.model_wire import INSTRUCTION, VERSION as WIRE_VERSION, unpacked
        from mara.registry import catalogue, resource

        self.model.input_wire_version = WIRE_VERSION
        common = resource('guides/roles/team.md').read_text().strip()
        for row in catalogue():
            role = row['id']
            with self.subTest(role=role):
                _, guide, payload, contract = self.capture(role)
                saved = self.session.latest('agent_input')['body']
                wire = build_prompt(self.model, role, guide, payload, contract)
                resolved = unpacked(json.loads(wire.split(INSTRUCTION, 1)[1]))
                self.assertEqual(saved['guide'], resolved['role_guide'])
                self.assertIn(common, guide)
                section = resource(row['guide']).read_text().split('## 역할 책임과 인계')[1].strip()
                self.assertIn(section, guide)

    def test_fresh_override_and_standalone_leader_keep_handoff(self):
        from mara.registry import role_guide, submission_guide
        override = role_guide('leader', 'custom role strategy')
        self.assertTrue(override.startswith('custom role strategy'))
        self.assertIn('## 역할 책임과 인계', override)
        sparse = {'analysis_stage':'proposal_synthesis'}
        self.assertEqual(submission_guide('leader', override, sparse), override)
        self.assertEqual(submission_guide('leader', 'custom role strategy', sparse), override)
        prepared = dict(sparse, input_budget={'version':'archived'})
        self.assertEqual(submission_guide('leader', 'archived text', prepared), 'archived text')

    def test_concise_context_output_is_accepted_without_repair(self):
        output={'summary':'판단에 필요한 현금 계획을 확인했어요.','constraints':['한도 유지'],'missing':[]}
        self.model.complete=lambda *_:copy.deepcopy(output)
        original=copy.deepcopy(self.payload)
        result,_=self.agents.call('context',self.payload)
        self.assertEqual(result,output);self.assertEqual(self.payload,original)
        validations=self.session.events('agent_validation')
        self.assertEqual(len(validations),1);self.assertEqual(validations[0]['body']['status'],'accepted')
    def test_explicit_legacy_contract_and_reports_remain_supported(self):
        payload={**self.payload,'narrative_contract':VERSION}
        _,guide,sent,contract=self.capture('context',payload)
        self.assertIn('judgment_report',contract['required'])
        self.assertEqual(sent['role_output_policy']['format'],'detailed_report')
        self.model.complete=lambda *_:{'summary':'과거 계약 재실행','constraints':[],'missing':[],'judgment_report':narrative(payload)}
        result,_=self.agents.call('context',payload)
        self.assertEqual(result['judgment_report']['schema_version'],VERSION)
        # Existing optional v1.0 reports retain their validation and display data.
        result,_=self.agents.call('context',self.payload)
        self.assertEqual(result['judgment_report']['schema_version'],VERSION)
