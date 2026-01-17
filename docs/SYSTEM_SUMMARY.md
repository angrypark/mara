# MARA System Summary

## 완성된 설계 개요

MARA (Macro Asset Rebalance Agent)는 유저별로 다양한 관점의 Agent를 통해 포트폴리오 분석을 수행하고, 각 Agent의 성과를 평가하며, 시각화하는 시스템입니다.

---

## 1. 유저별 분석 결과 저장 방식

### Database Schema

**3개의 핵심 테이블**:

1. **`agent_predictions`** - Agent별 개별 예측
   - 각 Layer에서 실행된 모든 Agent의 분석 결과 저장
   - Layer: macro, research, strategy, rebalancing
   - Agent 정보: name, persona, weight
   - 예측 데이터: market_regime, sector_outlook, recommended_allocation 등

2. **`agent_evaluations`** - Agent별 성과 평가
   - 실제 성과와 예측 비교
   - Layer별 평가 지표:
     - Macro: regime_accuracy, sector_prediction_error
     - Strategy: return_prediction_error, allocation_similarity
     - Research: opportunity_hit_rate, theme_performance
   - 종합 평가: overall_contribution, rationale, learning_points

3. **`agent_personas`** - Agent Persona 정의
   - Ray Dalio, Warren Buffett 등 투자 철학별 Persona
   - 적용 가능한 Layer, 기본 가중치, 민감도
   - Config 파일 및 System Prompt 파일 경로

### Data Flow

```
Prediction 실행
│
├─► predictions 테이블 (전체 예측)
│
├─► agent_predictions 테이블 (Agent별 예측)
│   ├─ Geopolitical Agent → market_regime: "moderate_risk"
│   ├─ Sector Rotation Agent → sector_outlook: {"technology": 0.18}
│   ├─ Ray Dalio Macro Agent → regime: "growth_moderate_inflation"
│   └─ Monetary Agent → policy: "easing_cycle"
│
└─► outputs/data/marv_2025-01-17_full.json (JSON 파일)

---

1개월 후 Retrospection 실행
│
├─► performance_results 테이블 (전체 성과)
│
├─► agent_evaluations 테이블 (Agent별 평가)
│   ├─ Geopolitical Agent → accuracy: 0.45, contribution: -0.02
│   ├─ Sector Rotation Agent → accuracy: 0.85, contribution: +0.04
│   ├─ Ray Dalio Macro Agent → accuracy: 0.70, contribution: +0.01
│   └─ Monetary Agent → accuracy: 0.88, contribution: +0.02
│
├─► agent_performance 테이블 (누적 통계)
│   └─ Geopolitical Agent 가중치: 0.20 → 0.15 (하향 조정 제안)
│
└─► outputs/data/marv_2025-01-17_evaluation.json (평가 JSON)
```

---

## 2. Agent 추가 및 정리 방식

### Persona-Based Agent System

**컨셉**: 각 Agent는 특정 투자 철학(Persona)을 가짐

**예시 Persona**:
- `ray_dalio`: 레이 달리오의 All Weather 전략
- `warren_buffett`: 워렌 버핏의 가치투자
- `sector_rotation`: 섹터 로테이션 전문
- `geopolitical`: CIA 지정학 분석가
- `monetary`: 중앙은행 정책 전문가

### Agent 추가 방법

#### 1단계: Persona Config 작성

`src/config/personas/ray_dalio_macro.yaml`:

```yaml
persona_name: ray_dalio
display_name: "Ray Dalio All Weather Strategy"

investment_philosophy: |
  - 4대 경제 레짐 (Growth/Recession × Inflation/Deflation)
  - 리스크 패리티
  - 부채 사이클 분석

applicable_layers:
  - macro
  - strategy

layer_configs:
  macro:
    output_format:
      regime: ["growth_inflation", "growth_deflation", ...]
      asset_class_outlook: {...}

  strategy:
    target_allocations:
      growth_inflation:
        equities: 0.30
        bonds: 0.15
        gold: 0.10
        ...
```

#### 2단계: System Prompt 작성

`src/agents/personas/RAY_DALIO_MACRO.md`:

```markdown
# Ray Dalio Macro Agent - System Prompt

You are a macro economic analyst trained in Ray Dalio's principles...

## Analysis Framework
1. Classify current economic regime (4 quadrants)
2. Analyze debt cycle position
3. Evaluate central bank policy
4. Recommend asset class allocation

## Output Format
{
  "regime": "growth_inflation",
  "asset_class_outlook": {...}
}
```

#### 3단계: Flow Config에 추가

`src/config/flows/growth.yaml`:

```yaml
layers:
  macro:
    agents:
      - name: ray_dalio_macro_agent
        persona: ray_dalio      # ← Persona 연결
        weight: 0.30
        enabled: true
```

#### 4단계: Database에 등록

```sql
INSERT INTO agent_personas VALUES
('ray_dalio', 'ray_dalio', 'Ray Dalio All Weather',
 'All Weather 포트폴리오 전략', '["macro", "strategy"]',
 0.30, 'conservative', 1);
```

