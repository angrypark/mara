# Agent-Level Tracking & Visualization

## Overview

각 Layer에서 실행되는 모든 Agent의 개별 분석 결과를 저장하고, 회고 시점에 각 Agent의 성과를 평가하며, 시간에 따른 Agent별 성과를 시각화하는 시스템입니다.

## Design Principles

1. **Agent-Level Granularity**: 모든 Agent의 개별 의견과 예측을 저장
2. **Persona-Based Agents**: Ray Dalio, Warren Buffett 등 다양한 투자 철학을 가진 Agent 추가 가능
3. **Retrospective Evaluation**: 과거 예측에 대한 Agent별 성과 평가
4. **Timeline Visualization**: 리밸런싱 시점별 전체 Flow와 Agent 결과 시각화

## Enhanced Database Schema

### 1. `agent_predictions` - Agent별 개별 예측 저장

```sql
CREATE TABLE agent_predictions (
    agent_prediction_id TEXT PRIMARY KEY,  -- UUID
    prediction_id TEXT NOT NULL,  -- 어느 실행의 일부인지
    user_id TEXT NOT NULL,

    -- Agent 정보
    layer TEXT NOT NULL,  -- 'macro', 'research', 'strategy', 'rebalancing'
    agent_name TEXT NOT NULL,  -- 'sector_rotation_agent', 'ray_dalio_macro_agent'
    agent_persona TEXT,  -- 'sector_rotation', 'ray_dalio', 'warren_buffett'
    agent_weight REAL,  -- 해당 시점의 가중치

    -- 예측 내용 (Layer별로 다름)
    prediction_data JSONB NOT NULL,  -- Agent의 상세 분석 결과

    -- Macro Layer 전용
    market_regime TEXT,
    sector_outlook JSONB,  -- {"technology": {"score": 0.15, "rationale": "..."}}
    confidence_score REAL,

    -- Strategy Layer 전용
    recommended_allocation JSONB,
    expected_return REAL,
    expected_risk REAL,

    -- Research Layer 전용
    opportunities JSONB,  -- [{"ticker": "NVDA", "theme": "ai_infrastructure", "score": 0.85}]

    -- Rebalancing Layer 전용
    suggested_actions JSONB,  -- [{"action": "buy", "ticker": "XLK", "amount": 5000000}]

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (prediction_id) REFERENCES predictions(prediction_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX idx_agent_predictions_prediction ON agent_predictions(prediction_id);
CREATE INDEX idx_agent_predictions_layer_agent ON agent_predictions(layer, agent_name);
```

### 2. `agent_evaluations` - Agent별 성과 평가

```sql
CREATE TABLE agent_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    agent_prediction_id TEXT NOT NULL,
    performance_result_id TEXT NOT NULL,
    user_id TEXT NOT NULL,

    -- Agent 정보
    layer TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    agent_persona TEXT,

    -- 평가 기간
    evaluation_date DATE NOT NULL,
    prediction_date DATE NOT NULL,  -- 예측 시점

    -- Layer별 평가 지표
    accuracy_score REAL,  -- 0.0 to 1.0

    -- Macro Layer 평가
    regime_accuracy REAL,  -- 시장 레짐 예측 정확도
    sector_prediction_error JSONB,  -- 섹터별 예측 오차

    -- Strategy Layer 평가
    return_prediction_error REAL,  -- expected vs actual return
    risk_prediction_error REAL,
    allocation_similarity REAL,  -- 제안 vs 실제 배분 유사도

    -- Research Layer 평가
    opportunity_hit_rate REAL,  -- 추천 종목 중 실제 수익률 좋았던 비율
    theme_performance JSONB,  -- 테마별 실제 성과

    -- Rebalancing Layer 평가
    action_effectiveness REAL,  -- 리밸런싱 액션의 효과
    timing_score REAL,  -- 타이밍 적절성

    -- 종합 평가
    overall_contribution REAL,  -- 전체 포트폴리오 성과에 대한 기여도
    rationale TEXT,  -- 평가 근거

    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (agent_prediction_id) REFERENCES agent_predictions(agent_prediction_id),
    FOREIGN KEY (performance_result_id) REFERENCES performance_results(result_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX idx_agent_evaluations_agent ON agent_evaluations(agent_name, evaluation_date);
```

### 3. `agent_personas` - Agent Persona 정의

```sql
CREATE TABLE agent_personas (
    persona_id TEXT PRIMARY KEY,
    persona_name TEXT UNIQUE NOT NULL,  -- 'ray_dalio', 'warren_buffett', 'sector_rotation'

    -- Persona 정보
    display_name TEXT NOT NULL,  -- 'Ray Dalio Macro', 'Warren Buffett Value'
    description TEXT,
    investment_philosophy TEXT,

    -- 적용 가능한 Layer
    applicable_layers JSONB,  -- ["macro", "strategy"]

    -- Persona 설정
    config_file TEXT,  -- 'src/config/personas/ray_dalio_macro.yaml'
    system_prompt_file TEXT,  -- 'src/agents/personas/RAY_DALIO_MACRO.md'

    -- 기본 파라미터
    default_weight REAL,
    sensitivity TEXT,  -- 'conservative', 'moderate', 'aggressive'

    -- 메타데이터
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);
```

