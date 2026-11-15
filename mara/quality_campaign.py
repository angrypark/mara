"""Resumable baseline + five real generation/evaluation cycles. No order authority."""
import copy
import fcntl
import os
import marshal
import sys
import types
from contextlib import contextmanager
from pathlib import Path
import hashlib
import re
from datetime import date
from .domain import dumps
from .registry import resource
from .evaluation import evaluate_report,rubric,evaluator_fingerprint
from .engine import Engine


def sha(value):return hashlib.sha256(dumps(value).encode()).hexdigest()


def frozen_rules():
    files=['resources/evaluation-rubric.json','guides/roles/evaluator.md','guides/portfolio-report-benchmarks.md','contracts/agent-evaluator.schema.json','mara/strict_evaluation.py','mara/evaluation.py','mara/quality_campaign.py','mara/agents.py','mara/quantitative_verifier.py','mara/coverage.py','mara/decision.py','mara/contracts.py','guides/roles/research-tools.md','guides/roles/analysis-exhibits.md']
    return {path:hashlib.sha256(resource(path).read_bytes()).hexdigest() for path in files}


def code_manifest():
    root=resource('mara/engine.py').parent.parent
    files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for folder,glob in [('mara','*.py'),('guides','*.md'),('contracts','*.json')]
        for p in sorted((root/folder).rglob(glob))}
    runtime={}
    for name,module in sorted(sys.modules.items()):
        if not name.startswith('mara.'):continue
        for key,value in vars(module).items():
            if isinstance(value,types.FunctionType) and value.__module__==name:
                runtime[name+'.'+key]=hashlib.sha256(marshal.dumps(value.__code__)).hexdigest()
            elif isinstance(value,type) and value.__module__==name:
                for method,fn in vars(value).items():
                    if isinstance(fn,(staticmethod,classmethod)):fn=fn.__func__
                    if isinstance(fn,types.FunctionType):runtime[name+'.'+key+'.'+method]=hashlib.sha256(marshal.dumps(fn.__code__)).hexdigest()
    return {'filesystem':files,'loaded_python_code':runtime,
        'rule':'Filesystem snapshot and actually loaded Python code are separate; changing a file does not hot-reload a running interpreter.'}


def evidence_basis(session,event):
    report=event['body'];market=session.get(report['market_id'])
    extras=[x for x in session.events('research_evidence') if x['run_id']==event['run_id'] and x['seq']<=event['seq']]
    return {'market_id':market['id'],'market_hash':market['digest'],'profile_id':report['profile_id'],'actual_id':report['actual_id'],
        'supplemental_facts':{x['body']['fact']['id']:sha(x['body']['fact']) for x in extras},
        'analysis_hash':sha(report.get('analysis',{}))}


def feedback(evaluation):
    o=evaluation['output']
    return {'summary':o['summary'],'red_flags':o['red_flags'],
        'criteria':[{'id':x['id'],'reason':x['reason'],'missing':x['missing'],'improvements':x['improvements'],
            'unmet_checks':[c for c in x.get('checks',[]) if c['status']!='met']} for x in o['criteria']],
        'gates':[g for g in o.get('gates',[]) if g['status']!='pass'],
        'coverage':[x for x in o.get('coverage',[]) if x['status']!='supported'],
        'deterministic_findings':evaluation['score'].get('deterministic_findings',[]),
        'instruction':'구체 결함을 원문/계산으로 해소하고 반대 근거를 보존해요. 불가능하면 원인·다음 행동을 명시해요. 점수나 특정 매수 결론을 목표로 삼지 않아요.'}


