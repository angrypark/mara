# Validation Layer

제안된 포트폴리오의 백테스팅 및 리스크 검증을 수행하는 레이어입니다.

## 책임 (Responsibilities)

- 백테스팅을 통한 과거 성과 시뮬레이션
- 사용자 정의 리스크 조건 충족 여부 확인 (MDD, VaR 등)
- Strategy Layer로 피드백 전달
- 최종 승인/거부 결정

## 구조

```
validation/
└── validator.py         # 리스크 조건 검증, 피드백 생성
```

## Tools 연동

Validation Layer는 `src/tools/analysis/`의 도구들을 호출합니다:

| Tool | 기능 | 위치 |
|------|------|------|
| **Backtest Tool** | 포트폴리오 과거 성과 시뮬레이션 | `src/tools/analysis/backtest.py` |
| **Risk Tool** | MDD, VaR, Volatility, Beta 계산 | `src/tools/analysis/risk.py` |

## 검증 프로세스

### 1. Backtest

제안된 포트폴리오를 과거 데이터로 시뮬레이션합니다.

```python
# Backtest 결과 예시
{
    "period": "2015-01-01 to 2025-01-01",
    "total_return": 1.52,
    "annualized_return": 0.143,
    "annualized_volatility": 0.185,
    "max_drawdown": -0.284,
    "sharpe_ratio": 0.77,
    "sortino_ratio": 1.02,
    "calmar_ratio": 0.50
}
```

### 2. Risk Check

사용자가 정의한 리스크 조건 충족 여부를 확인합니다.

| 지표 | 설명 | 사용자 정의 예시 |
|------|------|------------------|
| **Maximum Drawdown (MDD)** | 고점 대비 최대 하락폭 | "20% 이상 빠지면 안 된다" |
| **Volatility** | 수익률의 표준편차 | "연간 변동성 15% 이내" |
| **Value at Risk (VaR)** | 95% 신뢰구간 최대 손실 | "월 VaR 5% 이내" |
| **Beta** | 시장 대비 민감도 | "Beta 0.8 이하로 방어적" |

## Output Schema

### ValidationResult

```python
class ValidationResult(BaseModel):
    """Validation Layer 출력"""
    is_approved: bool
    iteration: int                    # 현재 반복 횟수 (1-3)
    risk_metrics: dict[str, float]    # {"mdd": 0.18, "volatility": 0.12, ...}
    violations: list[str]             # 위반된 조건들
    feedback: str | None              # Strategy Layer로 보낼 피드백 (미승인 시)
    backtest_summary: dict            # {"sharpe": 1.2, "cagr": 0.08, ...}
```

## Strategy ↔ Validation Loop

Validation Layer는 Strategy Layer와 피드백 루프를 형성합니다 (최대 3회).

### Loop 종료 조건

| 결과 | 조건 | 동작 |
|------|------|------|
| **성공** | 모든 리스크 조건 충족 | 최종 승인, Retrospection Layer로 전달 |
| **부분 승인** | 3회 후에도 일부 조건 미충족 | 위반 사항 명시 + 사용자 확인 요청 |
| **거부** | 핵심 리스크 조건(MDD) 위반 | 보수적 대안 제시 |

### 피드백 예시

```python
{
    "is_approved": False,
    "iteration": 2,
    "violations": ["MDD -28%가 목표 -20% 초과"],
    "feedback": "기술주 비중을 30% → 20%로 줄이고 채권 비중 10% 추가 권장"
}
```

## 에러 핸들링

### Fallback 전략

- **Backtest 실패**: 리스크 메트릭만으로 검증 진행 (`backtest_skipped` 경고 표시)

## 검증 임계값 설정

`src/config/thresholds.yaml`에서 프로필별 검증 기준을 설정합니다:

```yaml
validation:
  growth:
    max_drawdown: 0.35        # 35% 이내
    min_sharpe: 0.50
    min_annual_return: 0.07   # 연 7% 이상

  income:
    max_drawdown: 0.20        # 20% 이내
    min_sharpe: 0.30
    min_annual_return: 0.03   # 연 3% 이상
```

## 구현 가이드라인

1. **데이터 품질 체크**
   - 결측치 처리 (forward fill)
   - 이상치 탐지 (circuit breaker 고려)

2. **백테스팅 정확성**
   - Survivorship Bias 제거 (상장 폐지 종목 포함)
   - Look-ahead Bias 방지 (미래 정보 사용 금지)

3. **피드백 구체화**
   - 단순 "실패"가 아닌 구체적 개선 방향 제시
   - 어떤 자산을 얼마나 조정해야 하는지 명시

4. **시각화**
   - Cumulative Return Chart
   - Drawdown Chart
   - Rolling Sharpe Ratio

## 필수 라이브러리

- `pandas`: 데이터 처리
- `numpy`: 수치 계산
- `scipy`: 통계 분석
