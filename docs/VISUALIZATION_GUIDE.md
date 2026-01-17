# Visualization Guide

## Overview

MARA는 각 리밸런싱 시점별로 전체 Flow 실행 결과와 Agent별 분석을 시각화합니다.

## Visualization Types

### 1. Timeline View (`marv_timeline.html`)

**목적**: 전체 리밸런싱 히스토리를 시간순으로 표시

**포함 내용**:
- 전체 통계 (총 예측 수, 평가 완료 수, 평균 정확도, 총 수익률)
- 시점별 카드:
  - 예측일자
  - Expected vs Actual 지표 (Return, Volatility, Max DD)
  - Agent 성과 요약
  - 선택된 전략 및 배분
  - 평가 완료 시 핵심 인사이트

**사용 시나리오**:
- 전체 투자 성과 추이 확인
- 시점별 빠른 비교
- 특정 시점 상세 분석으로 이동

**샘플**: [`/outputs/visualizations/marv_timeline.html`](../outputs/visualizations/marv_timeline.html)

### 2. Detail View (`marv_2025-01-17_detail.html`)

**목적**: 특정 시점의 Layer → Agent 흐름 및 개별 Agent 분석 상세 표시

**포함 내용**:

#### Prediction Results Tab
- **Flow Diagram**: 8개 Layer 실행 순서 시각화
- **Macro Layer**:
  - Ensemble 결과 (시장 레짐, 신뢰도, 섹터 전망)
  - 각 Agent별:
    - 개별 분석 결과 (시장 레짐, 섹터 전망)
    - 가중치 표시
    - Persona 정보
- **Research Layer**:
  - Theme Investment Agent (AI, 반도체 테마별 종목 추천)
  - Warren Buffett Screener (가치주 발굴)
- **Strategy Layer**:
  - 3개 전략 후보 (Aggressive, Balanced, Defensive)
  - 각 전략별 예상 지표 및 배분
  - 선택된 전략 하이라이트
- **Rebalancing Layer**:
  - 제안된 리밸런싱 방법 (Cash Flow, Threshold 기반 등)
  - 권장 방법 및 근거

#### Performance Evaluation Tab (평가 완료 시)
- **Agent Performance Summary**:
  - Top Performer (정확도 88% 등)
  - Needs Improvement
  - 평균 정확도
- **Agent별 평가 상세**:
  - Accuracy Score
  - 예측 vs 실제 비교
  - Contribution (포트폴리오 성과 기여도)
  - 평가 근거 (Rationale)
  - 학습 포인트 (Learning Points)
- **Weight Adjustment 제안**:
  - Agent별 가중치 변경 제안 (+5%, -5% 등)
  - 변경 근거
- **Key Insights**:
  - 성공적인 예측 (✅)
  - 개선 필요한 부분 (⚠️)
  - 학습 사항 (💡)

**사용 시나리오**:
- 특정 시점의 전체 분석 과정 이해
- Agent별 예측 논리 파악
- 평가 결과 기반 학습

**샘플**: [`/outputs/visualizations/marv_2025-01-17_detail.html`](../outputs/visualizations/marv_2025-01-17_detail.html)

### 3. Agent Dashboard (계획 중)

**목적**: Agent별 누적 성과 대시보드

**포함 내용**:
- Agent별 정확도 추이 (시계열)
- Agent별 기여도 분석
- 가중치 변화 히스토리
- Persona별 비교

## Data Files

### 1. Full Prediction Data (`marv_2025-01-17_full.json`)

완전한 예측 실행 결과:
```json
{
  "prediction_id": "marv_2025-01-17",
  "flow": "growth",
  "layers": {
    "macro": {
      "ensemble_result": {...},
      "agents": [
        {
          "agent_prediction_id": "agent_pred_001",
          "agent_name": "geopolitical_agent",
          "agent_persona": "geopolitical",
          "weight": 0.20,
          "analysis": {...}
        }
      ]
    }
  }
}
```

**용도**:
- Visualization 생성 원본 데이터
- 상세 분석 및 디버깅
- API 응답 생성