### Agent 정리 방식

**디렉토리 구조**:

```
src/
├── config/
│   ├── personas/
│   │   ├── ray_dalio_macro.yaml
│   │   ├── warren_buffett_value.yaml
│   │   ├── geopolitical.yaml
│   │   └── sector_rotation.yaml
│   └── flows/
│       ├── growth.yaml  (어떤 persona를 쓸지 정의)
│       └── income.yaml
│
└── agents/
    ├── personas/
    │   ├── RAY_DALIO_MACRO.md  (System Prompt)
    │   ├── WARREN_BUFFETT_VALUE.md
    │   └── ...
    └── macro/
        └── macro_agent.py  (공통 실행 로직)
```

**핵심 원칙**:
1. Persona는 투자 철학 (What to analyze, How to analyze)
2. Flow는 Persona 조합 (Which personas to use, with what weights)
3. Agent 구현은 공통 (Load persona → Execute analysis)

---

## 3. 과거 시점 분석 결과의 Agent별 평가

### Evaluation Trigger System

**3가지 Trigger**:

1. **Scheduled Trigger** (매월 15일)
```python
if today.day == 15:
    pending = db.get_pending_evaluations()
    for prediction in pending:
        run_retrospection(prediction.id)
```

2. **On Rebalance Trigger** (리밸런싱 시)
```python
if new_rebalance_occurred(user_id):
    latest_prediction = db.get_latest_prediction(user_id)
    if not latest_prediction.has_evaluation():
        run_retrospection(latest_prediction.id)
```

3. **Manual Trigger** (CLI 명령)
```bash
mara retrospect --user marv --date 2025-01-17
```

### Agent별 평가 프로세스

```python
# 1. 이전 Prediction 조회
prediction = get_prediction("marv_2025-01-17")
agent_predictions = get_agent_predictions(prediction.id)

# 2. 실제 성과 계산
actual = calculate_actual_performance(
    start_date="2025-01-17",
    end_date="2025-02-17"
)

# 3. 각 Agent 평가
for agent_pred in agent_predictions:
    if agent_pred.layer == "macro":
        evaluation = evaluate_macro_agent(
            predicted_regime=agent_pred.market_regime,
            actual_regime=actual.market_regime,
            predicted_sectors=agent_pred.sector_outlook,
            actual_sectors=actual.sector_performance
        )
        # evaluation = {
        #     "regime_accuracy": 0.85,
        #     "sector_prediction_error": {...},
        #     "overall_accuracy": 0.82,
        #     "contribution": +0.03
        # }

    elif agent_pred.layer == "strategy":
        evaluation = evaluate_strategy_agent(
            expected_return=agent_pred.expected_return,
            actual_return=actual.actual_return,
            expected_allocation=agent_pred.recommended_allocation,
            actual_allocation=actual.final_allocation
        )

    # 4. 평가 저장
    save_agent_evaluation(
        agent_prediction_id=agent_pred.id,
        evaluation=evaluation,
        rationale="...",
        learning_points=[...]
    )

# 5. Agent 가중치 업데이트 제안
recommendations = calculate_weight_adjustments(
    user_id="marv",
    recent_evaluations=get_recent_evaluations(months=6)
)
# recommendations = [
#     {"agent": "geopolitical_agent", "weight": 0.20 → 0.15},
#     {"agent": "sector_rotation_agent", "weight": 0.40 → 0.45}
# ]
```

### 평가 지표

**Macro Layer**:
- `regime_accuracy`: 시장 레짐 예측 정확도
- `sector_prediction_error`: 섹터별 예측 오차
- `overall_contribution`: 전체 성과 기여도

**Strategy Layer**:
- `return_prediction_error`: 수익률 예측 오차
- `allocation_similarity`: 제안 배분 vs 실제 배분 유사도
- `sharpe_accuracy`: Sharpe Ratio 예측 정확도

**Research Layer**:
- `opportunity_hit_rate`: 추천 종목 적중률
- `theme_performance`: 테마별 실제 성과

**Rebalancing Layer**:
- `action_effectiveness`: 리밸런싱 액션 효과
- `timing_score`: 타이밍 적절성

---

## 4. 시각화

### Timeline View

**위치**: `outputs/visualizations/marv_timeline.html`

**구조**:
```
📊 MARA Portfolio Timeline
├─ Overall Stats
│  ├─ Total Predictions: 3
│  ├─ Evaluations Complete: 2
│  ├─ Avg Accuracy: 71%
│  └─ Total Return: +18.5%
│
└─ Timeline (최근 → 과거)
   ├─ 2025-01-17 (✓ Evaluated)
   │  ├─ Expected Return: 12.0%
   │  ├─ Actual Return: 8.0% (67% accuracy)
   │  ├─ Agent Performance
   │  │  ├─ Monetary Agent: 88% (Top)
   │  │  ├─ Sector Rotation: 85%
   │  │  └─ Geopolitical: 45% (Needs Improvement)
   │  ├─ Selected Strategy: Balanced Growth
   │  ├─ Key Insights
   │  └─ [View Detailed Analysis →]
   │
   ├─ 2024-12-15 (✓ Evaluated)
   └─ 2024-11-15 (✓ Evaluated)
```

