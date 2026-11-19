import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mara.codex_model import CodexModel,CodexError
from mara.contracts import output_schema,schema
from mara.model_routing import load_policy,select,POLICY_PATH
from mara.registry import personas
from mara.submission_recovery import contract as recovery_contract

READY={'installed':True,'compatible':True,'authenticated':True,'version':'0.169.0'}

class RoutingTests(unittest.TestCase):
    def setUp(self):
        fixture=Path(__file__).parent/'fixtures/model-routing.json'
        self.policy=load_policy(fixture)
        patcher=patch('mara.model_routing.POLICY_PATH',fixture);patcher.start();self.addCleanup(patcher.stop)

    def test_task_and_effort_are_independent_and_plan_precedes_role(self):
        for role in ('validation','leader','buffett'):
            d=select(self.policy,role,{'analysis_stage':'final_validation'},{'properties':{'calls':{}}})
            self.assertEqual((d['model'],d['effort']),('gpt-6.2-sol','medium'))
        d=select(self.policy,'validation',{'analysis_stage':'perspective_validation'},{});
        self.assertEqual((d['model'],d['effort']),('gpt-6.2-astra','high'))
        d=select(self.policy,'validation',{'analysis_stage':'final_validation'},{});
        self.assertEqual((d['model'],d['effort']),('gpt-6.2-astra','high'))
        self.assertEqual(select(self.policy,'editor',{}, {})['effort'],'low')

    def test_override_diagnostics_and_no_recursive_escalation(self):
        from mara.decision_calibration import CalibrationError
        from mara.output_validation import issue_code
        exc=CalibrationError('future_fact','Future assumption is not an observed fact')
        p={'output_feedback':{'code':issue_code(exc),'decision_policy_error':exc.diagnostic}}
        d=select(self.policy,'buffett',p,{});self.assertTrue(d['escalated']);self.assertEqual(d['effort'],'high')
        d=select(self.policy,'buffett',p,{},'gpt-6-astra','low')
        self.assertEqual((d['model'],d['effort']),('gpt-6-astra','low'));self.assertFalse(d['escalated'])
        for code in ('judgment_report','market_evidence_reference','output_contract','provider_submission','quota','timeout'):
            self.assertFalse(select(self.policy,'buffett',{'output_feedback':{'code':code}}, {})['escalated'])
        from mara.research_questions import QuestionReviewError
        for reason in ('before_final_proposal','unknown_calculation','empty_calculation'):
            error=QuestionReviewError('q',reason)
            self.assertFalse(select(self.policy,'buffett',{'output_feedback':{'code':issue_code(error),'question_error':error.diagnostic}}, {})['escalated'])
        with self.assertRaises(ValueError):select(self.policy,'editor',{}, {},'unverified-model')

    def test_real_cli_argument_path_and_private_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[];log=Path(tmp)/'routing.jsonl'
            def runner(cmd,prompt,directory,timeout):
                calls.append(cmd);Path(cmd[cmd.index('-o')+1]).write_text(json.dumps({'result_json':'{}'}))
                return '{"type":"turn.completed"}'
            with patch('mara.codex_model.status',return_value=READY),patch('mara.codex_model.executable',return_value='/codex'):
                m=CodexModel(runner=runner,routing_log=log)
            sol, astra = 'gpt-6.2-sol', 'gpt-6.2-astra'
            cases = [
                (role, {'analysis_stage': role}, output_schema(role), astra, 'medium')
                for role in ('context', 'evidence', *personas(), 'reflection')
            ]
            cases += [
                ('leader', {'analysis_stage':'proposal_synthesis'}, output_schema('leader'), astra, 'high'),
                ('leader', {'analysis_stage':'submission_review'}, recovery_contract([]), astra, 'high'),
                ('editor', {}, {}, sol, 'low'),
                ('memory', {}, output_schema('memory'), sol, 'medium'),
                ('context', {}, schema('persona-reply'), sol, 'medium'),
                ('context', {}, {'$id':'urn:mara:persona-extraction:1.0'}, sol, 'low'),
                ('leader', {}, {'properties':{'calls':{}}}, sol, 'medium'),
            ]
            for role, payload, contract, _, _ in cases:
                m.complete(role, '', payload, contract)
            requested=[json.loads(l) for l in log.read_text().splitlines() if json.loads(l)['state']=='requested']
            self.assertEqual(len(requested), len(cases))
            self.assertEqual(len(calls), len(cases))
            self.assertEqual(log.stat().st_mode&0o777,0o600)
            for (role, payload, _, model, effort), command, receipt in zip(cases, calls, requested):
                with self.subTest(role=role, payload=payload):
                    self.assertEqual(command[command.index('--model')+1], model)
                    self.assertIn(f'model_reasoning_effort="{effort}"', command)
                    self.assertEqual((receipt['model'], receipt['effort']), (model, effort))
                    self.assertEqual(receipt['routing_rules'], m.identity['routing_rules'])
            previous_identity = {k:v for k,v in m.identity.items() if k != 'routing_rules'}
            self.assertNotEqual(m.identity, previous_identity)

    def test_failure_does_not_add_a_provider_attempt_and_legacy_identity_is_pinned(self):
        calls=[]
        def runner(*args):calls.append(1);raise CodexError('transport failure')
        with patch('mara.codex_model.status',return_value=READY),patch('mara.codex_model.executable',return_value='/codex'):
            m=CodexModel(runner=runner);old=CodexModel(runner=runner,legacy=True)
        with self.assertRaises(CodexError):m.complete('validation','',{'analysis_stage':'final_validation'}, {})
        self.assertEqual(len(calls),1);self.assertNotEqual(m.identity,old.identity)
        self.assertNotIn('routing_policy',old.identity);self.assertEqual(old.identity['model'],'CLI default')

    def test_policy_frozen_for_instance_and_override_effort_reaches_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'policy.json';p.write_text(json.dumps(self.policy));commands=[]
            def runner(cmd,*args):
                commands.append(cmd);Path(cmd[cmd.index('-o')+1]).write_text('{"result_json":"{}"}');return '{"type":"turn.completed"}'
            with patch('mara.codex_model.status',return_value=READY),patch('mara.codex_model.executable',return_value='/codex'):
                m=CodexModel('gpt-6-astra',runner,effort='low',policy_path=p)
            p.write_text('{}');m.complete('validation','',{'analysis_stage':'final_validation'}, {})
            self.assertIn('gpt-6-astra',commands[0]);self.assertIn('model_reasoning_effort="low"',commands[0])

    def test_engine_existing_second_submission_emits_typed_diagnostic_for_escalation(self):
        from mara.agents import Agents
        from mara.decision_calibration import CalibrationError
        policy=self.policy;selections=[];inputs=[]
        class Session:
            def append(self,kind,body,*args):inputs.append((kind,body));return str(len(inputs))
        class Model:
            identity={'model':'fixture'};mode='live'
            def complete(self,role,guide,payload,contract):
                selections.append(select(policy,role,payload,contract));return {}
        a=Agents(Session(),Model(),'2026-11-19','test')
        with patch('mara.submission_recovery.guard'),patch('mara.agents.validate_output',side_effect=[CalibrationError('future_fact','Assumption treated as fact'),{}]):
            a._submit('buffett','',{}, {},[],{},10000,False)
        self.assertEqual([s['effort'] for s in selections],['medium','high'])
        self.assertEqual(len([x for x in inputs if x[0]=='agent_input']),2)
        final=[x[1] for x in inputs if x[0]=='agent_validation'][-1]
        self.assertEqual(final['attempt'],2);self.assertEqual(final['status'],'accepted')
