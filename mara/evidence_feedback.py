"""Bounded analyst -> evidence supplier -> analyst exchanges, never approval by receipt."""
import copy
import hashlib
from .domain import dumps
from .contracts import ContractError

VERSION = 'mara.evidence-feedback/1.0'
MAX_ROUNDS = 2
MAX_REQUESTS = 6
MAX_SHARED_REQUESTS = 12

POLICY = {
    'schema_version': VERSION,
    'instruction': '판단에 중요한 자료·독해·분석 공백이 있으면 next_checks에만 미루지 말고 evidence_requests로 자료 담당에게 요청하세요. 고정 question_id와 필요한 기간·단위·원문/계산 조건을 acceptance에 구체화하세요. 자료 요청은 개인 정보 확인이나 매수 지시가 아니에요. 응답은 증거 확보 상태이며 충분성·승인이 아니에요. 같은 요청을 반복하지 말고 받은 근거로 판단과 반증을 다시 검토하세요. 경제적 가정 선택은 요청자 책임이며 공급자에게 결론을 요구하지 않아요.',
    'retry_policy':'같은 대상의 부분 응답을 더 조사하려면 followup_of에 실제 이전 request_id, retry_reason에 새 원문 범위/출처/계산 경로와 결과를 바꿀 이유를 적어요. 새 related_fact_ids가 도착한 경우도 재조사할 수 있어요. 무근거 반복은 중단하며 미래 가정은 시나리오로 다뤄요.',
    'assessment_scope':'이번 입력의 evidence_feedback에서 requester가 자신이고 response가 있는 요청은 이전 회차에 평가했더라도 request_id별로 빠짐없이 한 번 다시 평가하세요. 새 응답만 평가하지 마세요. 아직 응답이 없는 자기 요청은 생략하거나 still_missing만 남기고, 반복 평가를 새 자료나 독립 확인으로 세지 마세요.',
    'max_rounds': MAX_ROUNDS, 'max_requests_per_round': MAX_REQUESTS,
    'max_requester_responses_per_round':MAX_SHARED_REQUESTS,
}

def target_key(row):
    target=row.get('research_target') or {}
    values=[str(target.get(k,'')).strip().casefold() for k in ('subject','topic','measure','period','unit','basis')]
    # Unknown dimensions never establish compatibility.
    if any(v in ('','unknown','unspecified','n/a','미정','미확인') for v in values):return row['request_id']
    return hashlib.sha256(dumps(values).encode()).hexdigest()

def schedule(waiting,exchanges):
    """Rank decision impact; share only identical dated/unit/basis research targets."""
    completed={target_key(r) for r in exchanges if r.get('response')}
    eligible=[]
    for row in waiting:
        impact={'changes_choice':4,'changes_size':3,'changes_timing':2,'explanation_only':1}.get(row.get('decision_priority'),0)
        integrity=int(row.get('gap_class') in ('fact_verification','calculation_link'))
        stage=int(row.get('stage')=='final_validation')
        row.update(research_group=target_key(row),priority_score=impact*100+integrity*10+stage,
            scheduling_reason='decision impact, then factual/calculation integrity, then final validation; stable request ID tie-break')
        if row.get('gap_class')=='future_judgment':
            row.update(status='scenario_review',scheduling_reason='Irreducible future assumption: requester must compare scenarios, sizes and review conditions; not negative evidence')
        elif row.get('research_target') and target_key(row) in completed and not retry_supported(row,exchanges):
            row.update(status='repeat_target_stopped',scheduling_reason='Same dated/unit/basis target already returned in this run; retain unmet acceptance for requester/learning review')
        else:eligible.append(row)
    # Legacy requests keep emission order; calibrated requests have an explicit stable order.
    eligible.sort(key=lambda r:(-r['priority_score'],r['request_id'] if r.get('decision_priority') else ''))
    active=[];groups=set()
    for row in eligible:
        group=row['research_group']
        if len(active)>=MAX_SHARED_REQUESTS or (group not in groups and len(groups)>=MAX_REQUESTS):
            row.update(status='deferred_capacity',scheduling_reason='Bounded research-target or requester-response budget; not evidence against the investment')
        else:active.append(row);groups.add(group)
    return active

def retry_supported(row,exchanges):
    for prior in exchanges:
        if not prior.get('response') or target_key(prior)!=target_key(row):continue
        new_facts=set(row.get('related_fact_ids',[]))-set(prior.get('related_fact_ids',[]))-set(prior['response']['fact_ids'])
        if new_facts:return True
        unmet=prior.get('assessment',{}).get('status')=='still_missing' or prior['response']['status']!='evidence_supplied' or bool(prior['response'].get('remaining_gap','').strip())
        if unmet and row.get('followup_of')==prior['request_id'] and row.get('retry_reason','').strip():return True
    return False

class FeedbackContractError(ContractError):
    def __init__(self,message,required=(),pending=()):
        super().__init__(message)
        self.diagnostic={'required_response_ids':sorted(required),'pending_request_ids':sorted(pending),
            'instruction':'자신의 실제 response가 있는 ID는 빠짐없이 한 번 평가하세요. 아직 응답이 없는 자신의 요청은 생략하거나 still_missing만 사용하세요. 대기 중인 요청을 incorporated/not_relevant로 닫거나 다른 역할 요청을 자기 assessment로 쓰지 마세요.'}


def validate_output(role, output, payload):
    questions={q['id'] for q in (payload.get('decision_scope') or {}).get('questions',[])}
    requests=output.get('evidence_requests',[])
    if any(r['question_id'] not in questions for r in requests):
        raise ContractError('Evidence request requires a frozen decision question')
    facts={f['id'] for f in payload.get('market',{}).get('facts',[])}
    if role!='evidence':
        own={r['request_id'] for r in payload.get('evidence_feedback',[]) if r['requester']==role}
        expected={r['request_id'] for r in payload.get('evidence_feedback',[]) if r['requester']==role and r.get('response')}
        assessments=output.get('evidence_assessments',[])
        received={r['request_id'] for r in assessments}
        if len(received)!=len(assessments) or not expected<=received<=own or any(r['request_id'] not in expected and r['status']!='still_missing' for r in assessments):
            raise FeedbackContractError('Requester must assess every returned response; pending acknowledgments stay missing',expected,own-expected)
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
            if request.get('related_fact_ids'):normalized['related_fact_ids']=sorted(request['related_fact_ids'])
            if request.get('followup_of'):normalized['followup_of']=request['followup_of'];normalized['retry_reason']=request.get('retry_reason')
            key=hashlib.sha256(dumps([role,normalized]).encode()).hexdigest()
            rows.append(dict(copy.deepcopy(request),request_id='request-'+key[:24],requester=role,
                source_output_id=output_id,stage=stage,round=round_no,
                status='duplicate' if key in seen else 'pending',dedup_key=key))
            seen.add(key)
    return rows


def for_role(exchanges,role):
    # Perspective inputs receive only their own requests, never peer opinions.
    return [copy.deepcopy(x) for x in exchanges if x['requester']==role or role in ('validation','leader')]