### 4. Update `predictions` table

```sql
-- 기존 predictions 테이블에 컬럼 추가
ALTER TABLE predictions ADD COLUMN flow_execution_id TEXT;
ALTER TABLE predictions ADD COLUMN snapshot_data JSONB;  -- 실행 시점의 전체 상태 스냅샷
```

## Persona-Based Agent System

### Persona Configuration Example

**src/config/personas/ray_dalio_macro.yaml**

```yaml
persona_name: ray_dalio
display_name: "Ray Dalio Macro Strategy"
description: "레이 달리오의 All Weather 전략 기반 거시경제 분석"

investment_philosophy: |
  - 4대 시장 레짐 분석: Growth, Inflation, Deflation, Stagflation
  - 영속적 포트폴리오: 모든 환경에서 견딜 수 있는 자산 배분
  - 리스크 패리티: 자산별 리스크 기여도 균형
  - Debt Cycle 분석: 장기 부채 사이클, 단기 경기 사이클

applicable_layers:
  - macro
  - strategy

layer_configs:
  macro:
    analysis_framework:
      - economic_regime_classification
      - debt_cycle_analysis
      - central_bank_policy
      - geopolitical_risk

    output_format:
      regime: ["growth_inflation", "growth_deflation", "recession_inflation", "recession_deflation"]
      asset_class_outlook:
        - equities
        - bonds
        - gold
        - commodities

    weight_recommendation:
      conservative: 0.25
      moderate: 0.30
      aggressive: 0.20

  strategy:
    principles:
      - risk_parity
      - diversification_across_regimes
      - minimize_correlation

    target_allocations:
      growth_inflation:
        equities: 0.30
        tips: 0.15
        commodities: 0.20
        gold: 0.10
        bonds: 0.15
        cash: 0.10

system_prompt_file: "src/agents/personas/RAY_DALIO_MACRO.md"
```

**src/config/personas/warren_buffett_value.yaml**

```yaml
persona_name: warren_buffett
display_name: "Warren Buffett Value Strategy"
description: "워렌 버핏의 가치투자 원칙 기반 분석"

investment_philosophy: |
  - 내재가치 분석: Intrinsic Value vs Market Price
  - 경제적 해자: Economic Moat (경쟁우위)
  - 우량기업 장기보유: Quality over quantity
  - 안전마진: Margin of Safety

applicable_layers:
  - research
  - strategy

layer_configs:
  research:
    screening_criteria:
      - roe_min: 0.15  # ROE > 15%
      - debt_to_equity_max: 0.50
      - free_cash_flow_positive: true
      - competitive_advantage: true
      - predictable_business: true

    valuation_methods:
      - dcf_analysis
      - pe_ratio_comparison
      - price_to_book

    margin_of_safety: 0.25  # 25% 이상 저평가

  strategy:
    principles:
      - concentrated_portfolio  # 5-10 종목
      - long_term_hold
      - ignore_market_noise

    allocation_style:
      max_positions: 10
      min_position_size: 0.05
      max_position_size: 0.25

system_prompt_file: "src/agents/personas/WARREN_BUFFETT_VALUE.md"
```

### Using Personas in Flow Config

**Updated growth.yaml**

```yaml
layers:
  macro:
    agents:
      - name: geopolitical_agent
        persona: geopolitical  # 기존 스타일
        weight: 0.20

      - name: sector_rotation_agent
        persona: sector_rotation
        weight: 0.30

      - name: ray_dalio_macro_agent
        persona: ray_dalio  # 새로운 Persona 추가
        weight: 0.30

      - name: monetary_agent
        persona: monetary
        weight: 0.20

  research:
    agents:
      - name: theme_investment
        persona: theme_investment
        enabled: true

      - name: warren_buffett_screener
        persona: warren_buffett
        enabled: true
```

## Data Flow

### 1. Prediction 실행 시

```python
# 1. Flow 실행
flow_execution_id = generate_id()
prediction_id = f"marv_2025-01-17"

# 2. Macro Layer 실행
macro_results = []

for agent_config in flow.layers.macro.agents:
    agent = load_agent(
        persona=agent_config.persona,
        layer="macro",
        config=agent_config
    )

    result = agent.analyze(market_data)

    # Agent 개별 예측 저장
    agent_prediction_id = save_agent_prediction(
        prediction_id=prediction_id,
        layer="macro",
        agent_name=agent_config.name,
        agent_persona=agent_config.persona,
        agent_weight=agent_config.weight,
        prediction_data=result,
        market_regime=result.regime,
        sector_outlook=result.sector_outlook,
        confidence_score=result.confidence
    )

    macro_results.append({
        "agent_prediction_id": agent_prediction_id,
        "weight": agent_config.weight,
        "result": result
    })

# 3. Ensemble 수행
ensemble_result = weighted_average(macro_results)

# 4. 최종 Prediction 저장
save_prediction(
    prediction_id=prediction_id,
    flow_execution_id=flow_execution_id,
    market_regime=ensemble_result.regime,
    macro_insights=ensemble_result.insights,
    snapshot_data={
        "macro_agents": [
            {
                "agent_prediction_id": r["agent_prediction_id"],
                "name": r["agent_name"],
                "weight": r["weight"]
            }
            for r in macro_results
        ]
    }
)
```

