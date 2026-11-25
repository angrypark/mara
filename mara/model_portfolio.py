"""Percentage-only production mandate. No portfolio history, balance or account adapters."""
import copy
import re
import threading
from datetime import datetime

from . import leader_mandate
from .agents import Agents
from .contracts import ContractError
from .domain import weights
from .model_exposures import acquire, calculate
from .onboarding import InputError, KST
from .registry import personas, role_guide
from .research import PublicArchive

VERSION = 'mara.model-portfolio/1'
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 3000}
STRINGS = {'type': 'array', 'items': TEXT, 'maxItems': 12}
POLICY = (
    '미국 주식 ETF 모형의 목표 비중을 소수로 표시해요. 분모는 미국 주식에 배정할 부분 전체예요. '
    '확정된 조건은 confirmed에서 읽고 해석 가정과 미확인 사항을 구분해요. 가계 잔고·투입액은 추정하지 않아요. '
    '공격적이라는 선호만으로 성장주 집중을 가정하지 마세요. 동일 기준의 광범위 지수와 편향 대안을 비교하고 '
    '각 가중치의 한계효과, 비용, 중복, 주식 및 달러 하락, 반증 조건을 분석해요. 비중·보수·수익률은 fraction이고 배수와 개수에는 각 지표의 단위를 쓰며 '
    '비중 계산의 기준일과 상품 지표 관측일을 구분해요. 간결한 한국어로 작성해요.'
)
METHOD = ('각 ETF 공시 전체 USD 자산 시장가치 합계 대비 주식 시장가치 및 기초종목 식별 주식스왑 명목금액. 동일 티커·명칭·거래소의 '
          '교집합에서 작은 비중 합으로 중복 측정. 회사명 끝 CLASS/CL 주종을 합친 공시명 기준으로 '
          '집중도를 근사하며 계열사·상이한 명칭은 합쳐지지 않을 수 있음. 1에서 측정 노출을 뺀 값은 현금 비중과 다름. 선물 명목을 '
          '별도 표시. 지수선물 내부 구성·개인 가계 비중은 미포함. 충격은 예시이며 확률·최대손실 추정이 아님.')


def fields(**props):
    return dict(type='object', properties=props, required=list(props), additionalProperties=False)


def request(setup, body):
    required = {'request_id', 'preference', 'objective'}
    optional = {'minimum_holding_years', 'tolerable_drawdown_fraction'}
    if not isinstance(body, dict) or not required <= body.keys() <= required | optional:
        raise InputError('모형 분석 요청 ID와 두 입력을 확인해주세요.')
    if not isinstance(body['request_id'], str) or not re.fullmatch('[a-f0-9]{32}', body['request_id']):
        raise InputError('모형 분석 요청 ID와 두 입력을 확인해주세요.')
    for key in ('preference', 'objective'):
        if not isinstance(body[key], str) or not 1 <= len(body[key].strip()) <= 250:
            raise InputError('모형 선호와 목적을 짧게 입력해주세요.')
    if 'minimum_holding_years' in body:
        years = body['minimum_holding_years']
        if type(years) is not int or years < 1:
            raise InputError('최소 보유 기간을 양의 연 단위로 입력해주세요.')
    if 'tolerable_drawdown_fraction' in body:
        loss = body['tolerable_drawdown_fraction']
        if type(loss) not in (int, float) or not 0 <= loss <= 1:
            raise InputError('하락 감내 범위는 0에서 1 사이의 비율로 입력해주세요.')
    jid = body['request_id']
    as_of = datetime.now(KST).date().isoformat()
    with setup.guard, setup.session() as session:
        with session.store.transaction():
            existing = session.store.db.execute(
                "SELECT * FROM events WHERE owner=? AND kind='model_request' AND run_id=?",
                (session.owner, jid)).fetchone()
            if existing:
                if session.decode(existing)['body'] != body:
                    raise InputError('동일 요청 ID의 입력이 달라요.')
                return {'job_id': jid, 'duplicate': True}
            if setup.thread and setup.thread.is_alive() or session.store.db.execute(
                    'SELECT 1 FROM locks WHERE owner=?',(session.owner,)).fetchone():
                raise InputError('다른 분석이 실행 중이에요.')
            session.store.db.execute('INSERT INTO locks VALUES (?,?)',(session.owner,jid))
            session.append('model_request', body, as_of, jid)
        setup.thread = threading.Thread(target=worker, args=(setup, body, as_of), daemon=True)
        try:
            setup.thread.start()
        except RuntimeError:
            session.append('model_failed', {'error_type':'WorkerStartError'}, as_of, jid)
            session.unlock(jid)
            raise
    return {'job_id': jid, 'status': 'running'}


def worker(setup, body, as_of):
    jid = body['request_id']
    with setup.session() as session:
        try:
            funds, positions, pairs = acquire(PublicArchive(setup.directory/'model-research'), as_of)
            run(session, setup.analysis_model(), jid, as_of,
                {k: v for k,v in body.items() if k!='request_id'}, funds, positions, pairs)
        except Exception as exc:
            session.append('model_failed', {'error_type':type(exc).__name__}, as_of, jid)
        finally:
            session.unlock(jid)


