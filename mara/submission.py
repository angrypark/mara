"""Submission CI: exact delivered references, typed revision requests and diagnostics."""
import copy
from .contracts import ContractError
from .output_validation import evidence_reference_errors,issue_code

VERSION='mara.submission/1.0'
FACT_FIELDS={'facts','fact_ids','evidence_ids','related_fact_ids'}
TEXT={'type':'string','minLength':1,'maxLength':1600}
REVISION={'type':'object','additionalProperties':False,'properties':{
 'id':dict(TEXT,maxLength=80),'target_role':dict(TEXT,maxLength=40),
 'source_output_id':dict(TEXT,maxLength=80),'issue_path':dict(TEXT,maxLength=300),
 'kind':{'type':'string','enum':['analysis_error','calculation_error','missing_evidence']},
 'reason':TEXT,'requested_change':TEXT,'acceptance':TEXT,
 'question_ids':{'type':'array','maxItems':20,'items':dict(TEXT,maxLength=120)},
 'fact_ids':{'type':'array','maxItems':20,'items':dict(TEXT,maxLength=120)}},
 'required':['id','target_role','source_output_id','issue_path','kind','reason','requested_change','acceptance','question_ids','fact_ids']}

def pointer(value,path):
 if path=='/':return value
 if not isinstance(path,str) or not path.startswith('/'):raise ValueError('JSON pointer required')
 for key in path[1:].split('/'):
  key=key.replace('~1','/').replace('~0','~')
  value=value[int(key)] if isinstance(value,list) else value[key]
 return value

def bind(contract,role,payload):
 """Constrain generation, without replacing or accepting a bad reference."""
 result=copy.deepcopy(contract);facts=[f['id'] for f in payload.get('market',{}).get('facts',[])]
 def visit(spec):
  if isinstance(spec,dict):
   for key,child in spec.get('properties',{}).items():
    if key in FACT_FIELDS and child.get('type')=='array':
     if facts:child['items']=dict(child.get('items',{}),enum=facts)
     else:child['maxItems']=0
   for child in spec.values():visit(child)
  elif isinstance(spec,list):
   for child in spec:visit(child)
 if role=='validation' and payload.get('submission_sources') is not None:
  result['properties']['revision_requests']={'type':'array','maxItems':4,'items':copy.deepcopy(REVISION)}
  result['required']=list(dict.fromkeys(result['required']+['revision_requests']))
 visit(result)
 return result

def validate_revisions(output,payload):
 if 'submission_sources' not in payload:return
 if 'revision_requests' not in output:raise ContractError('Explicit revision_requests required, including an empty list when no correctable defect exists')
 rows=output.get('revision_requests',[]);sources=payload['submission_sources']
 if len({r['id'] for r in rows})!=len(rows):raise ContractError('Duplicate revision request ID')
 questions={q['id'] for q in payload.get('decision_scope',{}).get('questions',[])}
 for r in rows:
  source=sources.get(r['target_role'])
  if not source or source['output_id']!=r['source_output_id']:raise ContractError('Revision must address the current accepted author output')
  if not set(r['question_ids'])<=questions:raise ContractError('Revision cites unknown decision question')
  try:pointer(source['output'],r['issue_path'])
  except (ValueError,KeyError,TypeError,IndexError):raise ContractError('Revision issue_path must locate the supplied author output') from None

def diagnostics(role,output,payload,error):
 refs=evidence_reference_errors(output,payload)
 result={'version':VERSION,'role':role,'code':issue_code(error),
  'issues':[dict(code='market_evidence_reference',path=r['path'],reason='ID was not delivered in this submission',value=r['undelivered_id']) for r in refs],
  'validation_error':str(error)[:2500],
  'current_response_ids':[r['request_id'] for r in payload.get('evidence_feedback',[]) if r.get('requester')==role],
  'historical_request_ids':[r['request_id'] for r in (payload.get('research_feedback_history') or {}).get('requests',[]) if r.get('requester')==role],
  'rule':'Use exact delivered IDs. Historical response evaluation is not a current evidence_assessment; use historical followup_of with provenance. No guessed substitution, no relaxation.'}
 if hasattr(error,'diagnostic'):result['semantic_diagnostic']=copy.deepcopy(error.diagnostic)
 return result
