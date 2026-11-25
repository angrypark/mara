"""A role can update its own durable judgment knowledge through accepted submissions."""
import re

from .contracts import validate
from .knowledge import PROTECTED


FIELD = 'role_knowledge_update'
POLICY = (
    '자기 역할에 재사용할 판단 원칙, 반증 조건, 희귀 위험 또는 검증 가능한 교훈만 한 건 제안할 수 있어요. '
    '개인정보, 종목/가격/시황, 현재 작업 내용, 일회성 관측과 출처 요약은 저장하지 마세요. '
    '적용 조건과 판단이 바뀔 이유를 명시하고 반복되는 항목은 revise를 사용해요. '
    '수정·보관은 입력에 전달된 자기 역할의 key만 사용해요. 원칙이나 희귀 위험의 내용을 바꾸거나 보관하려면 '
    '기존 판단이 적용되지 않는 이유와 전달 근거의 fact ID를 적어요. 필요한 항목이 없으면 필드를 생략하세요.'
)
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 600}
INVALIDATING_FACTS = {'type':'array','minItems':1,'maxItems':4,'uniqueItems':True,'items':TEXT}
ABSOLUTE_DATE = re.compile(r'\b(?:19|20)\d{2}(?:[-/.]\d{1,2}[-/.]\d{1,2}|\s*년\s*\d{1,2}\s*월)')
ONE_RUN_CONDITION = re.compile(r'\b(?:today|this run|this proposal) only\b|오늘만|이번 (?:실행|제안)에만',re.I)
SCHEMA = {'oneOf': [
    {'type': 'object', 'additionalProperties': False,
     'properties': dict(action={'enum': ['add']}, reason=TEXT, text=TEXT,
                        topic=dict(TEXT, maxLength=160), condition=TEXT,
                        category={'enum': ['principle', 'lesson', 'hypothesis', 'rare_risk']},
                        valid_until={'type': ['string', 'null'], 'pattern': r'^\d{4}-\d{2}-\d{2}$'}),
     'required': ['action', 'reason', 'text', 'topic', 'condition', 'category', 'valid_until']},
    {'type': 'object', 'additionalProperties': False,
     'properties': dict(action={'enum': ['revise']}, reason=TEXT, key=TEXT, text=TEXT, condition=TEXT,
                        invalidating_fact_ids=INVALIDATING_FACTS,
                        valid_until={'type': ['string', 'null'], 'pattern': r'^\d{4}-\d{2}-\d{2}$'}),
     'required': ['action', 'reason', 'key', 'text', 'condition', 'valid_until']},
    {'type': 'object', 'additionalProperties': False,
     'properties': dict(action={'enum': ['archive']}, reason=TEXT, key=TEXT,
                        invalidating_fact_ids=INVALIDATING_FACTS),
     'required': ['action', 'reason', 'key']},
]}


def offer(payload, role, contract):
    keys = {item['key']:item['event_id'] for item in payload.get('knowledge', {}).get('items', [])
            if item.get('owner_role') == role}
    payload['role_knowledge_policy'] = {'instruction': POLICY, 'own_keys': keys}
    contract['properties'][FIELD] = SCHEMA


def record(knowledge, as_of, run_id, output_ids):
    """Apply only the most recent accepted output per role at a durable result boundary."""
    if not knowledge.s.store.in_transaction:
        raise RuntimeError('Role knowledge changes require the result transaction')
    session = knowledge.s
    validations = session.events('agent_validation', as_of)
    accepted = {e['body']['output_id'] for e in validations
                if e['run_id'] == run_id and e['body']['status'] == 'accepted'}
    latest = {}
    for oid in output_ids:
        if oid not in accepted:
            continue
        output = session.get(oid)
        role = output['body']['role']
        if role not in latest or latest[role]['seq'] < output['seq']:
            latest[role] = output
    recorded = {e['body']['source_output_id'] for e in session.events('role_knowledge_receipt', as_of)
                if e['run_id'] == run_id}
    receipts = []
    for role, output in latest.items():
        oid = output['id']
        body = output['body']
        source = session.get(body['input_id'])['body']
        proposal = body.get(FIELD)
        policy = source['payload'].get('role_knowledge_policy')
        if oid in recorded or FIELD not in body or not policy:
            continue
        receipt = {'role': role, 'source_output_id': oid, 'status': 'rejected'}
        try:
            validate(proposal, SCHEMA)
            operation = dict(proposal)
            if (any(ABSOLUTE_DATE.search(operation.get(key,'')) for key in ('text','topic','condition'))
                    or ONE_RUN_CONDITION.search(operation.get('condition',''))):
                raise ValueError('Role knowledge must avoid one-off observations')
            current = knowledge.current(as_of)
            invalidating = operation.pop('invalidating_fact_ids', [])
            if operation['action'] != 'add':
                key = operation['key']
                if key not in policy['own_keys'] or policy['own_keys'][key] != current.get(key,{}).get('event_id'):
                    raise ValueError('Role did not receive this knowledge version')
                old = current[key]
                if old['category'] in PROTECTED and operation['action'] == 'revise' and not invalidating:
                    if any(operation[field] != old[field] for field in ('text','condition')):
                        raise ValueError('Protected knowledge revision requires delivered evidence')
            if operation['action'] != 'archive':
                operation['refs'] = [oid]
            if operation['action'] == 'add':
                operation.update(roles=[role], perspective=role, priority=5)
                fields = ('text', 'category', 'topic', 'condition')
                fingerprint = tuple(operation[k].strip().casefold() for k in fields)
                if any(k.get('owner_role')==role and k['status']=='active' and
                       tuple(k[f].strip().casefold() for f in fields)==fingerprint for k in current.values()):
                    raise ValueError('Role already has this knowledge')
            if invalidating:
                delivered = {f['id'] for f in source['payload'].get('market', {}).get('facts', [])}
                if not set(invalidating) <= delivered:
                    raise ValueError('Invalidation cites an undelivered fact')
                operation['invalidating_refs'] = [body['input_id']]
            receipt['knowledge_event_id'] = knowledge.apply(
                operation, as_of, run_id, owner_role=role, source_output_id=oid)
            receipt['status'] = 'applied'
            if invalidating:receipt['invalidating_fact_ids'] = invalidating
        except (ValueError, TypeError, KeyError, PermissionError):
            receipt['reason'] = 'invalid_or_unauthorized_update'
        receipt['event_id'] = session.append('role_knowledge_receipt', receipt, as_of, run_id)
        receipts.append(receipt)
    return receipts
