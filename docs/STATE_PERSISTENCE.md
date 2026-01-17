# State Persistence Design

## Overview

MARA는 예측 결과를 저장하고, 다음 실행 시 과거 데이터를 참고하며, 성과 분석을 추가하는 영속성 시스템을 제공합니다.

## Database Schema

### Technology Choice

**SQLite** (초기) → **PostgreSQL** (프로덕션)

- SQLite: 간단한 설정, 파일 기반, 로컬 개발용
- PostgreSQL: 확장성, 동시성, 프로덕션용

## Tables

### 1. `users` - 사용자 정보

```sql
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,  -- 'marv', 'parents'
    name TEXT NOT NULL,
    profile TEXT NOT NULL,  -- 'growth', 'income'
    flow TEXT NOT NULL,  -- 'growth', 'income'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Example data
INSERT INTO users VALUES
('marv', 'Marv', 'growth', 'growth', '2025-01-17', '2025-01-17'),
('parents', 'Parents', 'income', 'income', '2025-01-17', '2025-01-17');
```

### 2. `portfolios` - 포트폴리오 스냅샷

현재 보유 자산 저장 (입력 및 결과)

```sql
CREATE TABLE portfolios (
    portfolio_id TEXT PRIMARY KEY,  -- UUID
    user_id TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    portfolio_type TEXT NOT NULL,  -- 'current', 'recommended'
    total_value DECIMAL(15, 2),
    holdings JSONB NOT NULL,  -- {"SPY": {"shares": 100, "value": 45000}, ...}
    allocation JSONB NOT NULL,  -- {"cash": 0.30, "XLK": 0.25, ...}
    metadata JSONB,  -- 추가 정보

    FOREIGN KEY (user_id) REFERENCES users(user_id),
    UNIQUE (user_id, snapshot_date, portfolio_type)
);

CREATE INDEX idx_portfolios_user_date ON portfolios(user_id, snapshot_date);
```

**Example**:
```json
{
    "portfolio_id": "550e8400-e29b-41d4-a716-446655440001",
    "user_id": "marv",
    "snapshot_date": "2025-01-17",
    "portfolio_type": "current",
    "total_value": 100000000,
    "holdings": {
        "SPY": {"shares": 100, "value": 45000000, "cost_basis": 40000000},
        "QQQ": {"shares": 50, "value": 22000000, "cost_basis": 18000000},
        "cash": {"value": 33000000}
    },
    "allocation": {
        "SPY": 0.45,
        "QQQ": 0.22,
        "cash": 0.33
    }
}
```

### 3. `predictions` - 예측 결과 저장

```sql
CREATE TABLE predictions (
    prediction_id TEXT PRIMARY KEY,  -- 'marv_2025-01-17'
    user_id TEXT NOT NULL,
    flow TEXT NOT NULL,
    prediction_date DATE NOT NULL,

    -- Input State
    input_portfolio_id TEXT NOT NULL,

    -- Macro Analysis
    market_regime TEXT,  -- 'bull', 'bear', 'sideways', 'volatile'
    macro_insights JSONB,

    -- Strategy
    recommended_strategy TEXT,  -- 'Aggressive Growth', 'Balanced', etc.
    target_allocation JSONB,
    expected_return DECIMAL(5, 4),  -- 0.0800 = 8%
    expected_volatility DECIMAL(5, 4),
    expected_sharpe DECIMAL(5, 4),
    expected_max_dd DECIMAL(5, 4),

    -- Rebalancing
    rebalancing_method TEXT,
    rebalancing_actions JSONB,

    -- Full Report
    report_markdown TEXT,
    report_path TEXT,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (input_portfolio_id) REFERENCES portfolios(portfolio_id)
);

CREATE INDEX idx_predictions_user_date ON predictions(user_id, prediction_date);
```

