import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mara.agents import CONTRACTS,validate_output
from mara.codex_model import CodexModel,CodexError,environment,run_process
from mara.onboarding import PortfolioSetup,InputError

READY={'installed':True,'compatible':True,'authenticated':True,'version':'0.169.0'}
RESULT={'summary':'검증용 분석','constraints':[],'missing':[]}


class CodexTests(unittest.TestCase):
    def model(self,runner,model=''):
        with patch('mara.codex_model.status',return_value=READY),patch('mara.codex_model.executable',return_value='/test/codex'):
            return CodexModel(model,runner)

    @staticmethod
    def reply(command,result=RESULT):
        path=Path(command[command.index('-o')+1])
        path.write_text(json.dumps({'result_json':json.dumps(result)}))

    def test_evaluator_wire_resolves_to_the_exact_source_document(self):
        from mara.model_wire import INSTRUCTION,unpacked,VERSION
        payload={'original':['source text '*1000,0,False,None], 'again':['source text '*1000,0,False,None]}
        def runner(command,prompt,directory,timeout):
            wire=json.loads(prompt.split(INSTRUCTION,1)[1])
            self.assertEqual(wire['version'],VERSION)
            self.assertEqual(unpacked(wire),{'role_guide':'guide','contract':CONTRACTS['context'],'input':payload})
            self.assertLess(len(prompt),1048576)
            self.reply(command)
            return json.dumps({'type':'turn.completed'})
        for role in ('evaluator','evidence','buffett','leader','validation'):
            self.assertEqual(self.model(runner).complete(role,'guide',payload,CONTRACTS['context']),RESULT)

    def test_independent_private_calls_with_no_shell_or_credentials(self):
        calls=[]
        def runner(command,prompt,directory,timeout):
            calls.append(directory)
            self.assertEqual(command[-1],'-')
            self.assertNotIn('private user context',str(command))
            self.assertIn('private user context',prompt)
            for flag in ['--no-daemon','--ignore-user-config','--ephemeral','--skip-git-repo-check']:self.assertIn(flag,command)
            self.assertEqual(command[command.index('--sandbox')+1],'read-only')
            self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',command)
            self.assertIn('shell_tool',command);self.assertIn('apps',command);self.assertIn('plugins',command)
            self.assertEqual(Path(directory).stat().st_mode&0o777,0o700)
            self.assertEqual(Path(command[command.index('--output-schema')+1]).stat().st_mode&0o777,0o600)
            self.reply(command)
            return json.dumps({'type':'turn.completed'})
        model=self.model(runner)
        for role in ['context','evidence']:
            result=model.complete(role,'private user context',{},CONTRACTS['context'])
            validate_output('context',result,{})
        self.assertNotEqual(calls[0],calls[1]);self.assertTrue(all(not Path(x).exists() for x in calls))
        self.assertEqual(model.identity['provider'],'codex-cli')
        with patch.dict(os.environ,{'TOSS_CLIENT_SECRET':'private','MARA_API_KEY':'private','CODEX_THREAD_ID':'private'}):
            env=environment();self.assertNotIn('TOSS_CLIENT_SECRET',env);self.assertNotIn('MARA_API_KEY',env);self.assertNotIn('CODEX_THREAD_ID',env)

    def test_missing_completion_bad_json_and_tool_calls_rejected(self):
        traces=[json.dumps({'type':'turn.failed'}),json.dumps({'type':'thread.started'}),
                json.dumps({'type':'item.completed','item':{'type':'command_execution'}})+'\n'+json.dumps({'type':'turn.completed'})]
        for trace in traces:
            def runner(command,*args):self.reply(command);return trace
            with self.assertRaises(CodexError):self.model(runner).complete('context','',{},CONTRACTS['context'])
        def malformed(command,*args):
            Path(command[command.index('-o')+1]).write_text('private malformed content')
            return json.dumps({'type':'turn.completed'})
        with self.assertRaises(CodexError) as cm:self.model(malformed).complete('context','',{},CONTRACTS['context'])
        self.assertNotIn('private malformed',str(cm.exception))

    def test_narrative_provider_bound_matches_validated_output_budget(self):
        result={'text':'가'*30000}
        def runner(command,*args):
            self.reply(command,result);return json.dumps({'type':'turn.completed'})
        model=self.model(runner)
        self.assertEqual(model.complete('leader','',{'narrative_contract':'mara.judgment-report/1.0'},{}),result)
        with self.assertRaises(CodexError):model.complete('leader','',{}, {})
        result['text']='가'*39000
        with self.assertRaises(CodexError):model.complete('leader','',{'narrative_contract':'mara.judgment-report/1.0'}, {})

    def test_detailed_reports_have_a_bounded_longer_deadline(self):
        deadlines=[]
        def runner(command,prompt,directory,timeout):
            deadlines.append(timeout);self.reply(command);return json.dumps({'type':'turn.completed'})
        model=self.model(runner)
        model.complete('context','',{}, {})
        model.complete('leader','',{'narrative_contract':'mara.judgment-report/1.0'}, {})
        model.complete('marks','',{'market':{'source_text':'x'*260000}}, {})
        self.assertEqual(deadlines,[300,900,900])

    def test_calibrated_validation_size_boundaries_match_provider_and_agent(self):
        from mara.domain import dumps
        from mara.output_budget import characters
        payload={'analysis_stage':'perspective_validation',
                 'decision_policy':{'schema_version':'mara.decision-calibration/1.0'},
                 'market':{'facts':[]}}
        def result_at(size):
            obj={'issues':['x'*11000,'y'*11000], 'unsupported_claims':[],
                 'qualitative_pass':False,'reason':'r','decision_gaps':[],
                 'knowledge_feedback':[]}
            obj['reason']='r'*(1+size-len(dumps(obj)))
            self.assertEqual(len(dumps(obj)),size)
            return obj
        for p,limit in ((payload,38000),({},24000)):
            for size in (24000,24001,38000,38001):
                result=result_at(size)
                def runner(command,*args):
                    self.reply(command,result);return json.dumps({'type':'turn.completed'})
                if size<=limit:
                    self.assertEqual(self.model(runner).complete('validation','',p,{}),result)
                    validate_output('validation',result,p)
                else:
                    with self.assertRaises(CodexError):self.model(runner).complete('validation','',p,{})
                    with self.assertRaisesRegex(ValueError,'too large'):validate_output('validation',result,p)
        for role,p in [('evidence',payload),('validation',dict(payload,analysis_stage='research_plan')),
                       ('validation',dict(payload,analysis_stage=None)),
                       ('validation',dict(payload,decision_policy={'schema_version':'unsupported'}))]:
            self.assertEqual(characters(role,p),24000)
        self.assertEqual(characters('leader',{'narrative_contract':'mara.judgment-report/1.0'}),38000)
        result=result_at(28000)
        def padded_raw(command,*args):
            self.reply(command,result)
            path=Path(command[command.index('-o')+1]);path.write_text(path.read_text()+' '*131073)
            return json.dumps({'type':'turn.completed'})
        with self.assertRaises(CodexError):self.model(padded_raw).complete('validation','',payload,{})

    def test_larger_validation_budget_keeps_fact_integrity_checks(self):
        from mara.contracts import ContractError
        payload={'analysis_stage':'perspective_validation',
                 'decision_policy':{'schema_version':'mara.decision-calibration/1.0'},
                 'market':{'facts':[]},'decision_scope':{'questions':[{'id':'q'}]}}
        result={'issues':['x'*14000], 'unsupported_claims':[], 'qualitative_pass':False,
                'reason':'r'*14000,'knowledge_feedback':[],
                'decision_gaps':[{'question_id':'q','kind':'fact_verification','cause':'not_extracted',
                'status':'unresolved','subject':'Synthetic gap','affects_selected':False,
                'reason':'Missing source','resolution_condition':'Read the source',
                'next_action':'Research','fact_ids':['invented'],'calculation_paths':[]}]}
        with self.assertRaisesRegex(ContractError,'gap_sources'):validate_output('validation',result,payload)

    def test_logged_out_and_unsupported_cli_fail_before_analysis(self):
        for update in [{'installed':False},{'compatible':False},{'authenticated':False}]:
            with patch('mara.codex_model.status',return_value=dict(READY,**update)):
                with self.assertRaises(CodexError):CodexModel()

    def test_model_argument_injection_rejected(self):
        with self.assertRaises(CodexError):self.model(None,'--dangerously-bypass-approvals-and-sandbox')

    def test_subprocess_timeout_and_safe_provider_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(CodexError,'시간이 초과'):
                run_process([sys.executable,'-c','import time; time.sleep(5)'],'',tmp,0.05)
            for error,expected in [('401 secret-token','로그인'),('rate_limit secret-token','사용 한도'),('private raw content','실행에 실패')]:
                with self.assertRaisesRegex(CodexError,expected) as cm:
                    run_process([sys.executable,'-c','import sys;sys.stderr.write(sys.argv[1]);sys.exit(1)',error],'',tmp,5)
                self.assertNotIn('secret-token',str(cm.exception));self.assertNotIn('private raw',str(cm.exception))


