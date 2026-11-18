"""Append-only independent findings; never overwrite model decisions or market facts."""
import copy,hashlib,re
from .domain import dumps

KINDS={'arithmetic_rounding':'verified_arithmetic_correction','conditional_scope_mixed':'independent_scope_review'}

def digest(value):return hashlib.sha256(dumps(value).encode()).hexdigest()

def resolve(value,path):
    if not isinstance(path,str) or not path.startswith('/output/'):raise ValueError('Output pointer required')
    for part in path[1:].split('/'):
        part=part.replace('~1','/').replace('~0','~')
        value=value[int(part)] if isinstance(value,list) else value[part]
    return value

def check(session,completed,body,facts=None):
    if completed['owner']!=session.owner or completed['kind']!='completed' or body.get('source_completed_id')!=completed['id']:raise ValueError('Own completed source required')
    source=session.get(body['source_output_id'])
    if source['owner']!=session.owner or source['kind']!='agent_output' or source['run_id']!=completed['run_id'] or source['seq']>=completed['seq']:raise ValueError('Output does not belong to completed source')
    accepted=any(e['run_id']==completed['run_id'] and e['seq']<completed['seq'] and e['body'].get('output_id')==source['id'] and e['body']['status']=='accepted' for e in session.events('agent_validation'))
    if not accepted:raise ValueError('Accepted source output required')
    original=resolve(source['body'],body['source_path'])
    if not isinstance(original,str) or original!=body['original_text'] or digest(original)!=body['original_sha256'] or digest(source['body'])!=body['source_body_sha256']:raise ValueError('Original source text/hash mismatch')
    if KINDS.get(body.get('code'))!=body.get('classification'):raise ValueError('Controlled finding classification required')
    for key in ('reviewer','review_summary','correction_or_review','limits'):
        if not isinstance(body.get(key),str) or not body[key].strip():raise ValueError('Finding explanation and limits required')
    if body.get('scope')!='process_review_only' or len(dumps(body))>24000:raise ValueError('Bounded process review required')
    hashes=body.get('fact_hashes',{})
    if not isinstance(hashes,dict):raise ValueError('Fact hashes required')
    if hashes:
        if facts is None:
            from .fact_catalog import authoritative_facts
            facts=authoritative_facts(session,completed)
        known={f['id']:digest(f) for f in facts}
        if any(known.get(k)!=v for k,v in hashes.items()):raise ValueError('Original fact snapshot mismatch')
    if body['code']=='arithmetic_rounding':
        proof=body.get('verification',{})
        if not hashes or not all(isinstance(proof.get(k),str) and proof[k].strip() for k in ('formula','result','unit','period','rounding')):raise ValueError('Arithmetic verification required')
        if not all(re.fullmatch('[0-9a-f]{64}',proof.get(k,'')) for k in ('script_sha256','artifact_sha256')):raise ValueError('Verification artifact hashes required')
    return source

def findings(session,completed,before_seq=None):
    limit=before_seq if before_seq is not None else session.store.db.execute('SELECT coalesce(max(seq),0)+1 FROM events').fetchone()[0]
    result=[];facts=None
    for e in session.events('report_audit_finding',completed['effective']):
        if e['owner']!=session.owner or e['seq']>=limit or e['seq']<=completed['seq'] or e['body'].get('source_completed_id')!=completed['id']:continue
        try:
            if e['body'].get('fact_hashes') and facts is None:
                from .fact_catalog import authoritative_facts
                facts=authoritative_facts(session,completed)
            source=check(session,completed,e['body'],facts)
        except (ValueError,PermissionError,KeyError,TypeError,IndexError):continue
        result.append(dict(copy.deepcopy(e['body']),event_id=e['id'],recorded_at=e['recorded'],role=source['body']['role']))
    return result

def record(session,body,as_of):
    if not session.store.in_transaction:
        with session.store.transaction():return record(session,body,as_of)
    completed=session.get(body['source_completed_id'])
    if as_of!=completed['effective']:raise ValueError('Audit is scoped to the original analysis date')
    check(session,completed,body)
    for old in session.events('report_audit_finding',as_of):
        if old['owner']==session.owner and old['body']==body:return old['id']
    return session.append('report_audit_finding',copy.deepcopy(body),as_of,completed['run_id'])
