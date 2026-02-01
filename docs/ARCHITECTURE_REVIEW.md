# MARA Architecture Review

**Reviewer**: L6 Software Engineer Perspective
**Date**: 2025-02-01
**Status**: Review Complete

---

## Executive Summary

현재 MARA 시스템의 Agent 구조를 검토한 결과, **각 Agent가 독립적으로 명확한 목표를 수행할 수 있는 구조로 잘 설계**되어 있습니다. 다만, 몇 가지 개선점을 제안합니다.

### Overall Assessment: ✅ APPROVED with Minor Recommendations

---

## 1. Agent Independence Analysis

### 1.1 현재 Agent 구조

```
┌─────────────────────────────────────────────────────────────────────┐
│                           MARA Agent System                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │                    Perspective Agents                         │     │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │     │
│  │  │Geopoliti-│ │ Sector   │ │ Monetary │ │Ray Dalio │        │     │
│  │  │   cal    │ │ Rotation │ │          │ │  Macro   │        │     │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘        │     │
│  │       │            │            │            │               │     │
│  │       └────────────┴─────┬──────┴────────────┘               │     │
│  │                          │                                    │     │
│  │                    ┌─────▼─────┐                             │     │
│  │                    │ Research  │ (Multi-hop support)          │     │
│  │                    │   Agent   │                              │     │
│  │                    └───────────┘                             │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                               │                                       │
│                               ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │                    Strategy Aggregator                        │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                               │                                       │
│                               ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │                       Validator                               │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                               │                                       │
│                               ▼                                       │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │                       Evaluator                               │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 Agent별 독립성 평가

| Agent | Mission 명확성 | Input 명세 | Output 명세 | 독립 실행 가능 | 평가 |
|-------|---------------|-----------|------------|--------------|------|
| Geopolitical Agent | ✅ | ✅ | ✅ | ✅ | **A** |
| Sector Rotation Agent | ✅ | ✅ | ✅ | ✅ | **A** |
| Monetary Agent | ✅ | ✅ | ✅ | ✅ | **A** |
| Ray Dalio Macro Agent | ✅ | ✅ | ✅ | ✅ | **A** |
| Research Agent | ✅ | ✅ | ✅ | ✅ | **A** |
| Strategy Aggregator | ✅ | ✅ | ✅ | ⚠️ | **B+** |
| Validator | ✅ | ✅ | ✅ | ⚠️ | **B+** |
| Evaluator | ✅ | ✅ | ✅ | ⚠️ | **B+** |

**⚠️ 주의**: Strategy Aggregator, Validator, Evaluator는 상위 Agent의 Output에 의존하므로 완전 독립은 아님. 그러나 **Input 명세가 명확하여 Mock 데이터로 독립 테스트 가능**.

---

## 2. AGENT.md 품질 평가

### 2.1 필수 섹션 체크리스트

| 섹션 | 목적 | 현재 상태 |
|------|------|----------|
| **Mission** | 한 문장 목표 정의 | ✅ 모든 Agent에 존재 |
| **Identity** | Agent 페르소나 정의 | ✅ 모든 Agent에 존재 |
| **Input** | 입력 데이터 스키마 | ✅ Python dict 형태로 명세 |
| **Output** | 출력 데이터 스키마 | ✅ Python dict 형태로 명세 |
| **Framework** | 분석 절차 정의 | ✅ Step-by-step 정의 |
| **Rules** | 제약조건 및 가이드라인 | ✅ 모든 Agent에 존재 |
| **Example** | 실제 예시 | ✅ JSON 형태로 제공 |

### 2.2 Contract 명확성

**강점**:
- 모든 Agent의 Input/Output이 **Python dict/Pydantic 스키마**로 명확히 정의됨
- 필드별 타입과 의미가 주석으로 설명됨
- 실제 JSON 예시로 이해도 향상

**개선 필요**:
- 일부 Optional 필드 명시 부족
- Error case Output 정의 필요

---

## 3. 시스템 아키텍처 평가

### 3.1 장점

#### 3.1.1 Separation of Concerns (관심사 분리) ✅

```
Data Collection → Analysis → Aggregation → Validation → Learning
     (Data)        (Perspective)  (Strategy)   (Validation) (Retrospection)