class ProviderSettingsTests(unittest.TestCase):
    def test_codex_selection_uses_login_and_no_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=PortfolioSetup(Path(tmp)/'service')
            with patch('mara.onboarding.codex_status',return_value=READY):
                state=app.save_model({'provider':'codex','model':''})
                self.assertTrue(state['configured']);self.assertEqual(state['provider'],'codex')
                self.assertNotIn('api_key',json.loads(app.model_path.read_text()))
                with patch('mara.onboarding.CodexModel') as factory:
                    app.analysis_model();factory.assert_called_once_with('')
                again=PortfolioSetup(app.directory);self.assertEqual(again.model_state()['provider'],'codex')
            with patch('mara.onboarding.codex_status',return_value=dict(READY,authenticated=False)):
                self.assertFalse(app.model_state()['configured'])
                with self.assertRaisesRegex(InputError,'로그인'):app.save_model({'provider':'codex','model':''})

    def test_switching_keeps_api_secret_private_and_stops_during_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=PortfolioSetup(Path(tmp)/'service')
            app.save_model({'model':'api-model','api_key':'private-test-key'})
            with patch('mara.onboarding.codex_status',return_value=READY):
                state=app.save_model({'provider':'codex','model':'custom-model'})
                self.assertNotIn('private-test-key',json.dumps(state))
                self.assertNotIn('api_key',state)
                self.assertEqual(json.loads(app.model_path.read_text())['api_key'],'private-test-key')
            app.save_model({'provider':'openai','model':'api-model','api_key':''})
            self.assertEqual(app.model_state()['provider'],'openai')
            self.assertEqual(app.model_path.stat().st_mode&0o777,0o600)

