"""Frozen decision questions and evidence receipts; collection is never analytical resolution."""
import copy
from .contracts import ContractError

VERSION='mara.research-questions/1.0.0'


def freeze(profile,market):
    candidates=sorted(s for s,a in market['assets'].items() if s!='CASH' and a.get('asset_class')!='cash')
    questions=[{'id':'portfolio-allocation','target':'portfolio','owner':'leader','depth':'decision',
        'question':'목표·기간·유동성에 맞게 왜 이 비중인가? 유지·다른 비중·현금과 무엇이 다른가?',
        'acceptance':'같은 자금·통화·시점의 대안과 최종 비중 계산, 반증 조건을 비교해요.'}]
    for symbol in candidates:
        equity=market['assets'][symbol].get('kind') in {'STOCK','FOREIGN_STOCK','REIT','DEPOSITARY_RECEIPT'}
        questions.append({'id':'candidate-'+symbol,'target':symbol,'owner':'buffett' if equity else 'bogle','depth':'screening',
            'question':'선택·제외·추가 조사 중 무엇이 타당한가? 선택한다면 현재 가격과 비중의 근거가 충분한가?',
            'acceptance':'제외는 입증 가능한 이유. 선택한 기업은 가치 가정·가격·희석, 상품은 노출·구조·비용. 모두 같은 깊이의 DCF를 요구하지 않아요.'})
    return {'schema_version':VERSION,'as_of':market['as_of'],'goal':profile['goal'],'candidates':candidates,
        'questions':questions,'scope':'Initial eligible market candidates; discovery outside this set is recorded, not silently promoted to investable assets.'}


def validate_reviews(output,payload):
    rows=output.get('question_reviews')
    if rows is None:return
    scope=payload.get('decision_scope') or {};questions={q['id']:q for q in scope.get('questions',[])}
    if len({r['question_id'] for r in rows})!=len(rows) or any(r['question_id'] not in questions for r in rows):
        raise ContractError('Unknown or duplicate decision question')
    facts={f['id']:f for f in payload.get('market',{}).get('facts',[])}
    from .evaluation import pointer
    for row in rows:
        if not set(row['fact_ids'])<=facts.keys():raise ContractError('Question cites evidence not delivered to reviewer')
        for path in row['calculation_paths']:
            if not path.startswith('/analysis/'):raise ContractError('Question calculation must reference analysis')
            if pointer({'report':payload},'/report'+path) in (None,{},[]):raise ContractError('Empty question calculation')
        if row['status']=='supported' and not (row['fact_ids'] or row['calculation_paths']):
            raise ContractError('Supported question requires reviewable evidence')
        if row['status']=='supported' and not payload.get('final_proposal'):
            raise ContractError('Question resolution requires final proposal review')
    # Optional for old/custom providers. Omitted questions stay explicitly unreviewed.


def ledger(session,run_id,scope,delivery=(),final_review=None):
    events=[e for kind in ('research_activity','research_stop') for e in session.events(kind) if e['run_id']==run_id]
    activities=[e for e in events if e['kind']=='research_activity']
    stops=[{'event_id':e['id'],**e['body']} for e in events if e['kind']=='research_stop']
    delivered={fid for d in delivery for fid in d['fact_ids']}
    reviewer_delivered={fid for d in delivery if d['role']=='validation' for fid in d['fact_ids']}
    reviews={r['question_id']:r for r in (final_review or {}).get('question_reviews',[])}
    rows=[]
    for q in scope['questions']:
        linked=[e for e in activities if q['id'] in e['body'].get('question_ids',[])]
        ids=sorted({e['body']['fact_id'] for e in linked if e['body'].get('fact_id')})
        review=reviews.get(q['id'])
        review_ids=sorted(set(review['fact_ids'])) if review else []
        all_ids=sorted(set(ids+review_ids))
        # Even a supported review is an attributed analyst judgment, not a code proof or Q1 pass.
        rows.append(dict(q,activity_ids=[e['id'] for e in linked],activities=[{'event_id':e['id'],**e['body']} for e in linked],
            activated_fact_ids=ids,review_fact_ids=review_ids,fact_ids=all_ids,delivered_fact_ids=sorted(set(all_ids)&delivered),
            reviewer_delivered_fact_ids=sorted(set(all_ids)&reviewer_delivered),state='reviewed_'+review['status'] if review else 'awaiting_analysis_review',review=review))
    result={'schema_version':VERSION,'scope':copy.deepcopy(scope),'questions':rows,'research_stops':stops,
        'unattributed_activity_ids':[e['id'] for e in activities if not e['body'].get('question_ids')],
        'limits':'Evidence collection/delivery is not sufficient analysis. Reviewed status is final R4 judgment; Q1 and proposal readiness remain separate.'}
    from .contracts import validate,schema
    return validate(result,schema('research-questions'))


def validate_ledger(value,source_ids):
    rows=value['questions'];scope=value['scope']['questions'];ids=[q['id'] for q in scope]
    if len(set(ids))!=len(ids) or [q['id'] for q in rows]!=ids:raise ContractError('Question denominator mismatch')
    for q,original in zip(rows,scope):
        if any(q[k]!=v for k,v in original.items()):raise ContractError('Question scope changed')
        if not set(q['fact_ids'])<=set(source_ids):raise ContractError('Unknown question source')
        if set(q['fact_ids'])!=set(q['activated_fact_ids']+q['review_fact_ids']):raise ContractError('Question evidence mismatch')
        if q['activity_ids']!=[a['event_id'] for a in q['activities']]:raise ContractError('Question activity mismatch')
        if any(q['id'] not in a['question_ids'] for a in q['activities']):raise ContractError('Activity question mismatch')
        if any(not set(q[k])<=set(q['fact_ids']) for k in ('delivered_fact_ids','reviewer_delivered_fact_ids')):raise ContractError('Question delivery mismatch')
        review=q['review']
        if q['state']!=('reviewed_'+review['status'] if review else 'awaiting_analysis_review'):raise ContractError('Question review state mismatch')
        if review and (review['question_id']!=q['id'] or set(review['fact_ids'])!=set(q['review_fact_ids'])):raise ContractError('Question review reference mismatch')
        if review and review['status']=='supported' and not (review['fact_ids'] or review['calculation_paths']):raise ContractError('Question support missing')