```

각 Layer가 명확한 책임을 가짐:
- **Data Layer**: 데이터 수집만
- **Perspective Agents**: 분석만
- **Strategy Aggregator**: 종합만
- **Validator**: 검증만
- **Evaluator**: 학습만

#### 3.1.2 Loose Coupling (느슨한 결합) ✅

Agent 간 통신이 **표준화된 JSON 인터페이스**로 이루어짐:
```python
# 모든 Perspective Agent는 동일한 Output 형식
{
    "agent_id": str,
    "market_outlook": "BULLISH" | "NEUTRAL" | "BEARISH",
    "proposals": list[dict],
    ...
}
```

새 Perspective Agent 추가 시 기존 코드 수정 불필요.

#### 3.1.3 Extensibility (확장성) ✅

새 Agent 추가 프로세스가 명확함:
1. `src/config/personas/`에 YAML 생성
2. `src/agents/perspective/`에 AGENT.md 추가
3. `src/config/flows/`에 가중치 설정

#### 3.1.4 Testability (테스트 용이성) ✅

각 Agent가 독립적으로 테스트 가능:
```python
# Unit Test 예시
def test_geopolitical_agent():
    mock_input = {"data_insights": {...}, "current_portfolio": {...}}
    output = GeopoliticalAgent().analyze(mock_input)
    assert "market_outlook" in output
    assert output["market_outlook"] in ["BULLISH", "NEUTRAL", "BEARISH"]
```

### 3.2 개선 필요 사항

#### 3.2.1 Error Handling Contract 부재 ⚠️

**현재 상태**: AGENT.md에 성공 케이스만 정의됨

**권장 추가**:
```python
# Error Output Schema
{
    "status": "error",
    "error_code": str,           # "DATA_FETCH_FAILED", "LLM_TIMEOUT", etc.
    "error_message": str,
    "fallback_used": bool,
    "partial_output": dict | None
}
```

#### 3.2.2 Versioning 부재 ⚠️

**현재 상태**: AGENT.md 버전 관리 없음

**권장 추가**:
```yaml
# 각 AGENT.md 상단에 추가
version: "1.0.0"
last_updated: "2025-02-01"
compatible_with:
  - orchestration: ">=1.0.0"
  - strategy_aggregator: ">=1.0.0"
```

#### 3.2.3 Rate Limiting Contract ⚠️

**현재 상태**: Research Agent의 API 호출 제한 명세 부족

**권장 추가**:
```python
# RESEARCH_AGENT.md에 추가
rate_limits:
  max_queries_per_minute: 10
  max_tokens_per_query: 4000
  cooldown_on_429: 60  # seconds
```

---

## 4. 의존성 분석

### 4.1 의존성 그래프

```
DataState ─────────────────────────────────────────────────┐
     │                                                      │
     ▼                                                      │
┌────────────┐     ┌────────────┐     ┌────────────┐       │
│Geopolitical│     │  Sector    │     │  Monetary  │       │
│   Agent    │     │ Rotation   │     │   Agent    │       │
└─────┬──────┘     └─────┬──────┘     └─────┬──────┘       │
      │                  │                  │               │
      │        ┌─────────┴─────────┐       │               │
      │        │  Research Agent   │       │               │
      │        └─────────┬─────────┘       │               │
      │                  │                  │               │
      └─────────┬────────┴────────┬────────┘               │
                │                  │                        │
                ▼                  ▼                        │
        PerspectiveState   PerspectiveState                │
                │                  │                        │
                └────────┬─────────┘                       │
                         │                                  │
                         ▼                                  │
              ┌─────────────────────┐                      │
              │ Strategy Aggregator │                      │
              └──────────┬──────────┘                      │
                         │                                  │
                         ▼                                  │
                  StrategyState                            │
                         │                                  │
                         ▼                                  │
              ┌─────────────────────┐                      │
              │     Validator       │◄─────────────────────┘
              └──────────┬──────────┘     (Backtest uses historical data)
                         │
                         ▼
               ValidationState
                         │
                         ▼
              ┌─────────────────────┐
              │     Evaluator       │
              └─────────────────────┘
