"""Synthetic prose for flow tests; never used by production providers."""
from mara.agents import DemoModel
from mara.judgment_reports import VERSION,SECTIONS


def narrative(payload):
    explanations={
        'portfolio_context':'현재 보유 기록과 향후 납입 계획의 금액 범위는 서로 다릅니다. 이 합성 보고서는 사용자의 실제 자산이나 거래 결과를 설명하지 않으며 원본 입력의 소유 관계와 기준일을 검사하기 위한 테스트 문서입니다. 기존 현금은 예정 납입에 더하지 않고 별도 보유 기록으로 유지하며 투자 목적과 명시된 손실 한도도 자동 변경하지 않습니다. ',
        'market_context':'시장 상황은 입력에 포함된 합성 근거만으로 기술합니다. 관측일과 알려진 시점이 다른 자료는 실제 최신 시세로 표현하지 않으며 거래 비용이나 환율의 미래 방향을 보장하지 않습니다. 단일 출처가 여러 번 등장하더라도 독립적인 증거의 수가 증가한 것으로 해석하지 않고 원래 출처와 연결을 보존합니다. ',
        'decision_method':'검토 방법은 입력된 비중과 수치 제약을 대조하고 현재 보유와 신규 계획의 차이를 확인하는 것입니다. 대안의 위험과 비용을 같은 기준으로 비교하되 특정 투자자의 실제 견해나 성과를 모사했다고 주장하지 않습니다. 검증 과정에서 생긴 자료 공백과 반대 근거는 결과에 남기고 별도 평가 단계가 확인할 수 있도록 합니다. ',
        'conclusion':'최종 의견은 합성 연결 검증에 한정합니다. 사용자의 승인이나 주문 실행을 대신하지 않으며 결과의 숫자는 실제 금융 성과가 아닙니다. 신규 납입 선호와 기존 한도가 충돌하는 경우 한도를 조용히 바꾸지 않고 제약을 설명해야 합니다. 이후의 자료 변화와 실제 입력 수정이 확인되면 별도의 버전으로 판단을 다시 남겨야 합니다. '
    }
    return {'schema_version':VERSION,'title':'합성 상세 판단 보고서','as_of':payload['as_of'],
        **{k:explanations[k]+''.join(f'검증 항목 {i+1}에서는 {explanations[k]}' for i in range(2)) for k in SECTIONS},
        'evidence_ids':[f['id'] for f in payload.get('market',{}).get('facts',[])][:2]}


def attach(result,payload):
    if payload.get('narrative_contract') and isinstance(result,dict) and 'judgment_report' not in result:
        result['judgment_report']=narrative(payload)
    return result


def with_reports(model):
    original=model.complete
    def complete(role,guide,payload,contract):
        result=original(role,guide,payload,contract)
        return attach(result,payload) if 'judgment_report' in contract.get('properties',{}) else result
    model.complete=complete
    return model


class ReportingDemoModel(DemoModel):
    def complete(self,role,guide,payload,contract):
        result=super().complete(role,guide,payload,contract)
        return attach(result,payload) if 'judgment_report' in contract.get('properties',{}) else result
