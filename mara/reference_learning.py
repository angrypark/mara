"""Process-only reference CI lineage, separate from accepted investment evidence."""
import copy,hashlib
from .domain import dumps

def failures(events,completed):
 inputs={e['id']:e for e in events if e['kind']=='agent_input'}
 outputs={e['id']:e for e in events if e['kind']=='agent_output'}
 checks=sorted((e for e in events if e['kind']=='proposal_reference_validation'),key=lambda e:e['seq'])
 validations={e['body']['output_id']:e for e in events if e['kind']=='agent_validation'}
 hashes={oid:hashlib.sha256(dumps(e['body']['output']).encode()).hexdigest() for oid,e in outputs.items()}
 links={};children={};check_by_output={e['body']['output_id']:e for e in checks}
 for inp in inputs.values():
  p=inp['body']['payload'];feedback=p.get('reference_feedback')
  if inp['body']['role']!='leader' or not feedback or 'previous_output' not in feedback:continue
  digest=hashlib.sha256(dumps(feedback['previous_output']).encode()).hexdigest()
  prior=[e for e in checks if e['run_id']==inp['run_id'] and e['seq']<inp['seq'] and hashes.get(e['body']['output_id'])==digest and e['body']['errors']==feedback.get('errors')]
  if not prior:continue
  source=prior[-1];links[inp['id']]=source['id'];children.setdefault(source['id'],[]).append(inp)
 by_id={e['id']:e for e in checks}
 def first_error(check):
  seen=set();oldest=check
  while check['id'] not in seen:
   seen.add(check['id']);out=outputs.get(check['body']['output_id']);parent=links.get(out['body']['input_id']) if out else None
   if parent not in by_id:break
   check=by_id[parent]
   if check['body']['errors']:oldest=check
  return oldest['id']
 rows=[]
 for check in checks:
  b=check['body'];source=outputs.get(b['output_id'])
  # New alternatives/weights require ordinary reconciliation, not a failure.
  if b['status']!='failed' or not b['errors'] or not source:continue
  attempts=[];passed=[];queue=[check];visited=set()
  while queue:
   current=queue.pop(0)
   if current['id'] in visited:continue
   visited.add(current['id'])
   for inp in children.get(current['id'],[]):
    out=next((x for x in outputs.values() if x['body']['input_id']==inp['id']),None)
    validation=validations.get(out['id']) if out else None;reference=check_by_output.get(out['id']) if out else None
    status=validation['body']['status'] if validation else 'not_completed'
    row={'input_id':inp['id'],'source_reference_event_id':current['id'],'output_id':out['id'] if out else None,
      'submission_status':status,'reference_event_id':reference['id'] if reference else None,
      'reference_status':reference['body']['status'] if reference else 'not_checked'}
    attempts.append(row)
    if status=='accepted' and reference and inp['seq']<out['seq']<validation['seq']<reference['seq']:
     if reference['body']['status']=='passed' and not reference['body']['errors']:passed.append(row)
     else:queue.append(reference)
  rows.append({'failure_id':check['id'],'case_id':first_error(check),'kind':'proposal_reference_rejection','role':'leader',
   'stage':'proposal_synthesis','code':'proposal_reference','subtype':'calculation_link','recorded_at':check['recorded'],'as_of':check['effective'],
   'run_state':'completed' if check['run_id']==completed['run_id'] else 'failed',
   'source_output_id':source['id'],'source_output_sha256':hashes[source['id']],
   'source_submission_status':validations.get(source['id'],{}).get('body',{}).get('status','unknown'),
   'source_reference_status':'failed','diagnostic':copy.deepcopy(b['errors']),'reference_attempt':b['attempt'],
   'correction_status':'accepted' if passed else 'not_completed' if attempts else 'not_recorded',
   'correction_attempts':attempts,'verified_corrections':passed,
   'scope':'Reference CI process evidence only. Agent acceptance alone is not reference acceptance. No failed investment draft is copied or promoted; ordinary allocation reconciliation is not an error.'})
 return rows
