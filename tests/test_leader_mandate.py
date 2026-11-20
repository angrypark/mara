import json
import unittest

from mara.agents import DemoModel
from mara.codex_model import CodexError
from mara.continuation import LEGACY_MESSAGE
from mara.leader_mandate import VERSION
from mara.model_wire import VERSION as WIRE_VERSION
from mara.registry import personas
import test_evidence_feedback as feedback_fixtures
import test_system as system_fixtures


class MandateTests(unittest.TestCase):
    setUp = system_fixtures.Harness.setUp
    tearDown = system_fixtures.Harness.tearDown
    run_feedback_fixture = feedback_fixtures.EvidenceFeedbackTests.run_fixture

    def test_plan_survives_independent_analysis_and_evidence_reassessment(self):
        class Model(feedback_fixtures.FeedbackModel):
            leader_mandate_version = VERSION

        model = Model()
        result, session = self.run_feedback_fixture(model)
        plan = result['leader_mandate']
        self.assertEqual(len(session.events('leader_mandate_input')), 1)
        self.assertEqual(session.latest('leader_mandate_validation')['body']['status'], 'accepted')
        self.assertEqual([role for role, _ in model.inputs[:3]], ['context', 'leader', 'evidence'])
        self.assertEqual(model.inputs[1][1]['analysis_stage'], 'leader_mandate')
        self.assertNotIn('perspectives', model.inputs[1][1])
        self.assertTrue(model.inputs[1][1]['user_persona']['body']['unknowns'])
        self.assertEqual(result['evidence_feedback']['rounds'], 1)
        leader_followups = []
        for role, payload in model.inputs[2:]:
            if role not in (*personas(), 'leader', 'validation', 'evidence'):
                continue
            delivered = payload['leader_mandate']
            for key in ('output_id', 'decision_objective', 'benchmark', 'alternatives', 'measurement_criteria',
                        'open_questions', 'constraint_basis', 'unconfirmed_personal_conditions'):
                self.assertEqual(delivered[key], plan[key])
            if role in (*personas(), 'evidence'):
                self.assertEqual([row['role'] for row in delivered['assignments']], [role])
                self.assertNotIn('perspectives', payload)
            if role == 'leader' and payload.get('evidence_feedback_reassessment'):
                leader_followups.append(payload)
        self.assertTrue(leader_followups)
        self.assertEqual(leader_followups[-1]['perspectives']['buffett']['evidence_assessments'][0]['status'], 'still_missing')
        self.assertIn('validation', leader_followups[-1])

    def test_rejects_omitted_or_reallocated_role_before_analysis(self):
        class InvalidModel(DemoModel):
            leader_mandate_version = VERSION

            def complete(self, role, guide, payload, contract):
                output = super().complete(role, guide, payload, contract)
                if contract.get('$id') == VERSION:
                    output['assignments'][0]['role'] = output['assignments'][1]['role']
                return output

        self.e.model = InvalidModel()
        with self.assertRaisesRegex(ValueError, 'exactly one assignment'):
            self.e.run('2026-11-14', self.mid, evaluate_after=False)
        self.assertEqual(self.s.latest('leader_mandate_validation')['body']['status'], 'rejected')
        self.assertEqual([row['body']['role'] for row in self.s.events('agent_input')], ['context'])
        self.assertFalse(self.s.events('completed'))

    def test_canonical_constraints_survive_context_summary_omissions(self):
        recorded = []

        class Model(DemoModel):
            leader_mandate_version = VERSION

            def complete(self, role, guide, payload, contract):
                result = super().complete(role, guide, payload, contract)
                if role == 'context':
                    result.update(summary='Assumed 60 months', constraints=[])
                if contract.get('$id') == VERSION:
                    recorded.append(payload)
                return result

        self.e.model = Model()
        updated = dict(self.p, horizon_months=24, constraints=['Synthetic constraint'],
                       max_position_fraction=.4, loss_budget_scope='analysis_only', analysis_loss_budget=.5)
        self.e.set_profile(updated, '2026-11-14')
        result = self.e.run('2026-11-14', self.mid, evaluate_after=False)
        plan_input = recorded[0]
        self.assertEqual(plan_input['context_analysis']['constraints'], [])
        for key in ('horizon_months', 'constraints', 'max_position_fraction'):
            self.assertEqual(plan_input['constraint_basis'][key], updated[key])
            self.assertEqual(result['leader_mandate']['constraint_basis'][key], updated[key])
        self.assertEqual(plan_input['decision_context']['risk_budget']['scope'], 'analysis_only')
        self.assertTrue(any(row['id'] == 'loss_capacity'
                            for row in result['leader_mandate']['unconfirmed_personal_conditions']))

    def test_resume_reuses_recorded_plan_and_q1_does_not_receive_authoring_plan(self):
        raw = []
        calls = []

        class Model(DemoModel):
            leader_mandate_version = VERSION
            input_wire_version = WIRE_VERSION

            def complete(self, role, guide, payload, contract):
                calls.append((role, payload))
                output = super().complete(role, guide, payload, contract)
                if role == 'marks' and not raw:
                    raw.append(json.dumps({'result_json': json.dumps(output)}))
                    raise CodexError(LEGACY_MESSAGE)
                return output

        self.e.model = Model()
        with self.assertRaises(CodexError):
            self.e.run('2026-11-14', self.mid, evaluate_after=False)
        failed = self.s.latest('failed')
        pending = self.s.latest('agent_input')
        original = self.s.latest('leader_mandate_output')
        calls.clear()
        completed = self.e.resume(failed['id'], pending['id'], raw[0])
        self.assertEqual(completed['leader_mandate']['output_id'], original['id'])
        self.assertEqual(len(self.s.events('leader_mandate_output')), 1)
        self.assertEqual(calls[0][0], 'marks')
        self.assertTrue(all(payload.get('analysis_stage') != 'leader_mandate' for _, payload in calls))
        self.assertEqual(calls[0][1]['leader_mandate'], pending['body']['payload']['leader_mandate'])
        from mara.evaluation import evaluate_report
        evaluate_report(self.s, self.e.model, completed['event_id'])
        self.assertNotIn('leader_mandate', calls[-1][1]['report'])

    def test_leader_revisit_reaches_original_author_then_revalidates_the_reply(self):
        calls = []

        class Model(DemoModel):
            leader_mandate_version = VERSION

            def complete(self, role, guide, payload, contract):
                calls.append((role, payload))
                result = super().complete(role, guide, payload, contract)
                if role == 'leader' and 'submission_sources' in payload and not payload.get('leader_revision_history'):
                    source = payload['submission_sources']['marks']
                    result['revision_requests'] = [{
                        'id': 'reconsider-stress', 'target_role': 'marks', 'source_output_id': source['output_id'],
                        'issue_path': '/thesis', 'kind': 'analysis_reassessment', 'reason': 'Clarify the base shock',
                        'requested_change': 'Reconsider down-case assumption', 'acceptance': 'State the countercase',
                        'question_ids': ['portfolio-allocation'], 'fact_ids': [],
                    }]
                if role == 'marks' and payload.get('revision_instructions'):
                    result['thesis'] = 'Maintained original risk estimate after rechecking the countercase'
                return result

        self.e.model = Model()
        result = self.e.run('2026-11-14', self.mid, evaluate_after=False)
        marks = [payload for role, payload in calls if role == 'marks']
        self.assertEqual(len(marks), 2)
        self.assertNotIn('perspectives', marks[-1])
        work = marks[-1]['revision_instructions'][0]['leader_review_request']
        self.assertEqual(work['requested_change'], 'Reconsider down-case assumption')
        self.assertEqual(work['acceptance'], 'State the countercase')
        self.assertEqual(len([1 for role, _ in calls if role == 'buffett']), 1)
        final_leader = [payload for role, payload in calls if role == 'leader' and payload.get('leader_revision_history')][-1]
        self.assertEqual(final_leader['leader_revision_history'][0]['source_leader_output_id'], work['output_id'])
        self.assertEqual(final_leader['perspectives']['marks']['thesis'], result['perspectives']['marks']['thesis'])
        validators = [payload for role, payload in calls if role == 'validation']
        self.assertEqual([p['analysis_stage'] for p in validators],
                         ['perspective_validation', 'perspective_validation', 'final_validation'])
        self.assertEqual(validators[-1]['perspectives']['marks']['thesis'], result['perspectives']['marks']['thesis'])
        self.assertFalse(result['proposal'].get('revision_requests'))

    def test_revised_evidence_report_uses_body_and_id_of_same_accepted_output(self):
        leader_inputs = []

        class Model(DemoModel):
            leader_mandate_version = VERSION

            def complete(self, role, guide, payload, contract):
                result = super().complete(role, guide, payload, contract)
                if role == 'evidence' and payload.get('revision_instructions'):
                    result['summary'] = 'Revised market observation after reviewing the original source'
                if role == 'leader' and 'submission_sources' in payload:
                    leader_inputs.append(payload)
                    source = payload['submission_sources']['evidence']
                    if len(leader_inputs) == 1:
                        result['revision_requests'] = [{
                            'id': 'review-original-source', 'target_role': 'evidence', 'source_output_id': source['output_id'],
                            'issue_path': '/summary', 'kind': 'analysis_reassessment', 'reason': 'Clarify original observation',
                            'requested_change': 'Reconsider the scope of the observation', 'acceptance': 'State observation limits',
                            'question_ids': [], 'fact_ids': [],
                        }]
                return result

        self.e.model = Model()
        result = self.e.run('2026-11-14', self.mid, evaluate_after=False)
        initial = result['evidence_feedback']['initial_evidence']
        final = result['market_observations']
        self.assertNotEqual(final['output_id'], initial['output_id'])
        self.assertNotEqual(final['analysis']['summary'], initial['analysis']['summary'])
        output = self.s.get(final['output_id'])['body']
        self.assertEqual(final['analysis'], output['output'])
        self.assertEqual(final['stage'], self.s.get(output['input_id'])['body']['payload']['analysis_stage'])
        self.assertEqual(leader_inputs[-1]['evidence_analysis'], final['analysis'])
