"""Application-authored diagnostics; never expose provider errors or private values."""
from .contracts import ContractError
from .registry import agent


REASONS={
    'judgment_report':'상세 판단 리포트의 필수 내용·본문 분량·기준일·근거 연결을 충족하지 못했어요.',
    'proposal_reference':'주장 또는 대안이 실제 계산 결과와 연결되지 않아요. 리더의 계산 연결 검증 내역을 확인해주세요.',
    'market_evidence_reference':'시장 근거 목록에 없는 ID를 인용했어요.',
    'market_evidence_missing':'판단에 사용한 시장 근거 ID를 제시하지 않았어요.',
    'weight_total':'제안 비중의 합이 100%가 아니에요.',
    'output_contract':'응답이 정해진 출력 형식 또는 검증 조건을 충족하지 못했어요.',
}


def issue_code(exc):
    if str(exc).startswith('Judgment report:'):return 'judgment_report'
    # Match only errors produced by local validation, never arbitrary exception text.
    return {'Invented evidence ID':'market_evidence_reference',
            'Evidence references required':'market_evidence_missing',
            'Weights must sum to one':'weight_total'}.get(str(exc),'output_contract')


class AgentOutputError(ContractError):
    def __init__(self,role,code,output_id,attempts=2):
        self.details={'role':role,'code':code,'output_id':output_id,'attempts':attempts}
        repair=' 한 번 교정했지만 같은 검증을 통과하지 못해 분석을 멈췄어요.' if attempts>1 else ' 이 응답은 채택하지 않고 분석을 멈췄어요.'
        self.message=agent(role)['label']+' 응답 검증 실패: '+REASONS[code]+repair+' 저장한 입력과 답변은 유지돼요. 다시 생성하면 이 조건을 검사해요.'
        super().__init__(self.message)


def failed_job_diagnostic(session,job):
    """Read-only classification of old generic failures; never reinterpret successes."""
    if job['body'].get('status')!='failed' or job['body'].get('error_type') not in ('ValueError','ContractError'):return None
    starts=[x for x in session.events('onboarding_job') if x['body']['id']==job['body']['id'] and x['body']['status']=='running' and x['seq']<job['seq']]
    if not starts:return None
    failures=[x for x in session.events('failed') if starts[0]['seq']<x['seq']<job['seq']]
    if not failures:return None
    run_id=failures[-1]['run_id']
    rows=session.store.db.execute('SELECT * FROM events WHERE owner=? AND run_id=? AND kind IN (?,?) ORDER BY seq',
        (session.owner,run_id,'agent_input','agent_output')).fetchall()
    if len(rows)<2:return None
    inp,out=[session.decode(x) for x in rows[-2:]]
    if inp['kind']!='agent_input' or out['kind']!='agent_output' or out['body'].get('input_id')!=inp['id']:return None
    from .agents import validate_output
    try:validate_output(out['body']['role'],out['body']['output'],inp['body']['payload'])
    except (ValueError,TypeError,KeyError) as exc:
        return AgentOutputError(out['body']['role'],issue_code(exc),out['id'],attempts=1)
    return None
