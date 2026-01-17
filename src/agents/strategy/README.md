# Strategy Design Layer

투자 프로필별 맞춤형 자산 배분 전략을 수립하는 레이어입니다.

## 책임 (Responsibilities)

- Macro Insight를 바탕으로 구체적인 포트폴리오 생성
- 투자자 프로필별 차별화된 전략 (Growth vs Income)
- 동적 현금 비중 조절
- 리밸런싱 계획 수립

## Agent 구조

### 1. Growth Strategy Agent (`growth_agent.py`)
**대상**: 근로소득이 있는 공격적 투자자

**전략 특징**:
- 높은 주식 비중 (70-90%)
- 섹터 로테이션 적극 활용
- 개별 종목보다 섹터 ETF 선호
- 변동성 허용 범위 높음 (Max DD 30-40%)

**입력**:
- MarketState (from Macro Layer)
- Current Portfolio
- Risk Profile (from config)

**출력**:
```json
{
  "target_allocation": {
    "cash": 0.10,
    "bonds": 0.10,
    "equities": 0.80
  },
  "equity_sectors": {
    "technology": 0.35,
    "healthcare": 0.20,
    "financials": 0.15,
    "energy": 0.10
  },
  "rebalancing_actions": [
    {"action": "buy", "ticker": "XLK", "weight_change": 0.05},
    {"action": "sell", "ticker": "XLE", "weight_change": -0.03}
  ],
  "rationale": "AI 모멘텀 지속, 에너지 사이클 후반부 진입"
}
```

### 2. Income Strategy Agent (`income_agent.py`)
**대상**: 은퇴 자산 보호 및 현금흐름 창출

**전략 특징**:
- 안정적 배당 + 인플레이션 헤지 (TIPS, 금)
- 낮은 변동성 목표 (Max DD 15-20%)
- 월 0.25% (연 3%) 현금흐름 창출
- 원금 보존 우선

**입력**:
- MarketState
- Required Cash Flow (월 필요 금액)
- Risk Tolerance (낮음)

**출력**:
```json
{
  "target_allocation": {
    "cash": 0.15,
    "bonds": 0.40,
    "dividend_stocks": 0.30,
    "reits": 0.10,
    "gold": 0.05
  },
  "expected_yield": 0.032,
  "inflation_hedge": 0.45,
  "max_drawdown_estimate": 0.18,
  "cash_flow_plan": {
    "monthly_distribution": 5000000,
    "sources": ["dividend", "bond_coupon", "reit_distribution"]
  }
}
```

### 3. Cash Management Agent (`cash_agent.py`)
**전략**: 동적 현금 비중 조절

**로직**:
- **기본 현금 비중**: 20%
- **시장 하락 시 (VIX > 25)**: 현금 비중 줄임 (10-15%) → 저점 매수
- **시장 과열 시 (Valuation 높음)**: 현금 비중 늘림 (25-30%) → 수익 실현

**입력**:
- MarketState.regime
- VIX Level
- Valuation Metrics (P/E, CAPE)
- Current Cash Position

**출력**:
```json
{
  "target_cash_ratio": 0.15,
  "reason": "VIX 급등 (32), 저점 매수 기회",
  "action": "deploy_cash",
  "amount": 10000000
}
```

## Profile Configuration

각 투자자 프로필은 YAML로 정의됩니다.

### `config/profiles/growth.yaml`
```yaml
profile: growth
risk_tolerance: high
investment_horizon: 10_years
constraints:
  max_single_sector: 0.40
  max_drawdown_tolerance: 0.35
  min_cash_ratio: 0.05
  max_cash_ratio: 0.30
preferences:
  sector_rotation: true
  individual_stocks: false
  leverage: false
```

### `config/profiles/income.yaml`
```yaml
profile: income
risk_tolerance: low
investment_horizon: indefinite
constraints:
  max_drawdown_tolerance: 0.20
  min_cash_ratio: 0.10
  max_cash_ratio: 0.25
  required_annual_yield: 0.03
preferences:
  dividend_focus: true
  inflation_hedge: true
  principal_protection: true
```

## 구현 가이드라인

1. **Portfolio Optimization**
   - Mean-Variance Optimization (Markowitz) 기본 활용
   - Constraint 기반 최적화 (cvxpy 라이브러리)

2. **Transaction Cost 고려**
   - 작은 변화(< 2%)는 리밸런싱 안 함
   - 거래 비용 및 세금 고려

3. **리밸런싱 우선순위**
   - 신규 입금 활용 우선 (매도 최소화)
   - 큰 괴리만 조정

4. **시나리오 분석**
   - 제안한 포트폴리오를 2008, 2020 시나리오에서 테스트
   - Stress Test 결과 첨부

## 출력 스키마

```python
@dataclass
class StrategyState:
    profile: str  # "growth" or "income"
    target_allocation: Dict[str, float]
    rebalancing_actions: List[Action]
    expected_return: float
    expected_risk: float
    rationale: str
    citations: List[str]
    timestamp: datetime
```
