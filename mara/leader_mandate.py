"""One auditable pre-analysis leader submission and role-specific delivery."""
import copy
import hashlib

from .contracts import ContractError, schema, validate
from .registry import catalogue

VERSION = "urn:mara:leader-mandate:1.0.0"
STAGE = "leader_mandate"


def responsibilities():
    return [dict(role=item['id'], responsibility=item['description'])
            for item in catalogue() if item['kind'] in ('evidence', 'perspective', 'validation', 'leader')]


def validate_plan(output, payload, contract):
    validate(output, contract)
    expected = {row['role'] for row in payload['roles']}
    delivered = [row['role'] for row in output['assignments']]
    if len(delivered) != len(expected) or set(delivered) != expected:
        raise ContractError('Leader mandate requires exactly one assignment for each runtime role')
    return output


def run(session, model, guide, common, context_id, run_id, as_of):
    from .submission_recovery import guard
    from .codex_model import ProviderSubmissionError

    contract = schema('leader-mandate')
    payload = {key: copy.deepcopy(common[key]) for key in (
        'decision_scope', 'user_persona', 'decision_context', 'context_analysis', 'funding')}
    profile = common['profile']
    payload.update(analysis_stage=STAGE, as_of=as_of, roles=responsibilities(),
        constraint_basis={key: copy.deepcopy(profile[key]) for key in (
            'constraints', 'markets', 'horizon_months', 'horizon_purpose', 'cash_need', 'cash_need_date',
            'max_position_fraction', 'criteria', 'investment_style') if key in profile},
        analysis_paths=['/analysis/' + key.replace('~', '~0').replace('/', '~1') for key in common['analysis']],
        market_basis={'base_currency': common['market']['base_currency'],
                      'candidate_symbols': common['decision_scope']['candidates']})
    guide += (
        '\n이번 호출은 초기 분석 계획이에요. 현재 목표와 입력 제약에 맞춰 핵심 질문, 기준 포트폴리오, 비교할 대안, '
        '공통 측정 기준과 역할별 조사 범위·수용 조건을 정해요. constraint_basis와 decision_context.risk_budget을 '
        '사용하고 맥락 요약의 추정이나 생략으로 두 입력을 바꾸지 않아요. benchmark는 동일한 통화·기간·자금 흐름으로 '
        '대안을 비교하기 위한 기준을 설명해요. 대안은 가용성·동일 기준 비교를 전제로 열어두고, '
        '자산 선택·비중·최종 판단을 미리 정하지 않아요. 측정 기준에는 계산 기준과 관측 또는 실패 조건을 '
        '넣어요. 개인 미확인 조건을 사실이나 제약으로 바꾸지 않고 더 확인할 문제로 남겨요. 역할마다 고유 '
        '업무를 정확히 한 건씩 지정하고, 검증은 입력 제약·계산·주장 비교를 독립적으로 확인하도록 맡겨요.')
    guard(session, run_id, as_of)
    input_id = session.append('leader_mandate_input', {
        'role': 'leader', 'payload': payload, 'guide': guide, 'guide_hash': hashlib.sha256(guide.encode()).hexdigest(),
        'contract': contract, 'provider': model.identity, 'context_output_id': context_id,
    }, as_of, run_id)
    provider_error = None
    try:
        output = model.complete('leader', guide, payload, contract)
    except ProviderSubmissionError as exc:
        provider_error = exc
        output = exc.output
    record = {'input_id': input_id, 'output': output}
    if provider_error:
        record.update(provider_failure=provider_error.diagnostic, raw_provider_response=provider_error.raw_response)
    output_id = session.append('leader_mandate_output', record, as_of, run_id)
    try:
        if provider_error:
            raise provider_error
        validate_plan(output, payload, contract)
    except ValueError:
        session.append('leader_mandate_validation', {
            'input_id': input_id, 'output_id': output_id, 'status': 'rejected',
        }, as_of, run_id)
        raise
    session.append('leader_mandate_validation', {
        'input_id': input_id, 'output_id': output_id, 'status': 'accepted',
    }, as_of, run_id)
    return handoff(output_id, output, payload)


def handoff(output_id, output, payload):
    return {'output_id': output_id, **copy.deepcopy(output),
            'constraint_basis': copy.deepcopy(payload['constraint_basis']),
            'unconfirmed_personal_conditions': copy.deepcopy(payload['user_persona']['body']['unknowns'])}


def for_role(mandate, role):
    if role not in {item['role'] for item in mandate['assignments']}:
        return None
    value = copy.deepcopy(mandate)
    if role not in ('validation', 'leader'):
        value['assignments'] = [item for item in value['assignments'] if item['role'] == role]
    value['interpretation'] = (
        '초기 비교 기준과 역할별 조사 계획이에요. 실제 사용자 제약은 profile과 user_persona의 '
        '확인 상태를 따르고, 반론·자료 공백·기준의 부적합은 검토 결과에 남겨요. '
        '최종 판단은 각 역할의 증거와 검증·재요청 결과를 원래 비교 기준에 대조해요.')
    return value


def restore(session, events, start, context, evidence, pending, accepted):
    """Check the one accepted mandate against recorded inputs, without a new call."""
    kinds = ('leader_mandate_input', 'leader_mandate_output', 'leader_mandate_validation')
    records = [[event for event in events if event['kind'] == kind] for kind in kinds]
    if not any(records) and not start['body'].get('leader_mandate_version'):
        return None
    if any(len(rows) != 1 for rows in records):
        raise ValueError('Original leader mandate is missing or ambiguous')
    request, response, receipt = (rows[0] for rows in records)
    evidence_input = session.get(evidence['body']['input_id'])
    if (not context['seq'] < request['seq'] < response['seq'] < receipt['seq'] < evidence_input['seq']
            or request['body']['context_output_id'] != context['id']
            or request['body']['provider'] != pending['body']['provider']
            or request['body']['contract'] != schema('leader-mandate')
            or request['body']['guide_hash'] != hashlib.sha256(request['body']['guide'].encode()).hexdigest()
            or request['body']['payload']['context_analysis'] != context['body']['output']
            or response['body']['input_id'] != request['id'] or response['body'].get('provider_failure')
            or receipt['body'] != {'input_id': request['id'], 'output_id': response['id'], 'status': 'accepted'}):
        raise ValueError('Original leader mandate lineage changed')
    plan = validate_plan(response['body']['output'], request['body']['payload'], request['body']['contract'])
    mandate = handoff(response['id'], plan, request['body']['payload'])
    inputs = [session.get(row['body']['input_id']) for row in accepted if row['seq'] > response['seq']]
    for entry in [*inputs, pending]:
        body = entry['body']
        if body['payload'].get('leader_mandate') != for_role(mandate, body['role']):
            raise ValueError('Original leader mandate delivery changed')
    return mandate
