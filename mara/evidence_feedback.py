"""Bounded analyst -> evidence supplier -> analyst exchanges, never approval by receipt."""
import copy
import hashlib
from .domain import dumps
from .contracts import ContractError

VERSION = 'mara.evidence-feedback/1.0'
MAX_ROUNDS = 2
MAX_REQUESTS = 6

POLICY = {
    'schema_version': VERSION,
    'instruction': '판단에 중요한 자료·독해·분석 공백이 있으면 next_checks에만 미루지 말고 evidence_requests로 자료 담당에게 요청하세요. 고정 question_id와 필요한 기간·단위·원문/계산 조건을 acceptance에 구체화하세요. 자료 요청은 개인 정보 확인이나 매수 지시가 아니에요. 응답은 증거 확보 상태이며 충분성·승인이 아니에요. 같은 요청을 반복하지 말고 받은 근거로 판단과 반증을 다시 검토하세요. 경제적 가정 선택은 요청자 책임이며 공급자에게 결론을 요구하지 않아요.',
    'max_rounds': MAX_ROUNDS, 'max_requests_per_round': MAX_REQUESTS,
}


def validate_output(role, output, payload):
    questions={q['id'] for q in (payload.get('decision_scope') or {}).get('questions',[])}
    requests=output.get('evidence_requests',[])
    if any(r['question_id'] not in questions for r in requests):
        raise ContractError('Evidence request requires a frozen decision question')
    facts={f['id'] for f in payload.get('market',{}).get('facts',[])}
    if role!='evidence':
        expected={r['request_id'] for r in payload.get('evidence_feedback',[]) if r['requester']==role and r.get('response')}
        assessments=output.get('evidence_assessments',[])
        if len({r['request_id'] for r in assessments})!=len(assessments) or {r['request_id'] for r in assessments}!=expected:
            raise ContractError('Requester must assess every returned evidence response')
        if any(not set(r['fact_ids'])<=facts for r in assessments):raise ContractError('Evidence assessment cites undelivered facts')
    if role!='evidence':return
    expected={r['request_id'] for r in payload.get('evidence_assignments',[])}
    responses=output.get('evidence_responses',[])
    if len({r['request_id'] for r in responses})!=len(responses) or {r['request_id'] for r in responses}!=expected:
        raise ContractError('Evidence responses must match assigned request IDs exactly')
    for row in responses:
        if not set(row['fact_ids'])<=facts:raise ContractError('Evidence response cites undelivered facts')
        if row['status']=='evidence_supplied' and not row['fact_ids']:
            raise ContractError('Evidence supplied requires a delivered fact')
        if row['status']!='evidence_supplied' and not row['remaining_gap'].strip():
            raise ContractError('Unresolved response requires a remaining gap')


def collect(outputs, seen, round_no):
    """Preserve every emitted request, including duplicates and overflow."""
    rows=[]
    for role,stage,output_id,output in outputs:
        for request in output.get('evidence_requests',[]):
            normalized={k:' '.join(v.split()).casefold() for k,v in request.items() if k in ('question_id','need','acceptance')}
            key=hashlib.sha256(dumps([role,normalized]).encode()).hexdigest()
            rows.append(dict(copy.deepcopy(request),request_id='request-'+key[:24],requester=role,
                source_output_id=output_id,stage=stage,round=round_no,
                status='duplicate' if key in seen else 'pending',dedup_key=key))
            seen.add(key)
    return rows


def for_role(exchanges,role):
    # Perspective inputs receive only their own requests, never peer opinions.
    return [copy.deepcopy(x) for x in exchanges if x['requester']==role or role in ('validation','leader')]

