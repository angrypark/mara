# Validation Layer

제안된 포트폴리오의 정량적 검증 및 리스크 분석을 수행하는 레이어입니다.

## 책임 (Responsibilities)

- 백테스팅을 통한 과거 성과 시뮬레이션
- 리스크 메트릭 계산 (Sharpe, Max DD, VaR)
- Stress Testing (극한 시나리오)
- 벤치마크 대비 성과 비교

## 주요 모듈

### 1. Backtesting Engine (`backtester.py`)

**기능**:
- 제안된 포트폴리오를 과거 10년 데이터로 시뮬레이션
- 월별 리밸런싱 가정
- 거래 비용 반영 (0.1% 수수료)

**입력**:
- StrategyState.target_allocation
- Historical Price Data (10년)
- Rebalancing Frequency (기본: 월별)

**출력**:
```json
{
  "period": "2015-01-01 to 2025-01-01",
  "total_return": 0.152,
  "annualized_return": 0.143,
  "annualized_volatility": 0.185,
  "max_drawdown": -0.284,
  "sharpe_ratio": 0.77,
  "sortino_ratio": 1.02,
  "calmar_ratio": 0.50,
  "win_rate": 0.62
}
```

### 2. Risk Metrics Calculator (`risk_metrics.py`)

**계산 메트릭**:

1. **Sharpe Ratio**: (수익률 - 무위험수익률) / 변동성
2. **Sortino Ratio**: 하방 변동성만 고려한 Sharpe
3. **Max Drawdown**: 최대 손실 구간
4. **VaR (Value at Risk)**: 95% 신뢰구간 최대 손실
5. **CVaR (Conditional VaR)**: VaR 초과 시 평균 손실
6. **Beta**: 시장 대비 민감도
7. **Tracking Error**: 벤치마크와의 괴리

**코드 예시**:
```python
def calculate_risk_metrics(
    returns: pd.Series,
    benchmark_returns: pd.Series = None,
    risk_free_rate: float = 0.04
) -> RiskMetrics:
    """
    포트폴리오의 리스크 메트릭 계산
    """
    sharpe = (returns.mean() - risk_free_rate) / returns.std()
    max_dd = calculate_max_drawdown(returns)
    var_95 = returns.quantile(0.05)
    cvar_95 = returns[returns < var_95].mean()

    return RiskMetrics(
        sharpe_ratio=sharpe,
        max_drawdown=max_dd,
        var_95=var_95,
        cvar_95=cvar_95,
        ...
    )
```

### 3. Stress Testing (`stress_test.py`)

**시나리오**:
1. **2008 금융위기**: -50% 주식 하락
2. **2020 코로나**: -35% 급락 후 빠른 회복
3. **2022 인플레이션**: 주식/채권 동반 하락
4. **2000 닷컴 버블**: 기술주 70% 하락

**출력**:
```json
{
  "scenario": "2008_financial_crisis",
  "portfolio_return": -0.38,
  "benchmark_return": -0.50,
  "relative_performance": 0.12,
  "recovery_time_months": 18,
  "passed": true
}
```

### 4. Benchmark Comparison (`benchmark.py`)

**벤치마크**:
- **Growth Profile**: 60/40 포트폴리오 (SPY 60% + AGG 40%)
- **Income Profile**: 배당 ETF (SCHD, VYM)
- **All-Weather**: Ray Dalio All-Weather Portfolio

**비교 지표**:
- 수익률 차이
- 리스크 조정 수익률 (Sharpe)
- 최대 낙폭 비교
- 상승/하락 시장 성과

**출력**:
```json
{
  "benchmark": "60_40_portfolio",
  "outperformance": 0.023,
  "better_sharpe": true,
  "lower_drawdown": true,
  "verdict": "PASS"
}
```

## Validation Rules

검증 통과 조건:

1. **수익률**:
   - Growth: 연 7% 이상
   - Income: 연 3% 이상 (배당 포함)

2. **Max Drawdown**:
   - Growth: -35% 이내
   - Income: -20% 이내

3. **Sharpe Ratio**:
   - Growth: > 0.5
   - Income: > 0.3

4. **Stress Test**:
   - 모든 시나리오에서 벤치마크 대비 -5% 이내

**실패 시 동작**:
- Critic Layer에 경고 전달
- Strategy Layer로 피드백 (재조정 요청)

## 구현 가이드라인

1. **데이터 품질 체크**
   - 결측치 처리 (forward fill)
   - 이상치 탐지 (circuit breaker 고려)

2. **백테스팅 정확성**
   - Survivorship Bias 제거 (상장 폐지 종목 포함)
   - Look-ahead Bias 방지 (미래 정보 사용 금지)

3. **성능 최적화**
   - Vectorized Operations (NumPy/Pandas)
   - 병렬 처리 (Joblib)

4. **시각화**
   - Cumulative Return Chart
   - Drawdown Chart
   - Rolling Sharpe Ratio

## 출력 스키마

```python
@dataclass
class ValidationState:
    backtest_results: BacktestResult
    risk_metrics: RiskMetrics
    stress_test_results: List[StressTestResult]
    benchmark_comparison: BenchmarkComparison
    validation_passed: bool
    warnings: List[str]
    timestamp: datetime
```

## 필수 라이브러리

- `pandas`: 데이터 처리
- `numpy`: 수치 계산
- `scipy`: 통계 분석
- `cvxpy`: 포트폴리오 최적화
- `matplotlib/plotly`: 시각화
- `quantstats`: 성과 분석 (선택)