**Example**:
```json
{
    "prediction_id": "marv_2025-01-17",
    "user_id": "marv",
    "flow": "growth",
    "prediction_date": "2025-01-17",
    "input_portfolio_id": "550e8400-e29b-41d4-a716-446655440001",
    "market_regime": "bull",
    "macro_insights": {
        "sector_outlook": {"technology": 0.12, "healthcare": 0.08},
        "themes": ["ai_infrastructure"]
    },
    "recommended_strategy": "Balanced Growth",
    "target_allocation": {
        "cash": 0.15,
        "XLK": 0.30,
        "XLV": 0.25,
        "AGG": 0.15,
        "XLF": 0.15
    },
    "expected_return": 0.09,
    "expected_volatility": 0.18,
    "expected_sharpe": 0.50,
    "expected_max_dd": -0.25,
    "rebalancing_method": "cash_flow_based",
    "rebalancing_actions": [
        {"action": "buy", "ticker": "XLK", "amount": 5000000}
    ],
    "report_path": "outputs/reports/2025-01-17_growth_report.md"
}
```

### 4. `performance_results` - 실제 성과 (Retrospection)

```sql
CREATE TABLE performance_results (
    result_id TEXT PRIMARY KEY,
    prediction_id TEXT NOT NULL,
    user_id TEXT NOT NULL,

    -- 성과 분석 기간
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,

    -- 실제 성과
    actual_return DECIMAL(5, 4),
    actual_volatility DECIMAL(5, 4),
    actual_sharpe DECIMAL(5, 4),
    actual_max_dd DECIMAL(5, 4),

    -- 예측 vs 실제 비교
    return_error DECIMAL(5, 4),  -- actual - expected
    prediction_accuracy DECIMAL(5, 4),  -- 0.0 to 1.0

    -- 섹터별 성과
    sector_performance JSONB,  -- {"technology": 0.10, "healthcare": 0.05}

    -- Agent별 성과 기여도
    agent_attribution JSONB,

    -- 분석 완료 시각
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (prediction_id) REFERENCES predictions(prediction_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX idx_results_prediction ON performance_results(prediction_id);
```

**Example**:
```json
{
    "result_id": "result_marv_2025-01-17",
    "prediction_id": "marv_2025-01-17",
    "user_id": "marv",
    "start_date": "2025-01-17",
    "end_date": "2025-02-17",
    "actual_return": 0.06,  // 예측 0.09, 실제 0.06
    "actual_volatility": 0.20,
    "actual_sharpe": 0.45,
    "actual_max_dd": -0.12,
    "return_error": -0.03,  // 3% 낮음
    "prediction_accuracy": 0.67,
    "sector_performance": {
        "technology": 0.10,  // 예측 0.12, 실제 0.10
        "healthcare": 0.11   // 예측 0.08, 실제 0.11 (초과)
    },
    "agent_attribution": {
        "sector_rotation_agent": {"accuracy": 0.62, "impact": -0.01},
        "monetary_agent": {"accuracy": 0.75, "impact": 0.02}
    }
}
```

### 5. `agent_performance` - Agent별 성과 추적

```sql
CREATE TABLE agent_performance (
    record_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,

    -- 누적 통계 (rolling)
    total_predictions INTEGER DEFAULT 0,
    accurate_predictions INTEGER DEFAULT 0,
    accuracy_rate DECIMAL(5, 4),  -- accurate / total

    -- 최근 6개월 성과
    recent_accuracy DECIMAL(5, 4),

    -- 가중치 조정
    current_weight DECIMAL(5, 4),
    recommended_weight DECIMAL(5, 4),

    -- 업데이트 시각
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(user_id),
    UNIQUE (user_id, agent_name)
);
```

### 6. `execution_logs` - 실행 로그

```sql
CREATE TABLE execution_logs (
    log_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    flow TEXT NOT NULL,
    execution_date TIMESTAMP NOT NULL,

    status TEXT NOT NULL,  -- 'running', 'completed', 'failed'
    layers_completed JSONB,  -- ["portfolio_input", "data", "macro"]

    error_message TEXT,
    execution_time_seconds INTEGER,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
```

## Data Flow

### 1. 첫 번째 실행 (예측)

```python
# 1. 사용자 입력 (current_portfolio.yaml)
current_portfolio = load_yaml("inputs/marv_current_portfolio.yaml")

# 2. Portfolio 스냅샷 저장
portfolio_id = save_portfolio(
    user_id="marv",
    snapshot_date="2025-01-17",
    portfolio_type="current",
    holdings=current_portfolio["holdings"]
)

# 3. Flow 실행
result = run_flow(flow="growth", user_id="marv", portfolio_id=portfolio_id)

# 4. Prediction 저장
prediction_id = save_prediction(
    user_id="marv",
    prediction_date="2025-01-17",
    input_portfolio_id=portfolio_id,
    recommended_strategy=result["strategy"],
    target_allocation=result["allocation"],
    expected_metrics=result["metrics"]
)

# 5. 리포트 저장
save_report(
    prediction_id=prediction_id,
    markdown=result["report"],
    path="outputs/reports/2025-01-17_growth_report.md"
)
```