### Detail View

**위치**: `outputs/visualizations/marv_2025-01-17_detail.html`

**구조**:
```
📊 MARA Analysis Report - 2025-01-17
├─ Summary Cards
│  ├─ Expected Return: +12.0%
│  ├─ Actual Return: +8.0%
│  ├─ Prediction Accuracy: 67%
│  └─ Portfolio Value: ₩100M → ₩108M
│
├─ Flow Diagram
│  Portfolio → Data → Macro → Research → Strategy → Rebalancing → Validation → Critic
│
├─ [Prediction Results Tab]
│  ├─ 🌍 Macro Analysis (4 Agents)
│  │  ├─ Geopolitical Agent
│  │  │  ├─ Prediction: Moderate Risk, Tech -5%
│  │  │  └─ Evaluation: 45% accuracy, -2% contribution
│  │  │     └─ Learning: 지정학 리스크 과대평가
│  │  │
│  │  ├─ Sector Rotation Agent
│  │  │  ├─ Prediction: Bull Market, Tech +18%
│  │  │  └─ Evaluation: 85% accuracy, +4% contribution
│  │  │     └─ Learning: AI 테마 정확히 포착
│  │  │
│  │  ├─ Ray Dalio Macro Agent
│  │  │  ├─ Prediction: Growth + Moderate Inflation
│  │  │  ├─ Risk Parity: Equities 40%, Bonds 30%, Gold 15%
│  │  │  └─ Evaluation: 70% accuracy, +1% contribution
│  │  │
│  │  └─ Monetary Agent
│  │     ├─ Prediction: Easing Cycle, Tech +12%
│  │     └─ Evaluation: 88% accuracy, +2% contribution
│  │
│  ├─ 🔍 Research Layer
│  │  ├─ Theme Investment (AI, Semiconductor)
│  │  └─ Warren Buffett Screener (AAPL, V)
│  │
│  ├─ 🎯 Strategy Layer (3 Candidates)
│  │  ├─ Aggressive Growth (Expected: 15%, Sharpe: 0.60)
│  │  ├─ Balanced Growth (Selected) ✓
│  │  └─ Defensive Growth (Expected: 9%, Sharpe: 0.64)
│  │
│  └─ ⚖️ Rebalancing Layer
│     ├─ Cash Flow Based (Preferred)
│     └─ Threshold Based
│
└─ [Performance Evaluation Tab]
   ├─ Agent Performance Summary
   │  ├─ Top Performer: Monetary (88%)
   │  ├─ Needs Improvement: Geopolitical (45%)
   │  └─ Avg Accuracy: 72%
   │
   ├─ Weight Adjustments
   │  ├─ Geopolitical: 20% → 15% (-5%)
   │  └─ Sector Rotation: 40% → 45% (+5%)
   │
   └─ Key Insights
      ├─ ✅ AI 및 반도체 테마 강세 정확히 포착
      ├─ ⚠️ 지정학 리스크 과대평가
      ├─ 💡 금 배분은 리스크 헤지 역할
      └─ 📈 현금흐름 기반 리밸런싱은 세금 효율적
```

### 시각화 특징

1. **리밸런싱 시점별 저장**:
   - 각 예측 시점마다 HTML 파일 생성
   - `marv_2025-01-17_detail.html`
   - `marv_2024-12-15_detail.html`

2. **전체 Flow 표시**:
   - 8개 Layer 실행 순서 다이어그램
   - Layer별 Agent 목록 및 가중치

3. **Agent별 결과 요약**:
   - Prediction 시점: Agent의 분석 결과
   - Evaluation 시점: 정확도, 기여도, 학습 포인트

4. **평가 결과 표시**:
   - Accuracy Badge (High: 85%+, Medium: 60-85%, Low: <60%)
   - Contribution (긍정/부정 기여도)
   - Learning Points (💡 아이콘)
   - Weight Adjustment Recommendations

---

## 핵심 설계 원칙

### 1. Agent-Level Granularity
모든 Agent의 개별 의견을 저장하고 평가합니다.

### 2. Persona-Based Flexibility
다양한 투자 철학을 Persona로 추가할 수 있습니다.

### 3. Retrospective Learning
과거 예측을 평가하고, Agent 가중치를 자동 조정합니다.

### 4. Visual Transparency
전체 분석 과정과 평가 결과를 시각적으로 표현합니다.

---

## 구현 상태

✅ **완료**:
- Database Schema (agent_predictions, agent_evaluations, agent_personas)
- Persona Config 시스템 (ray_dalio, warren_buffett)
- Sample Output Data (full.json, evaluation.json)
- Visualization (Timeline, Detail View)
- Documentation (AGENT_TRACKING.md, VISUALIZATION_GUIDE.md)

🔄 **다음 단계**:
- Repository 클래스 구현
- Agent 실행 로직 구현
- Retrospection Agent 구현
- Migration Scripts
- CLI 명령 추가
