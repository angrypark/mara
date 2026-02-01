# Strategy Layer

여러 Perspective Agent의 제안을 종합하여 최종 포트폴리오 조정 방향을 제시하는 레이어입니다.

## 책임 (Responsibilities)

- 다중 Perspective Agent 제안 종합
- 각 Agent의 신뢰도(과거 성과 기반) 가중치 적용
- cvxpy 기반 포트폴리오 최적화
- 최종 포트폴리오 조정 방향 제시

## 구조

```
strategy/
├── aggregator.py        # 다중 Agent 제안 종합
└── optimizer.py         # cvxpy 기반 포트폴리오 최적화
```

## 주요 모듈

### `aggregator.py`

여러 Perspective Agent의 리밸런싱 제안을 종합합니다.

```python
def aggregate_proposals(
    proposals: list[PerspectiveOutput],
    weights: dict[str, float]  # agent_id -> weight
) -> AggregatedProposal:
    """
    다수의 Perspective Agent 제안을 가중 평균으로 종합

    Args:
        proposals: 각 Perspective Agent의 출력
        weights: Agent별 신뢰도 가중치 (과거 성과 기반)

    Returns:
        종합된 리밸런싱 제안
    """
```

### `optimizer.py`

Mean-Variance Optimization을 통해 최적 포트폴리오를 계산합니다.

```python
def optimize_portfolio(
    expected_returns: np.ndarray,
    cov_matrix: np.ndarray,
    constraints: dict
) -> np.ndarray:
    """
    cvxpy 기반 포트폴리오 최적화

    Constraints:
    - 가중치 합 = 1
    - 숏 금지 (weights >= 0)
    - 단일 자산 최대 비중
    - 최대 변동성
    """
```

## Output Schema

### PortfolioAllocation

```python
class PortfolioAllocation(BaseModel):
    """최종 포트폴리오 배분"""
    ticker: str
    weight: float                     # 비중 (0-1)
    rationale: str                    # 배분 근거
```

### StrategyOutput

```python
class StrategyOutput(BaseModel):
    """Strategy Layer 출력"""
    timestamp: datetime
    allocations: list[PortfolioAllocation]
    total_weight: float               # 합계 = 1.0
    dominant_perspective: str         # 가장 영향력 있던 Agent
    dissenting_views: list[str]       # 반대 의견 요약
```

## Strategy ↔ Validation Loop

Strategy Layer는 Validation Layer와 피드백 루프를 형성합니다 (최대 3회).

```
┌─────────────────┐         ┌─────────────────┐
│  Strategy Layer │         │ Validation Layer│
└────────┬────────┘         └────────┬────────┘
         │                           │
         │  1. 전략 제안             │
         │──────────────────────────▶│
         │                           │
         │  2. 리스크 검증 결과      │
         │◀──────────────────────────│
         │     (비율 수정 피드백)    │
         │                           │
         │  3. 수정된 전략 제안      │
         │──────────────────────────▶│
         │                           │
         ▼                           ▼
```

### Loop 종료 조건

- **성공**: 모든 리스크 조건 충족
- **부분 승인**: 3회 반복 후에도 일부 조건 미충족 시, 위반 사항 명시 + 사용자 확인 요청
- **거부**: 핵심 리스크 조건(MDD) 위반 시 보수적 대안 제시

## Agent 가중치

Agent별 가중치는 `src/config/ensemble_weights.yaml`에서 설정합니다:

```yaml
strategy_ensemble:
  growth:
    ray_dalio_macro: 0.30
    sector_rotation: 0.40
    geopolitical: 0.20
    monetary: 0.10

  income:
    ray_dalio_macro: 0.40
    sector_rotation: 0.20
    geopolitical: 0.20
    monetary: 0.20
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

4. **반대 의견 기록**
   - 다수 의견과 다른 Agent의 의견도 기록
   - 추후 Retrospection에서 활용

## 필수 라이브러리

- `cvxpy`: 포트폴리오 최적화
- `numpy`: 수치 계산
- `pandas`: 데이터 처리