def read(session, jid):
    from .portfolio_replay import status_for_proposal
    rows = session.store.db.execute(
        'SELECT * FROM events WHERE owner=? AND run_id=? AND kind IN (?,?,?,?,?) ORDER BY seq DESC',
        (session.owner, jid, 'model_completed', 'model_failed', 'recovery', 'model_request','model_blocked')).fetchall()
    if not rows or not any(r['kind']=='model_request' for r in rows):
        raise PermissionError()
    request_row = next(r for r in rows if r['kind'] == 'model_request')
    terminal = next((r for r in rows if r['kind'] in ('model_completed','model_failed','model_blocked')), None)
    row = session.decode(terminal if terminal is not None else rows[0])
    status = {'model_request':'running','model_completed':'completed','model_failed':'failed',
              'recovery':'interrupted','model_blocked':'blocked'}[row['kind']]
    return {'run_id':jid, 'report_id':row['id'] if status=='completed' else None,
            'status':status, 'as_of':request_row['effective'],
            'portfolio_replay':status_for_proposal(session,row['id']) if status=='completed' else None,
            'result':row['body'] if status!='running' else None}


def run(session, model, jid, as_of, inputs, funds, positions, pairs):
    if model.mode != 'live':
        raise ValueError('Production provider required')
    agent = Agents(session, model, as_of, jid)
    from .knowledge import Knowledge
    knowledge = Knowledge(session, namespace='model_portfolio')
    submissions = []
    years = inputs.get('minimum_holding_years')
    loss = inputs.get('tolerable_drawdown_fraction')
    unknowns = ['정확한 최초 인출 시점' if years is not None else '투자 기간과 인출 시점',
                '실제 초기·월 투입 가능액']
    if loss is None:
        unknowns.append('감내 가능한 손실')
    base = dict(schema_version=VERSION, as_of=as_of, confirmed=inputs, unknowns=unknowns,
                scope='미국 주식 배분 내부 100%, 가계 배분율과 금액 미산출')
    risk_budget = '개인 한도 미확인. 공통 충격 시나리오로 비교'
    if loss is not None:
        risk_budget = {
            'confirmed_tolerance_fraction':loss,
            'interpretation':'잠정적으로 미국 주식 배정분의 원화 기준 고점 대비 낙폭으로 해석. 손실 상한 보장이나 자동 매도선이 아님.',
            'comparison':'고점에서 시작하고 입출금이 없는 가정. 일회 충격과 실제 경로의 최대낙폭을 구별하고, '
                         '주식·환율 동시 충격이 감내 범위를 넘는 정도와 각 대안에서 남는 위험을 설명.',
        }
        base['risk_interpretation'] = risk_budget
    allocation = dict(type='object', minProperties=1, propertyNames={'enum':list(funds)},
                      additionalProperties={'type':'number','minimum':0,'maximum':1})
    refs = dict(type='array',minItems=1,uniqueItems=True,items={'enum':list(funds)})
    revision = fields(target_role={'enum':list(personas())}, requested_change=TEXT)
    changes = dict(type='array', maxItems=len(personas()), items=revision)
    perspective = fields(weights=allocation, evidence_ids=refs, thesis=TEXT, risk=TEXT,
                         benchmark_comparison=TEXT, weight_reason=TEXT, falsifier=TEXT)
    proposal = fields(weights=allocation, evidence_ids=refs, rationale=TEXT, weight_reasons=TEXT,
                      benchmark_comparison=TEXT, dissent=TEXT, risks=TEXT, rebalance=TEXT,
                      scenarios=TEXT, questions=STRINGS, revision_requests=changes)
    review = fields(qualitative_pass={'type':'boolean'}, reason=TEXT, issues=STRINGS,
                    revision_requests=changes)
    def submit(role, stage, contract, inputs_for_role, instruction):
        payload = dict(base, **inputs_for_role, analysis_stage=stage)
        payload['knowledge'] = knowledge.retrieve(as_of,role)
        if role in (*personas(), 'evidence', 'validation', 'leader') and stage != 'leader_mandate':
            payload['leader_mandate'] = leader_mandate.for_role(plan, role)
        def verify(output):
            if 'weights' in output:
                weights(output['weights'])
            requests = output.get('revision_requests', [])
            if len({r['target_role'] for r in requests}) != len(requests):
                raise ContractError('Group corrections by author')
            if output.get('qualitative_pass') and requests:
                raise ContractError('A revision requires a new review')
        guide = role_guide(role) + '\n' + POLICY + '\n' + instruction
        result, output_id=agent.submit_scoped(role, guide, payload, contract, verify, role_knowledge=True)
        submissions.append(output_id)
        return result, output_id
    context, context_id = submit('context','context_analysis',fields(summary=TEXT, conditional_inputs=STRINGS),
        {},'확정 입력과 최소 기간의 의미를 보존하고 나머지는 질문 또는 시나리오로 남겨요.')
    scope = dict(goal=inputs['objective'], candidates=list(funds), model_scope=base['scope'])
    common = dict(decision_scope=scope, user_persona={'body':dict(confirmed=inputs,unknowns=unknowns)},
                  decision_context={'risk_budget':risk_budget},
                  context_analysis=context, funding={'basis':'dimensionless weights only'},
                  profile={'markets':['US'],'constraints':[base['scope']]}, analysis={'comparison':{}},
                  market={'base_currency':'USD'})
    if years is not None:
        common['profile']['constraints'].append(f'최소 {years}년 보유. 해당 연도 말의 인출이나 회복은 확정하지 않음.')
    plan = leader_mandate.run(session, model, role_guide('leader')+'\n'+POLICY, common, context_id,jid,as_of)
    singles = {t:calculate({t:1}, funds, positions) for t in funds}
    market = dict(funds=funds, full_fund_exposures=singles, overlap=pairs, method=METHOD,
                  candidate_basis='동일 운용사의 미국 전체시장, 대형 성장, 대형 가치, 소형 지수. 동일 자료형으로 비교하는 제한된 후보군.',
                  market={'facts':[{'id':t,'source':f['sources'][0]['source']} for t,f in funds.items()]})
    if loss is not None:
        # Fixed comparison size mirrors the existing style-tilt sensitivity, not a personal target.
        market['style_comparisons'] = {
            ticker:calculate({'ITOT':.85, ticker:.15}, funds, positions)
            for ticker in funds if ticker != 'ITOT'}
    evidence, eid = submit('evidence','evidence_analysis',fields(summary=TEXT,evidence_ids=refs,gaps=STRINGS),
                           market, '상품과 보유 자료의 날짜·잔여분과 해석 한계를 점검해요.')
    shared = dict(market, evidence=evidence, evidence_output_id=eid)
    views = {}
    def analyze(role, correction=None):
        result, oid = submit(role, 'perspective_analysis', perspective,
            dict(shared, revision_instructions=correction) if correction else shared,
            '자신의 분석 관점으로 단순 기준안과 편향 대안을 비교하고 독립 비중을 제출해요.')
        views[role] = dict(output_id=oid, output=result,
                           metrics=calculate(result['weights'],funds,positions))
    for role in personas():
        analyze(role)
    last_feedback = {}
    for cycle in range(3):
        sources = dict(shared, perspectives=copy.deepcopy(views), **last_feedback)
        first, first_id = submit('validation','perspective_validation',review,sources,
            '각 관점의 비교 논리·수치·미확인 조건을 검사해요. 수정이 필요하면 해당 관점에만 요청해요.')
        revisions = first['revision_requests']
        requester = first_id
        if not revisions and first['qualitative_pass']:
            final, leader_id = submit('leader','proposal_synthesis',proposal,
                dict(sources,perspective_validation=first, validation_output_id=first_id),
                '관점들의 대안을 종합해 채택 비중과 조정 조건을 정해요. 자료로 구별할 수 없는 배분은 단순 기준안도 허용해요.')
            revisions, requester = final['revision_requests'], leader_id
            if not revisions:
                metrics = calculate(final['weights'],funds,positions)
                frozen = dict(sources, proposal=final, leader_output_id=leader_id,
                              leader_mandate=leader_mandate.for_role(plan,'leader'),
                              perspective_validation=first, validation_output_id=first_id,
                              final_metrics=metrics, benchmark=singles['ITOT'])
                check, check_id = submit('validation','final_validation',review,frozen,
                    '최신 리더 제출과 재계산값을 직접 대조해요. 설명·계산이 충돌하면 실패 이유와 필요한 수정을 적어요.')
                if check['qualitative_pass']:
                    rating, qid = submit('evaluator','frozen_quality_review',
                        fields(summary=TEXT, limitations=STRINGS),dict(frozen,final_validation=check),
                        '동결된 결론과 계산을 독립 평가해요. 근거 강도와 미검증 범위를 구체화해요.')
                    report = dict(base, mandate=plan, evidence=evidence, funds=funds, overlap=pairs,
                        measurement=METHOD, perspectives=views, proposal=final, metrics=metrics,
                        benchmark=singles['ITOT'], final_validation=check, quality_review=rating,
                        accepted_ids=dict(context=context_id,evidence=eid,leader=leader_id,validation=check_id,quality=qid))
                    from .portfolio_replay import status_for_proposal
                    report['portfolio_replay']=status_for_proposal()
                    from .role_knowledge import record
                    with session.store.transaction():
                        report['role_knowledge_updates']=record(knowledge,as_of,jid,submissions)
                        report['role_knowledge_pruning_id']=knowledge.prune(as_of,jid)
                        session.append('model_completed',report,as_of,jid)
                    return
                revisions, requester = check['revision_requests'], check_id
                last_feedback = {'previous_leader':final,'required_review':check,'review_output_id':check_id}
        if cycle == 2 or (not revisions and not last_feedback):
            session.append('model_blocked',dict(reason='검증 미통과',review_output_id=requester),as_of,jid)
            return
        for item in revisions:
            target = item['target_role']
            correction = dict(item,requester_output_id=requester,source_output_id=views[target]['output_id'],
                              prior_output=views[target]['output'])
            session.append('model_revision',correction,as_of,jid)
            analyze(target, correction)
