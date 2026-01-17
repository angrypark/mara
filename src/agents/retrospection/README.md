# Retrospection Layer

자가 학습 및 성과 분석을 수행하는 레이어입니다. 매달 지난달의 예측과 실제 결과를 비교하여 시스템을 개선합니다.

## 책임 (Responsibilities)

- 지난달 예측 vs 실제 성과 비교
- Agent별 성과 기여도 분석
- 오류 패턴 파악 및 학습
- 다음 사이클을 위한 피드백 생성

## 주요 모듈

### 1. Prediction Tracker (`prediction_tracker.py`)

**기능**: 매달 예측을 저장하고 추적

**저장 데이터**:
```json
{
  "prediction_id": "2025-01-15-growth",
  "timestamp": "2025-01-15T00:00:00Z",
  "profile": "growth",
  "predictions": {
    "market_regime": "bull",
    "expected_return": 0.08,
    "sector_outlook": {
      "technology": 0.12,
      "healthcare": 0.08,
      "energy": 0.05
    },
    "recommended_allocation": {
      "cash": 0.15,
      "XLK": 0.30,
      "XLV": 0.20
    }
  },
  "agents": {
    "geopolitical": {"regime": "stable", "confidence": 0.75},
    "sector_rotation": {"top_sector": "technology", "confidence": 0.82},
    "monetary": {"policy_stance": "neutral", "confidence": 0.70}
  }
}
```

### 2. Performance Analyzer (`performance_analyzer.py`)

**분석 항목**:

1. **Portfolio 수익률 비교**
   - 예측한 수익률 vs 실제 수익률
   - 오차율 계산

2. **Sector 성과 비교**
   - 각 섹터 예측 vs 실제
   - 가장 정확했던/틀렸던 섹터

3. **Regime 예측 정확도**
   - "Bull Market" 예측이 맞았는지
   - 실제 시장 움직임과 일치도

**출력**:
```json
{
  "period": "2025-01-15 to 2025-02-15",
  "portfolio_return": {
    "predicted": 0.08,
    "actual": 0.06,
    "error": -0.02,
    "error_pct": -25.0
  },
  "sector_accuracy": {
    "technology": {"predicted": 0.12, "actual": 0.10, "error": -0.02},
    "healthcare": {"predicted": 0.08, "actual": 0.11, "error": 0.03},
    "energy": {"predicted": 0.05, "actual": -0.02, "error": -0.07}
  },
  "regime_correct": true
}
```

### 3. Agent Attribution (`agent_attribution.py`)

**Agent별 성과 기여도 분석**:

1. **Macro Agent 정확도**
   - Geopolitical Agent의 지정학 예측 정확도
   - Sector Rotation Agent의 섹터 픽 승률
   - Monetary Agent의 금리 예측 정확도

2. **Strategy Agent 효과성**
   - Growth Agent의 리밸런싱 타이밍
   - Cash Agent의 현금 조절 적중률

**예시**:
```json
{
  "agent_scores": {
    "geopolitical_agent": {
      "predictions_made": 12,
      "accuracy": 0.75,
      "impact_on_return": 0.02,
      "grade": "B+"
    },
    "sector_rotation_agent": {
      "predictions_made": 24,
      "accuracy": 0.62,
      "impact_on_return": -0.01,
      "grade": "C+"
    },
    "cash_agent": {
      "predictions_made": 12,
      "accuracy": 0.83,
      "impact_on_return": 0.03,
      "grade": "A-"
    }
  }
}
```

### 4. Feedback Generator (`feedback_generator.py`)

**학습 및 개선 방향 제시**:

1. **패턴 인식**
   - 일관되게 틀리는 예측 패턴
   - 예: "에너지 섹터를 항상 과대평가"

2. **조정 제안**
   - Agent 가중치 조정
   - 예: "Sector Rotation Agent 신뢰도 0.8 → 0.7로 하향"

3. **새로운 데이터 소스 필요성**
   - 예: "Monetary Agent가 금리 예측에 실패 → 더 많은 Fed 자료 필요"

**출력**:
```json
{
  "insights": [
    "에너지 섹터 예측이 3개월 연속 과대평가 → 보수적 조정 필요",
    "기술주 예측은 일관되게 정확 → 신뢰도 유지"
  ],
  "adjustments": [
    {
      "target": "sector_rotation_agent",
      "parameter": "energy_bias",
      "current": 0.0,
      "recommended": -0.05,
      "reason": "지속적 과대평가"
    },
    {
      "target": "ensemble_weights",
      "parameter": "cash_agent_weight",
      "current": 0.2,
      "recommended": 0.25,
      "reason": "현금 조절 타이밍 우수"
    }
  ],
  "action_items": [
    "Monetary Agent에 더 많은 Fed 회의록 데이터 추가",
    "Geopolitical Agent 페르소나 업데이트 (보수적 → 중립)"
  ]
}
```

## 회고 주기

1. **월별 회고 (Primary)**
   - 매월 15일 실행
   - 지난 1개월 성과 분석

2. **분기별 회고 (Secondary)**
   - 3개월 트렌드 분석
   - 장기 패턴 인식

3. **연간 회고 (Strategic)**
   - 연말 종합 리뷰
   - Agent 페르소나 전면 재설계 검토

## 구현 가이드라인

1. **데이터 저장**
   - 모든 예측과 결과를 SQLite/PostgreSQL에 저장
   - 쉽게 쿼리 가능한 구조

2. **시각화**
   - 예측 vs 실제 차트
   - Agent별 성과 대시보드
   - 누적 학습 곡선

3. **자동 피드백 루프**
   - Feedback을 다음 사이클에 자동 반영
   - 사람 승인 후 적용 (선택적)

4. **A/B Testing**
   - 조정 전후 성과 비교
   - 실험적 변경의 효과 측정

## 출력 스키마

```python
@dataclass
class RetrospectionState:
    period: str
    performance_analysis: PerformanceAnalysis
    agent_attribution: AgentAttribution
    feedback: Feedback
    adjustments_applied: List[Adjustment]
    next_cycle_recommendations: List[str]
    timestamp: datetime
```

## 메타 학습 (Meta-Learning)

장기적으로 다음을 학습:

1. **시장 국면별 Agent 성과**
   - Bull Market에서 어떤 Agent가 강한지
   - Bear Market에서 어떤 Agent가 정확한지

2. **계절성 패턴**
   - 특정 시기에 특정 Agent가 더 정확

3. **외부 이벤트 영향**
   - 선거, 전쟁 등 예외 상황 대응 능력

이를 바탕으로 **Adaptive Weighting** 구현:
```python
def get_agent_weight(agent: str, market_regime: str, month: int) -> float:
    """
    현재 시장 국면과 시기에 따라 Agent 가중치 동적 조정
    """
    base_weight = config.base_weights[agent]
    regime_modifier = meta_learning.regime_modifiers[agent][market_regime]
    seasonal_modifier = meta_learning.seasonal_modifiers[agent][month]

    return base_weight * regime_modifier * seasonal_modifier
```