### 2. Evaluation Data (`marv_2025-01-17_evaluation.json`)

회고 분석 결과:
```json
{
  "evaluation_id": "eval_marv_2025-01-17",
  "actual_performance": {...},
  "agent_evaluations": {
    "macro": [
      {
        "agent_name": "geopolitical_agent",
        "evaluation": {
          "overall_accuracy": 0.45,
          "contribution_to_performance": -0.02,
          "rationale": "...",
          "learning_points": [...]
        }
      }
    ]
  }
}
```

**용도**:
- Performance Evaluation Tab 데이터
- Agent 학습 및 가중치 조정
- 성과 분석

## Visualization Generation Workflow

### 1. Prediction 실행 시

```python
# Flow 실행
result = run_flow(user_id="marv", flow="growth", date="2025-01-17")

# 1. DB에 저장
save_prediction(result)
save_agent_predictions(result.layers)

# 2. JSON 파일 생성
save_json(
    path="outputs/data/marv_2025-01-17_full.json",
    data=result
)

# 3. Visualization 생성
generate_detail_view(
    prediction_id="marv_2025-01-17",
    output="outputs/visualizations/marv_2025-01-17_detail.html"
)

# 4. Timeline 업데이트
update_timeline(
    user_id="marv",
    output="outputs/visualizations/marv_timeline.html"
)
```

### 2. Evaluation 실행 시

```python
# Retrospection 실행
evaluation = run_retrospection(prediction_id="marv_2025-01-17")

# 1. DB에 저장
save_performance_result(evaluation.performance_result)
save_agent_evaluations(evaluation.agent_evaluations)

# 2. JSON 파일 생성
save_json(
    path="outputs/data/marv_2025-01-17_evaluation.json",
    data=evaluation
)

# 3. Detail View 업데이트 (Evaluation Tab 추가)
update_detail_view(
    prediction_id="marv_2025-01-17",
    evaluation=evaluation
)

# 4. Timeline 업데이트
update_timeline(user_id="marv")
```

## Customization

### Color Scheme

```css
/* Primary Colors */
--primary: #667eea;
--secondary: #764ba2;

/* Status Colors */
--success: #48bb78;
--warning: #f56565;
--info: #4299e1;

/* Accuracy Colors */
--high-accuracy: #c6f6d5;   /* 85%+ */
--medium-accuracy: #feebc8; /* 60-85% */
--low-accuracy: #fed7d7;    /* <60% */
```

### Adding New Metrics

Detail View에 새로운 지표 추가:

```html
<div class="metric-box">
    <div class="metric-label">New Metric</div>
    <div class="metric-value">Value</div>
    <div class="metric-comparison">vs Expected</div>
</div>
```

### Adding New Agent Persona

1. Persona Config 생성: `src/config/personas/new_persona.yaml`
2. System Prompt 작성: `src/agents/personas/NEW_PERSONA.md`
3. Flow Config에 추가:
```yaml
agents:
  - name: new_agent
    persona: new_persona
    weight: 0.20
```

## Best Practices

### 1. File Naming Convention

- Timeline: `{user_id}_timeline.html`
- Detail: `{user_id}_{date}_detail.html`
- Data: `{user_id}_{date}_full.json`
- Evaluation: `{user_id}_{date}_evaluation.json`

### 2. Performance

- Detail View는 특정 시점만 로드 (모든 시점 로드 X)
- Timeline은 최근 10개 시점만 표시 (Pagination)
- JSON 파일은 압축 저장 고려 (gzip)

### 3. Accessibility

- Color만으로 정보 전달 X (아이콘, 텍스트 병행)
- 충분한 대비비 (WCAG AA 기준)
- Keyboard navigation 지원

## Future Enhancements

- [ ] Interactive Charts (Chart.js, D3.js)
- [ ] Export to PDF
- [ ] Comparison View (두 시점 비교)
- [ ] Agent Performance Dashboard
- [ ] Mobile-responsive design
- [ ] Dark mode