### 2. 다음 달 실행 (성과 분석 + 새 예측)

```python
# 1. 이전 예측 조회
previous_prediction = get_latest_prediction(user_id="marv")
# prediction_id: "marv_2025-01-17"
# expected_return: 0.09
# target_allocation: {...}

# 2. 현재 포트폴리오 입력
current_portfolio = load_yaml("inputs/marv_current_portfolio.yaml")

# 3. 성과 분석 (Retrospection Layer)
actual_return = calculate_actual_return(
    previous_allocation=previous_prediction["target_allocation"],
    start_date="2025-01-17",
    end_date="2025-02-17"
)

performance_result = analyze_performance(
    prediction=previous_prediction,
    actual_return=actual_return,
    period=("2025-01-17", "2025-02-17")
)

# 4. Performance Result 저장
save_performance_result(
    prediction_id=previous_prediction["prediction_id"],
    actual_return=actual_return,
    prediction_accuracy=performance_result["accuracy"],
    agent_attribution=performance_result["agent_scores"]
)

# 5. Agent 가중치 업데이트 (선택적)
update_agent_weights(
    user_id="marv",
    agent_scores=performance_result["agent_scores"]
)

# 6. 새로운 예측 실행 (과거 데이터 참고)
new_result = run_flow(
    flow="growth",
    user_id="marv",
    portfolio_id=new_portfolio_id,
    previous_predictions=get_recent_predictions(user_id="marv", limit=3)
)
```

## Repository Pattern

### `PortfolioRepository`

```python
from typing import Optional, List
from datetime import date

class PortfolioRepository:
    def save(self, portfolio: Portfolio) -> str:
        """포트폴리오 저장, portfolio_id 반환"""
        pass

    def get_by_id(self, portfolio_id: str) -> Optional[Portfolio]:
        """ID로 조회"""
        pass

    def get_latest(self, user_id: str, portfolio_type: str = "current") -> Optional[Portfolio]:
        """최신 포트폴리오 조회"""
        pass

    def get_history(self, user_id: str, limit: int = 10) -> List[Portfolio]:
        """포트폴리오 히스토리"""
        pass
```

### `PredictionRepository`

```python
class PredictionRepository:
    def save(self, prediction: Prediction) -> str:
        """예측 저장"""
        pass

    def get_by_id(self, prediction_id: str) -> Optional[Prediction]:
        pass

    def get_latest(self, user_id: str) -> Optional[Prediction]:
        """최신 예측 조회 (성과 분석용)"""
        pass

    def get_pending_analysis(self, user_id: str) -> List[Prediction]:
        """성과 분석 대기 중인 예측 (result가 없는 것)"""
        pass
```

### `PerformanceRepository`

```python
class PerformanceRepository:
    def save(self, result: PerformanceResult) -> str:
        pass

    def get_by_prediction(self, prediction_id: str) -> Optional[PerformanceResult]:
        pass

    def get_agent_stats(self, user_id: str, agent_name: str) -> dict:
        """Agent의 누적 통계"""
        pass
```

## File Locations

```
data/
├── mara.db                          # SQLite database
├── portfolios/
│   └── marv_2025-01-17_current.json
└── predictions/
    └── marv_2025-01-17_prediction.json

outputs/
├── reports/
│   └── 2025-01-17_growth_report.md
├── portfolios/
│   └── 2025-01-17_growth_recommendation.json
└── logs/
    └── 2025-01-17_growth_execution.log
```

## Migration Scripts

```bash
# 초기 DB 생성
python -m src.db.migrations.001_initial_schema

# Agent 성과 테이블 추가
python -m src.db.migrations.002_add_agent_performance
```

## Next Steps

1. ✅ DB 스키마 설계 완료
2. 🔄 Repository 클래스 구현
3. 🔄 Migration scripts 작성
4. 🔄 CLI에 retrospection 명령 추가