### 2. Retrospection 실행 시 (Agent 평가)

```python
# 1. 이전 Prediction 조회
previous_prediction = get_prediction("marv_2025-01-17")

# 2. 해당 Prediction의 모든 Agent 예측 조회
agent_predictions = get_agent_predictions(
    prediction_id="marv_2025-01-17"
)

# 3. 실제 성과 계산
actual_performance = calculate_actual_performance(
    start_date="2025-01-17",
    end_date="2025-02-17"
)

# 4. Performance Result 저장
performance_result_id = save_performance_result(
    prediction_id="marv_2025-01-17",
    actual_return=0.06,
    actual_volatility=0.18,
    ...
)

# 5. 각 Agent 평가
for agent_pred in agent_predictions:
    evaluation = evaluate_agent(
        agent_prediction=agent_pred,
        actual_performance=actual_performance
    )

    save_agent_evaluation(
        agent_prediction_id=agent_pred.id,
        performance_result_id=performance_result_id,
        layer=agent_pred.layer,
        agent_name=agent_pred.agent_name,
        accuracy_score=evaluation.accuracy,
        regime_accuracy=evaluation.regime_accuracy,
        sector_prediction_error=evaluation.sector_errors,
        overall_contribution=evaluation.contribution,
        rationale=evaluation.rationale
    )

# 6. Agent 가중치 업데이트 제안
weight_recommendations = calculate_new_weights(
    agent_evaluations=get_agent_evaluations(user_id="marv", recent_months=6)
)
```

## Evaluation Triggers

### Automatic Trigger

```yaml
# src/config/retrospection.yaml

triggers:
  - type: scheduled
    frequency: monthly
    day: 15
    enabled: true

  - type: on_rebalance
    enabled: true
    evaluate_previous_prediction: true

  - type: manual
    cli_command: "mara retrospect --user marv --date 2025-01-17"
```

### Trigger Implementation

```python
# src/orchestration/retrospection_trigger.py

class RetrospectionTrigger:
    def __init__(self, db: Database):
        self.db = db

    def check_scheduled_trigger(self) -> List[str]:
        """매월 15일 체크"""
        today = date.today()
        if today.day == 15:
            # 평가 대기 중인 Prediction 조회
            pending = self.db.get_pending_evaluations()
            return [p.prediction_id for p in pending]
        return []

    def check_rebalance_trigger(self, user_id: str) -> Optional[str]:
        """리밸런싱 발생 시 이전 Prediction 평가"""
        latest_rebalance = self.db.get_latest_rebalance(user_id)
        latest_prediction = self.db.get_latest_prediction(user_id)

        if latest_prediction and not latest_prediction.has_evaluation():
            days_since = (date.today() - latest_prediction.prediction_date).days
            if days_since >= 30:  # 최소 30일 경과
                return latest_prediction.prediction_id
        return None

    def execute_retrospection(self, prediction_id: str):
        """Retrospection 실행"""
        from src.agents.retrospection import RetrospectionAgent

        agent = RetrospectionAgent()
        result = agent.evaluate_prediction(prediction_id)

        # Agent별 평가 저장
        for agent_eval in result.agent_evaluations:
            self.db.save_agent_evaluation(agent_eval)

        # 전체 성과 저장
        self.db.save_performance_result(result.performance_result)
```

## Visualization System

### Output Files Structure

```
outputs/
├── visualizations/
│   ├── marv_timeline.html              # 전체 타임라인 (모든 리밸런싱)
│   ├── marv_2025-01-17_detail.html     # 특정 시점 상세
│   └── marv_agent_performance.html     # Agent 성과 대시보드
├── data/
│   ├── marv_2025-01-17_full.json       # 해당 시점 전체 데이터
│   └── marv_agent_stats.json           # Agent 통계
```

### Visualization Components

1. **Timeline View**: 리밸런싱 시점별 타임라인
2. **Flow View**: 특정 시점의 Layer → Agent 흐름도
3. **Agent Detail**: 각 Agent의 분석 결과 요약
4. **Evaluation View**: 평가 완료 시 성과 표시
5. **Agent Dashboard**: Agent별 누적 성과

## Next Steps

1. ✅ 설계 완료
2. 🔄 Sample output 생성
3. 🔄 Visualization 구현
4. 🔄 DB 마이그레이션 스크립트