class Campaign:
    def __init__(self,session,model,research_library=None):self.s,self.model,self.library=session,model,research_library

    def events(self,kind,campaign_id):return [e for e in self.s.events(kind) if e['body']['campaign_id']==campaign_id]

    @contextmanager
    def operation(self):
        # OS releases the lock on process death; no abandoned persistent lease.
        db_path=Path(self.s.store.db.execute('PRAGMA database_list').fetchone()[2])
        path=db_path.parent/('.quality-'+hashlib.sha256(self.s.owner.encode()).hexdigest()[:24]+'.lock')
        fd=os.open(path,os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,'a') as handle:
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('Quality campaign already running for this user') from None
            try:yield
            finally:fcntl.flock(handle,fcntl.LOCK_UN)

    def start(self,baseline_id,campaign_id):
        with self.operation():return self._start(baseline_id,campaign_id)

    def _start(self,baseline_id,campaign_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',campaign_id):raise ValueError('Invalid campaign identity')
        previous=self.events('quality_campaign',campaign_id)
        if previous:
            if previous[0]['body']['baseline_id']!=baseline_id:raise ValueError('Campaign request identity conflict')
            return previous[0]['body']
        event=self.s.get(baseline_id)
        if event['kind']!='completed' or self.s.latest('completed')['id']!=baseline_id:raise ValueError('Start from the latest completed report')
        state={'campaign_id':campaign_id,'baseline_id':baseline_id,'as_of':event['effective'],'rounds_required':5,
            'rules':frozen_rules(),'rubric_hash':sha(rubric()),'provider':self.model.identity,
            'evaluator_spec_hash':evaluator_fingerprint(self.s,self.model,event['effective']),
            'baseline_basis':evidence_basis(self.s,event),'initial_code_manifest':code_manifest(),
            'definition':'baseline assessment, then improvement -> full decision flow -> independent assessment five times; failed attempts retained',
            'authority':'analysis only; no orders or actual holding changes'}
        self.s.append('quality_campaign',state,date.today().isoformat())
        return state

    def run(self,campaign_id,progress=lambda value:None,through_round=5):
        with self.operation():
            try:return self._run(campaign_id,progress,through_round)
            except Exception as exc:
                campaigns=self.events('quality_campaign',campaign_id);points=self.events('quality_checkpoint',campaign_id)
                if campaigns and (not points or points[-1]['body']['status']!='failed'):
                    done={e['body']['round'] for e in self.events('quality_round',campaign_id)}
                    round_no=next((n for n in range(6) if n not in done),5)
                    self.s.append('quality_checkpoint',{'campaign_id':campaign_id,'round':round_no,'stage':'preflight','status':'failed','error_type':type(exc).__name__},campaigns[0]['body']['as_of'])
                raise

    def use_market(self,campaign_id,market_id,reason):
        if not isinstance(reason,str) or not reason.strip():raise ValueError('Source revision reason required')
        with self.operation():
            state=self.events('quality_campaign',campaign_id)[0]['body'];event=self.s.get(market_id)
            if event['kind']!='market' or event['effective']!=state['as_of']:raise ValueError('Source pack must have the frozen decision date')
            done={e['body']['round'] for e in self.events('quality_round',campaign_id)}
            next_round=next((i for i in range(1,6) if i not in done),None)
            if next_round is None:raise ValueError('Campaign already has all five improvements')
            return self.s.append('quality_source_update',{'campaign_id':campaign_id,'before_round':next_round,
                'market_id':market_id,'market_hash':event['digest'],'reason':reason},state['as_of'])

    def recover_interrupted_execution(self,campaign_id,as_of):
        # Only called while holding this user's exclusive OS campaign lock.
        # Ordinary user analyses and other campaigns are never unlocked here.
        locked=self.s.store.db.execute('SELECT run_id FROM locks WHERE owner=?',(self.s.owner,)).fetchone()
        if not locked:return
        run_id=locked['run_id']
        intents=[e for e in self.s.events('execution_intent') if e['run_id']==run_id and e['body'].get('campaign_id')==campaign_id]
        starts=[e for e in self.s.events('run_started') if e['run_id']==run_id and (e['body'].get('improvement') or {}).get('campaign_id')==campaign_id]
        evaluations=[e for e in self.events('quality_checkpoint',campaign_id) if e['body'].get('stage')=='evaluation'
            and e['body'].get('status')=='running' and run_id=='quality-'+campaign_id+'-'+str(e['body']['round'])]
        if not (intents or starts or evaluations):raise RuntimeError('Another execution owns the portfolio lock; campaign cannot recover it')
        with self.s.store.transaction():
            self.s.append('recovery',{'run_id':run_id,'campaign_id':campaign_id,
                'reason':'Exclusive campaign OS lock reacquired after interruption; recovered only its recorded execution'},as_of,run_id)
            self.s.store.db.execute('DELETE FROM locks WHERE owner=? AND run_id=?',(self.s.owner,run_id))

    def _run(self,campaign_id,progress,through_round):
        if type(through_round) is not int or not 0<=through_round<=5:raise ValueError('Round limit must be 0..5')
        records=self.events('quality_campaign',campaign_id)
        if not records:raise ValueError('Unknown campaign')
        state=records[0]['body'];as_of=state['as_of']
        if frozen_rules()!=state['rules'] or self.model.identity!=state['provider']:raise ValueError('Frozen evaluation rules or model changed; new campaign required')
        self.recover_interrupted_execution(campaign_id,as_of)
        completed={e['body']['round']:e['body'] for e in self.events('quality_round',campaign_id)}
        parent_id=state['baseline_id']
        for round_no in range(through_round+1):
            if round_no in completed:
                parent_id=completed[round_no]['completed_id'];continue
            if frozen_rules()!=state['rules'] or evaluator_fingerprint(self.s,self.model,as_of)!=state['evaluator_spec_hash']:raise ValueError('Evaluation rules changed during campaign')
            stage='generation' if round_no else 'evaluation'
            self.s.append('quality_checkpoint',{'campaign_id':campaign_id,'round':round_no,'stage':stage,'status':'running','parent_completed_id':parent_id},as_of)
            progress({'round':round_no,'stage':stage,'status':'running'})
            try:
                if round_no:
                    prior=completed[round_no-1]
                    evaluation=self.s.get(prior['evaluation_event_id'])['body']
                    # Recovery includes a crash after completed was stored but before the checkpoint.
                    generated=[e for e in self.s.events('completed') if (e['body'].get('improvement') or {}).get('campaign_id')==campaign_id
                        and e['body']['improvement']['round']==round_no]
                    if generated:event=generated[-1]
                    else:
                        if self.s.latest('completed')['id']!=parent_id:raise ValueError('Newer user decision exists; preserve this campaign as a historical branch')
                        improvement={'campaign_id':campaign_id,'round':round_no,'parent_completed_id':parent_id,
                            'evaluation_event_id':prior['evaluation_event_id'],'feedback':feedback(evaluation),
                            'previous_proposal':copy.deepcopy(self.s.get(parent_id)['body']['proposal']),
                            'allow_supplemental_research':True,
                            'pack_policy':'Keep original basis; any newly read same-date evidence is separately recorded and hashed in this round, never inserted into earlier records.'}
                        updates=[e for e in self.events('quality_source_update',campaign_id) if e['body']['before_round']==round_no]
                        if updates:improvement['market_id']=updates[-1]['body']['market_id'];improvement['source_revision_reason']=updates[-1]['body']['reason']
                        result=Engine(self.s,self.model,self.library).run(as_of,force=True,
                            revision_reason='독립 평가 지적 재검토 '+str(round_no),improvement=improvement,evaluate_after=False)
                        event=self.s.get(result['event_id'])
                else:event=self.s.get(parent_id)
                if evaluator_fingerprint(self.s,self.model,as_of)!=state['evaluator_spec_hash']:raise ValueError('Effective evaluator guide or skills changed during campaign')
                stage='evaluation'
                self.s.append('quality_checkpoint',{'campaign_id':campaign_id,'round':round_no,'stage':'evaluation','status':'running','completed_id':event['id']},as_of)
                progress({'round':round_no,'stage':'evaluation','status':'running'})
                # Q1 cannot race another proposal. Its payload removes earlier feedback and scores.
                lock='quality-'+campaign_id+'-'+str(round_no)
                self.s.lock(lock)
                try:
                    result=evaluate_report(self.s,self.model,event['id'])
                finally:self.s.unlock(lock)
                if result['evaluator_spec_hash']!=state['evaluator_spec_hash']:raise ValueError('Evaluation specification changed; this invocation cannot count toward the campaign')
                evaluations=[e for e in self.s.events('report_evaluation') if e['body']['completed_id']==event['id'] and e['body']['rubric_hash']==state['rubric_hash']]
                evaluation_event=evaluations[-1];output=self.s.get(result['output_id']);inp=self.s.get(output['body']['input_id'])
                row={'campaign_id':campaign_id,'round':round_no,'completed_id':event['id'],'parent_completed_id':parent_id if round_no else None,
                    'run_id':event['run_id'],'evaluation_event_id':evaluation_event['id'],'evaluator_input_id':inp['id'],'evaluator_output_id':output['id'],
                    'evaluator_input_hash':inp['digest'],'evaluator_output_hash':output['digest'],'recorded_at':evaluation_event['recorded'],
                    'rules':state['rules'],'rubric_hash':state['rubric_hash'],'provider':self.model.identity,
                    'evaluator_spec_hash':result['evaluator_spec_hash'],
                    'evidence_basis':evidence_basis(self.s,event),'code_manifest':code_manifest(),'score':result['score'],
                    'changes':event['body']['proposal']['premise_changes'] if round_no else [],
                    'source_independence':'new evaluator invocation for this immutable target; same configured model can have correlated errors'}
                if any(x['evaluator_output_id']==row['evaluator_output_id'] for x in completed.values()):raise ValueError('Cached evaluation cannot count as a new round')
                eid=self.s.append('quality_round',row,as_of,event['run_id']);row['event_id']=eid
                completed[round_no]=row;parent_id=event['id']
                self.s.append('quality_checkpoint',{'campaign_id':campaign_id,'round':round_no,'stage':'evaluation','status':'completed','completed_id':event['id']},as_of,event['run_id'])
                progress({'round':round_no,'stage':'evaluation','status':'completed','score':result['score']})
            except Exception as exc:
                self.s.append('quality_checkpoint',{'campaign_id':campaign_id,'round':round_no,'stage':stage,'status':'failed','error_type':type(exc).__name__},as_of)
                raise
        return self.status(campaign_id)

    def status(self,campaign_id):
        rounds=[e['body'] for e in self.events('quality_round',campaign_id)];points=self.events('quality_checkpoint',campaign_id)
        finished=len(rounds)==6 and {r['round'] for r in rounds}==set(range(6)) and len({r['evaluator_output_id'] for r in rounds})==6
        last=rounds[-1] if rounds else None
        return {'schema_version':'mara.quality-campaign/1.0.0','campaign_id':campaign_id,'G6':'pass' if finished else 'unknown',
            'completed_improvements':len([r for r in rounds if r['round']>0]),'required_improvements':5,
            'strict_quality_pass':bool(finished and last['score'].get('strict_pass')),
            'checkpoint':points[-1]['body'] if points else None,'rounds':rounds}


def projection(session,report_id,run_id=None):
    relevant=[]
    rounds=session.events('quality_round')
    linked=None
    if report_id:linked=(session.get(report_id)['body'].get('improvement') or {}).get('campaign_id')
    if not linked and run_id:
        starts=[e for e in session.events('run_started') if e['run_id']==run_id]
        if starts:linked=(starts[-1]['body'].get('improvement') or {}).get('campaign_id')
    for event in session.events('quality_campaign'):
        c=event['body']
        if c['campaign_id']==linked or c['baseline_id']==report_id or any(r['body']['campaign_id']==c['campaign_id'] and r['body']['completed_id']==report_id for r in rounds):relevant.append(c)
    if not relevant:return None
    status=Campaign(session,None).status(relevant[-1]['campaign_id'])
    status['rounds']=[{k:v for k,v in row.items() if k in ('round','completed_id','parent_completed_id','run_id','evaluation_event_id','evaluator_input_id','evaluator_output_id','evaluator_input_hash','evaluator_output_hash','rubric_hash','recorded_at','score','changes','source_independence')} for row in status['rounds']]
    return status
