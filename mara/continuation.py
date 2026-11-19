"""Verified initial-perspective continuation, never regeneration of accepted prefixes."""
import copy,hashlib,os,subprocess
from pathlib import Path
from .domain import dumps
from . import history
from .registry import personas
from .agents import validate_output
from .contracts import validate
from .codex_model import ProviderSubmissionError

VERSION='mara.execution-continuation/1.0'
LEGACY_MESSAGE='Codex 분석 결과가 필요한 JSON 형식에 맞지 않아요. 다시 시도해주세요.'

def resource_fingerprint():
 root=Path(__file__).resolve().parent.parent
 return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for directory in ('guides','contracts') for p in sorted((root/directory).rglob('*')) if p.is_file() and (directory!='contracts' or p.suffix=='.json')}

def process_birth(pid):
 try:return subprocess.check_output(['ps','-p',str(pid),'-o','lstart='],text=True,stderr=subprocess.DEVNULL).strip()
 except (OSError,subprocess.CalledProcessError):return ''

def alive(body):
 return bool(body.get('pid') and body.get('process_birth') and process_birth(body['pid'])==body['process_birth'])

def prepare(session,model,failed_id,response_input_id,raw_response,resource_manifest=None):
 """Read-only eligibility, prefix and exact pending-input verification."""
 failure=session.get(failed_id);run=failure['run_id']
 if failure['kind']!='failed' or failure['body'].get('error_type')!='CodexError' or failure['body'].get('message')!=LEGACY_MESSAGE:
  raise ValueError('Continuation requires the known legacy provider-submission boundary failure')
 ev=[session.decode(r) for r in session.store.db.execute('SELECT * FROM events WHERE owner=? AND run_id=? ORDER BY seq',(session.owner,run))]
 if any(e['kind'] in ('completed','continuation_started') for e in ev):raise ValueError('Execution already completed or continuation already attempted')
 if [e['id'] for e in ev if e['kind']=='failed']!=[failed_id]:raise ValueError('Ambiguous original failure sequence')
 starts=[e for e in ev if e['kind']=='run_started']
 if len(starts)!=1:raise ValueError('Exactly one original start required')
 start=starts[0];b=start['body']
 resources=b.get('runtime_resources') or resource_manifest
 if not resources or resources!=resource_fingerprint():raise ValueError('Original guide/contract resource snapshot differs or is unavailable')
 if b['mode']!=model.mode or b['history_scope']!=history.scope(session):raise ValueError('Continuation owner mode/history changed')
 previous=history.latest(session,'completed',boundary=b['history_scope'])
 if (previous['id'] if previous else None)!=b['previous_id']:raise ValueError('A newer completed report exists')
 if b.get('amendment') or b.get('improvement') or b.get('external_review'):raise ValueError('Frozen/review branch continuation is unsupported')
 sensitive={'profile','actual','cashflow','history_reset','knowledge','user_persona','clarification_answer','quality_stability_result'}
 for kind in sensitive:
  if any(e['seq']>start['seq'] and (kind!='knowledge' or e['run_id']!=run or e['seq']>failure['seq']) for e in session.events(kind)):raise ValueError('Personal/history/knowledge state changed outside the verified prefix')
 if any(e['kind'] in ('recovery_leader_input','evidence_feedback_dispatch','recovery_research_dispatch') for e in ev):raise ValueError('Continuation after feedback or coordinated recovery is unsupported')
 if any(e['kind']=='agent_input' and e['body']['role'] in ('leader','validation') for e in ev):raise ValueError('Continuation after synthesis/validation is unsupported')
 inputs=[e for e in ev if e['kind']=='agent_input'];pending=inputs[-1];role=pending['body']['role']
 if pending['id']!=response_input_id or role not in personas() or pending['seq']>=failure['seq']:raise ValueError('Response must belong to the first unfinished perspective input')
 if any(e['kind']=='agent_output' and e['body']['input_id']==pending['id'] for e in ev):raise ValueError('Pending input already has an output')
 if not isinstance(raw_response,str) or not raw_response or len(raw_response.encode())>524288:raise ValueError('Bounded original unverified response required')
 if any(pending['body']['payload'].get(k) for k in ('output_feedback','submission_repair','revision_instructions')):raise ValueError('Only an interrupted first submission is supported; repair budget cannot reset')
 if pending['body']['provider']!=model.identity:raise ValueError('Provider identity changed')
 accepted=[];by_role={}
 for e in ev:
  if e['kind']!='agent_validation' or e['body']['status']!='accepted':continue
  out=session.get(e['body']['output_id']);inp=session.get(out['body']['input_id'])
  if any(x['owner']!=session.owner or x['run_id']!=run for x in (out,inp)) or not inp['seq']<out['seq']<e['seq']<failure['seq']:raise ValueError('Accepted prefix lineage mismatch')
  if out['body'].get('provider_failure'):raise ValueError('Unattested provider result cannot be reused')
  if hashlib.sha256(inp['body']['guide'].encode()).hexdigest()!=inp['body']['guide_hash']:raise ValueError('Original guide hash mismatch')
  validate(out['body']['output'],inp['body']['contract']);validate_output(out['body']['role'],out['body']['output'],inp['body']['payload'])
  accepted.append(out);by_role.setdefault(out['body']['role'],[]).append(out)
 roles=list(personas());expected=set(roles[:roles.index(role)])
 if {r for r in by_role if r in roles}!=expected or not {'context','evidence'}<=by_role.keys():raise ValueError('Accepted perspectives must be an uninterrupted prefix')
 if any(len(by_role.get(r,[]))!=1 for r in expected|{'context','evidence'}):raise ValueError('Ambiguous accepted prefix')
 if by_role['context'][0]['body']['output']['missing']:raise ValueError('Context remains unresolved')
 audit=[e for e in ev if e['kind']=='pruning_audit']
 if len(audit)!=1:raise ValueError('Original knowledge pruning must be complete exactly once')
 h=[e for e in ev if e['kind']=='research_feedback_history'];scope=[e for e in ev if e['kind']=='decision_scope']
 if len(scope)!=1 or (previous and len(h)!=1):raise ValueError('Original scope/history snapshot unavailable')
 learning={'status':'no_predecessor','history_event_id':h[0]['id'] if h else None,'source_completed_id':b['previous_id'],
  'reflection_output_id':None,'memory_outputs':[],'applications':[]}
 reflection=None
 if previous:
  if len(by_role.get('reflection',[]))!=1 or not by_role.get('memory'):raise ValueError('Original learning prefix is incomplete')
  ref=by_role['reflection'][0];reflection=ref['body']['output']
  learning.update(status='reviewed',reflection_output_id=ref['id'],reflection_input_id=ref['body']['input_id'])
  for out in by_role['memory']:
   value=out['body']['output'];learning['memory_outputs'].append({'output_id':out['id'],'input_id':out['body']['input_id'],'learning_applications':value.get('learning_applications',[]),'conflicts':value.get('conflicts',[])})
   for i,op in enumerate(value['operations']):
    matches=[e for e in ev if e['kind']=='research_learning_application' and e['body']['memory_output_id']==out['id'] and e['body']['operation_index']==i]
    if len(matches)!=1:raise ValueError('Learning operation lacks exactly one original application')
    receipt=matches[0];knowledge=session.get(receipt['body']['knowledge_event_id'])
    if knowledge['run_id']!=run or knowledge['kind']!='knowledge' or knowledge['body']['action']!=op['action'] or not out['seq']<knowledge['seq']<receipt['seq']<audit[0]['seq']:raise ValueError('Learning application lineage mismatch')
    learning['applications'].append(dict(receipt['body'],event_id=receipt['id']))
 cache={r:(copy.deepcopy(by_role[r][0]['body']['output']),by_role[r][0]['id']) for r in expected|{'context','evidence'}}
 return {'version':VERSION,'failure':failure,'start':start,'pending':pending,'raw_response':raw_response,'cache':cache,
  'decision_scope':scope[0]['body'],'research_history':h[0]['body'] if h else None,'learning_cycle':learning,'reflection':reflection,
  'pruning_audit_id':audit[0]['id'],'user_persona':pending['body']['payload']['user_persona'],
  'facts':[e['body']['fact'] for e in ev if e['kind']=='research_evidence'],
  'prefix_output_ids':[e['id'] for e in accepted],
  'resources':resources,'resource_provenance':'original_run_snapshot' if b.get('runtime_resources') else 'caller_provided_legacy_snapshot',
  'prefix_digest':hashlib.sha256(dumps([{k:e[k] for k in ('id','digest')} for e in ev if e['seq']<=failure['seq']]).encode()).hexdigest()}