if __name__=='__main__':unittest.main()

class ProviderBoundaryTests(unittest.TestCase):
    model=CodexTests.model
    reply=staticmethod(CodexTests.reply)
    def test_provider_completion_and_json_errors_are_distinct_and_keep_original(self):
        from mara.codex_model import ProviderSubmissionError
        cases=[('trace_item_shape',json.dumps({'type':'item.completed','item':None}),{'result_json':json.dumps(RESULT)}),
            ('trace_item_shape',json.dumps({'type':'item.completed','item':[]}),{'result_json':json.dumps(RESULT)}),
            ('trace_json','not-json',{'result_json':json.dumps(RESULT)}),
            ('completion_unverified',json.dumps({'type':'thread.started'}),{'result_json':json.dumps(RESULT)}),
            ('response_json',json.dumps({'type':'turn.completed'}),{'result_json':'{"summary":'}),
            ('output_budget',json.dumps({'type':'turn.completed'}),{'result_json':json.dumps(dict(RESULT,summary='x'*25000))})]
        for reason,trace,raw in cases:
            def runner(command,prompt,directory,timeout):
                Path(command[command.index('-o')+1]).write_text(json.dumps(raw));return trace
            with self.subTest(reason=reason),self.assertRaises(ProviderSubmissionError) as cm:
                self.model(runner).complete('context','guide',{},CONTRACTS['context'])
            self.assertEqual(cm.exception.diagnostic['reason'],reason)
            self.assertEqual(json.loads(cm.exception.raw_response),raw)
    def test_turn_failed_or_error_is_not_a_retryable_submission(self):
        from mara.codex_model import ProviderSubmissionError
        for kind in ('turn.failed','error'):
            def runner(command,prompt,directory,timeout):
                self.reply(command);return json.dumps({'type':kind,'message':'quota or authentication failure'})
            with self.assertRaises(CodexError) as cm:self.model(runner).complete('context','guide',{},CONTRACTS['context'])
            self.assertNotIsInstance(cm.exception,ProviderSubmissionError)
