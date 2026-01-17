# Critic Layer

최종 검토 및 의사결정을 수행하는 레이어입니다. 모든 이전 Layer의 출력을 종합하여 포트폴리오 승인 여부를 결정합니다.

## 책임 (Responsibilities)

- 논리적 일관성 검증 (Macro Insight ↔ Strategy 정합성)
- Cross-Layer 검증 (각 Layer 출력 간 모순 확인)
- 최종 포트폴리오 승인/거부/수정 요청
- 투자자에게 전달할 최종 리포트 생성

## 주요 모듈

### 1. Logic Consistency Checker (`consistency_checker.py`)

**검증 항목**:

1. **Macro-Strategy 정합성**
   - Macro에서 "경기 침체" 판단했는데 Strategy가 공격적 → 경고
   - Sector Outlook이 "기술주 약세"인데 XLK 비중 증가 → 경고

2. **Strategy-Validation 정합성**
   - Strategy가 제안한 포트폴리오의 백테스팅 결과가 기대치 미달 → 재조정 요청
   - Risk Metrics가 프로필의 Risk Tolerance 초과 → 거부

3. **내부 모순 체크**
   - Cash Agent는 "현금 증가" 권고하는데 Strategy는 "풀 투자" → 조정 필요
   - 여러 Macro Agent 의견이 극단적으로 상충 → 신뢰도 하락

**출력**:
```json
{
  "consistency_score": 0.78,
  "issues": [
    {
      "level": "warning",
      "description": "Macro Agent는 경기 둔화를 예상하지만, Growth Strategy는 여전히 공격적",
      "affected_layers": ["macro", "strategy"]
    }
  ],
  "recommendation": "proceed_with_caution"
}
```

### 2. Cross-Agent Validator (`cross_validator.py`)

**검증 로직**:

- **Macro Layer 내부 검증**:
  - Geopolitical Agent와 Sector Agent 의견 일치도
  - 극단적 의견 차이 시 재분석 요청

- **Strategy Layer 내부 검증**:
  - Growth Agent와 Cash Agent 권고 조화
  - 리밸런싱 액션이 현금 비중 목표와 일치하는지

- **Validation 결과 신뢰도**:
  - 백테스팅 기간 충분한지 (최소 10년)
  - Stress Test 시나리오 다양한지

**출력**:
```json
{
  "macro_agreement": 0.85,
  "strategy_coherence": 0.92,
  "validation_confidence": 0.88,
  "overall_score": 0.88
}
```

### 3. Final Decision Maker (`decision_maker.py`)

**의사결정 프로세스**:

1. **APPROVE (승인)**
   - Consistency Score > 0.8
   - Validation Passed = True
   - No Critical Issues

2. **APPROVE_WITH_WARNINGS (조건부 승인)**
   - Consistency Score > 0.7
   - Minor Warnings 존재
   - Validation Passed = True

3. **REQUEST_REVISION (수정 요청)**
   - Consistency Score < 0.7
   - Validation Failed
   - Major Issues 존재

4. **REJECT (거부)**
   - Critical Issues (예: 프로필 Risk Tolerance 심각하게 초과)
   - Multiple Validation Failures

**출력**:
```json
{
  "decision": "APPROVE_WITH_WARNINGS",
  "confidence": 0.82,
  "rationale": "전반적으로 논리적이나, 경기 둔화 시그널 대비 공격적 배분이 다소 우려됨",
  "action_required": [
    "기술주 비중 5% 감소 권고",
    "현금 비중 15%로 상향 권고"
  ]
}
```

### 4. Report Generator (`report_generator.py`)

**최종 리포트 구성**:

```markdown
# 포트폴리오 리포트 - 2025년 1월

## 1. Executive Summary
- 시장 국면: Mid-Cycle Bull Market
- 추천 포트폴리오: Growth Profile
- 예상 수익률: 8-12% (연환산)
- 최대 예상 낙폭: -25%

## 2. Macro Analysis
- 지정학: 미중 관계 소폭 개선
- 섹터: AI 인프라 투자 지속, 반도체 회복 초입
- 통화정책: Fed 완화 사이클 시작

## 3. Portfolio Recommendation
| Asset Class | Current | Target | Change |
|-------------|---------|--------|--------|
| Cash        | 20%     | 15%    | -5%    |
| Technology  | 25%     | 30%    | +5%    |
| Healthcare  | 15%     | 20%    | +5%    |

## 4. Validation Results
- 백테스팅 수익률: 14.3% (연환산)
- Sharpe Ratio: 0.77
- Max Drawdown: -28.4%
- 벤치마크 대비: +2.3%

## 5. Risk Considerations
- 기술주 집중 리스크 (30%)
- 경기 둔화 시 방어 섹터 부족
- 권고: 6개월 후 재검토

## 6. Action Items
1. XLK (기술 ETF) 5% 매수
2. XLV (헬스케어 ETF) 5% 매수
3. 현금 10M → 5M 감소
```

## 구현 가이드라인

1. **LLM 기반 최종 검토**
   - Claude Opus로 전체 컨텍스트 리뷰
   - "당신은 CFA 자격증을 가진 투자자문가입니다" 페르소나

2. **체크리스트 기반 검증**
   - 모든 검증 항목 자동 체크
   - 누락 항목 없도록 강제

3. **인간 피드백 루프**
   - 최종 리포트를 사용자에게 제시
   - 사용자 승인 후 실행 (선택적)

4. **이력 관리**
   - 모든 의사결정 기록 저장
   - 나중에 Retrospection Layer에서 활용

## 출력 스키마

```python
@dataclass
class CriticState:
    decision: str  # "APPROVE", "APPROVE_WITH_WARNINGS", "REQUEST_REVISION", "REJECT"
    confidence: float
    consistency_score: float
    issues: List[Issue]
    final_portfolio: Portfolio
    report: str  # Markdown 형식
    action_items: List[str]
    timestamp: datetime
```

## 승인 Threshold 설정

```yaml
thresholds:
  approve:
    min_consistency_score: 0.80
    min_validation_confidence: 0.85
    max_critical_issues: 0

  approve_with_warnings:
    min_consistency_score: 0.70
    min_validation_confidence: 0.75
    max_critical_issues: 0
    max_warnings: 3

  reject:
    critical_issues: 1  # 1개 이상이면 무조건 거부
```