def begin(session,plan):
 run=plan['start']['run_id'];as_of=plan['start']['effective'];pending=plan['pending']
 receipt={k:plan[k] for k in ('version','prefix_output_ids','prefix_digest','resources','resource_provenance')}
 receipt.update(source_failed_id=plan['failure']['id'],source_input_id=pending['id'],pid=os.getpid(),process_birth=process_birth(os.getpid()),
  source_status='failed',status='running',raw_response_sha256=hashlib.sha256(plan['raw_response'].encode()).hexdigest(),
  rule='Same original run and frozen submission; no accepted model regeneration, knowledge reapplication, budget reset or acceptance of the unverified response')
 cid=session.append('continuation_started',receipt,as_of,run)
 session.append('recovery',{'status':'resuming','continuation_id':cid,'pid':receipt['pid'],'process_birth':receipt['process_birth'],'source_failed_id':plan['failure']['id']},as_of,run)
 error=ProviderSubmissionError('legacy_completion_unverified',plan['raw_response'],{'root_cause':'unknown; original CLI trace unavailable'})
 oid=session.append('agent_output',{'role':pending['body']['role'],'input_id':pending['id'],'output':error.output,'provider_failure':error.diagnostic,
  'raw_provider_response':plan['raw_response'],'continuation_id':cid,'origin':'Preserved caller-supplied response paired with original unfinished input; never provider-attested'},as_of,run)
 from .submission import diagnostics
 diag=diagnostics(pending['body']['role'],error.output,pending['body']['payload'],error)
 session.append('agent_validation',{'role':pending['body']['role'],'input_id':pending['id'],'output_id':oid,'status':'rejected','code':'provider_submission','subtype':None,'attempt':1,'diagnostic':diag},as_of,run)
 plan['receipt_id']=cid;plan['feedback']={'code':'provider_submission','rejected_output_id':oid,'previous_output':error.output,'submission_diagnostic':diag,
  'instruction':'원 응답은 CLI 완료 확인이 없어 미수용 상태예요. 사실·계산·반론을 유지하며 원 계약에 맞는 전체 JSON을 새로 제출하세요. 이전 내용이 검증된 사실이라고 가정하지 않아요.'}
 return plan