```

### 4.2 순환 의존성 검사

**결과**: ✅ 순환 의존성 없음

모든 의존성이 단방향(위 → 아래)으로 흐름.

---

## 5. 권장 사항

### 5.1 필수 개선 (P0)

| 항목 | 설명 | 예상 작업량 |
|------|------|------------|
| Error Schema 정의 | 각 AGENT.md에 에러 출력 형식 추가 | 2h |
| Timeout 명세 | 각 Agent의 최대 실행 시간 정의 | 1h |

### 5.2 권장 개선 (P1)

| 항목 | 설명 | 예상 작업량 |
|------|------|------------|
| AGENT.md 버전 관리 | 버전 + 호환성 정보 추가 | 1h |
| Validation Layer에 Stress Test 명세 | 스트레스 테스트 시나리오 표준화 | 2h |
| Research Agent Rate Limiting | API 호출 제한 명세 | 1h |

### 5.3 선택 개선 (P2)

| 항목 | 설명 | 예상 작업량 |
|------|------|------------|
| Warren Buffett Value Agent 추가 | personas YAML 존재, AGENT.md 필요 | 2h |
| Agent Performance Dashboard | 실시간 성과 모니터링 | 1d |

---

## 6. 결론

### 6.1 아키텍처 적합성

현재 MARA 시스템은 **Agent 기반 아키텍처의 핵심 원칙을 잘 준수**하고 있습니다:

1. ✅ **Single Responsibility**: 각 Agent가 하나의 명확한 목표
2. ✅ **Interface Segregation**: Input/Output 스키마로 명확한 계약
3. ✅ **Dependency Inversion**: Agent 간 직접 의존 없이 State를 통해 통신
4. ✅ **Open/Closed**: 새 Agent 추가 시 기존 코드 수정 불필요

### 6.2 독립 실행 가능성

**Yes** - 각 Agent는 AGENT.md에 정의된 Input을 제공받으면 독립적으로 실행 가능:

```python
# 독립 실행 예시
from mara.agents.perspective import GeopoliticalAgent

agent = GeopoliticalAgent()
mock_input = load_mock_data("geopolitical_input.json")
output = await agent.analyze(mock_input)
validate_output(output, GeopoliticalOutputSchema)
```

### 6.3 최종 평가

| 평가 항목 | 점수 | 코멘트 |
|----------|------|--------|
| Agent 독립성 | 9/10 | 명확한 계약으로 독립 테스트 가능 |
| 확장성 | 9/10 | 새 Agent 추가 프로세스 명확 |
| 유지보수성 | 8/10 | 에러 처리 명세 보완 필요 |
| 테스트 용이성 | 9/10 | Mock 데이터로 단위 테스트 가능 |
| 문서화 | 9/10 | AGENT.md 품질 우수 |

**Overall: 8.8/10** - Production Ready with Minor Improvements

---

## Appendix: AGENT.md 파일 목록

```
src/agents/
├── perspective/
│   ├── README.md                   # Layer 설명
│   ├── geopolitical/
│   │   └── AGENT.md               # 지정학 분석
│   ├── sector_rotation/
│   │   └── AGENT.md               # 섹터 로테이션
│   ├── monetary/
│   │   └── AGENT.md               # 통화정책 분석
│   └── ray_dalio_macro/
│       └── AGENT.md               # All Weather 전략
├── research/
│   ├── AGENT.md                   # 심층 조사
│   └── README.md                   # Layer 설명
├── strategy/
│   ├── AGENT.md                   # 전략 종합
│   └── README.md                   # Layer 설명
├── validation/
│   ├── AGENT.md                   # 백테스트/검증
│   └── README.md                   # Layer 설명
└── retrospection/
    ├── AGENT.md                   # 성과 평가
    └── README.md                   # Layer 설명
```
