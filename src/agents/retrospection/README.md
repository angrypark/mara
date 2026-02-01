# Retrospection Layer

시간 경과 후 예측 vs 실제 성과를 비교하고, Agent 가중치 조정을 제안하는 레이어입니다.

## 책임 (Responsibilities)

- 예측 vs 실제 성과 비교
- 어떤 논리가 맞았고 틀렸는지 분석
- Agent별 성과 기여도 분석
- Agent 가중치 조정 제안 → 다음 사이클에 반영

## 구조

```
retrospection/
└── evaluator.py         # 예측 vs 실제 비교, 가중치 조정 제안
```

## Output Schema

### RetrospectionState

```python
class RetrospectionState:
    """Retrospection Layer 출력"""
    period: str                       # 분석 기간
    predicted_vs_actual: dict         # 예측 vs 실제 비교
    agent_performance: dict           # Agent별 성과
    learning_insights: list[str]      # 학습 인사이트
    weight_adjustments: list[dict]    # Agent 가중치 조정 제안
    timestamp: datetime
```

## 분석 프로세스

### 1. 예측 vs 실제 비교

```python
{
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
    }
}
```

### 2. Agent별 성과 분석

```python
{
    "ray_dalio_macro": {
        "predictions_made": 12,
        "accuracy": 0.75,
        "impact_on_return": 0.02,
        "grade": "B+"
    },
    "sector_rotation": {
        "predictions_made": 24,
        "accuracy": 0.62,
        "impact_on_return": -0.01,
        "grade": "C+"
    }
}
```

### 3. 가중치 조정 제안

```python
{
    "adjustments": [
        {
            "agent_id": "sector_rotation",
            "current_weight": 0.40,
            "recommended_weight": 0.35,
            "reason": "에너지 섹터 지속적 과대평가"
        },
        {
            "agent_id": "ray_dalio_macro",
            "current_weight": 0.30,
            "recommended_weight": 0.35,
            "reason": "매크로 환경 예측 정확"
        }
    ]
}
```

## 회고 주기

| 주기 | 실행 시점 | 목적 |
|------|-----------|------|
| **월별** | 매월 15일 | 지난 1개월 성과 분석 |
| **분기별** | 매 분기 말 | 3개월 트렌드 분석, 장기 패턴 인식 |
| **연간** | 연말 | 종합 리뷰, Agent 페르소나 재설계 검토 |

## CLI 실행

```bash
# 월간 회고 실행
python -m src.orchestration.cli retrospect --prediction-id 2025-01-15-growth
```

## Database 연동

Retrospection Layer는 다음 테이블을 사용합니다:

| 테이블 | 용도 |
|--------|------|
| `agent_predictions` | 개별 Agent 분석 결과 저장 |
| `agent_evaluations` | 예측 vs 실제 성과 비교 결과 |
| `agent_personas` | 페르소나 정의 및 기본 가중치 |

## 피드백 루프

Retrospection의 결과는 다음 사이클에 반영됩니다:

```
┌─────────────────┐         ┌─────────────────┐
│  Retrospection  │         │ Perspective     │
│     Layer       │         │    Agents       │
└────────┬────────┘         └────────┬────────┘
         │                           │
         │  Agent 가중치 조정 제안   │
         │──────────────────────────▶│
         │                           │
         │  다음 사이클에 반영       │
         │                           │
         ▼                           ▼
```

## 메타 학습 (Meta-Learning)

장기적으로 다음을 학습합니다:

1. **시장 국면별 Agent 성과**
   - Bull Market에서 어떤 Agent가 강한지
   - Bear Market에서 어떤 Agent가 정확한지

2. **계절성 패턴**
   - 특정 시기에 특정 Agent가 더 정확

3. **외부 이벤트 영향**
   - 선거, 전쟁 등 예외 상황 대응 능력

## 구현 가이드라인

1. **데이터 저장**
   - 모든 예측과 결과를 SQLite에 저장
   - 쉽게 쿼리 가능한 구조

2. **시각화**
   - 예측 vs 실제 차트
   - Agent별 성과 대시보드
   - 누적 학습 곡선

3. **자동 피드백 루프**
   - Feedback을 다음 사이클에 자동 반영
   - 사람 승인 후 적용 (선택적)

4. **학습 인사이트 기록**
   - 일관되게 틀리는 패턴 기록
   - 개선 방향 문서화
