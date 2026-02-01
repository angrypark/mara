# Orchestration Layer

LangGraph를 활용하여 전체 Agent 워크플로우를 관리하는 레이어입니다.

## 책임 (Responsibilities)

- Agent 간 실행 순서 및 데이터 흐름 제어
- State Management (공유 상태 관리)
- 조건부 분기 (Loop 조건에 따라 재실행)
- 에러 핸들링 및 재시도 로직

## 구조

```
orchestration/
├── graph.py             # 메인 그래프 정의
├── nodes.py             # 노드 함수들
└── cli.py               # CLI 엔트리포인트
```

## 6-Layer Pipeline

```
User Profile → Data → Perspective Agents (병렬) → Strategy → Validation → Retrospection
                              ↑                       ↓
                              └──── Research Agent ←──┘
                                   (multi-hop)
```

## State 정의

각 Layer는 공유 State를 읽고 쓰며, 다음 정보를 전달합니다:

| State | 내용 |
|-------|------|
| `UserProfileState` | 포트폴리오, 투자 목표, 리스크 허용도 |
| `DataState` | 시장 데이터 요약, 가격 변동, 핵심 인사이트 |
| `PerspectiveState` | 각 Agent별 평가 및 리밸런싱 제안 |
| `StrategyState` | 종합된 포트폴리오 조정 방향, 최종 비중 |
| `ValidationState` | 백테스팅 결과, 리스크 메트릭, 승인/거부 |
| `RetrospectionState` | 예측 vs 실제, 학습 인사이트, Agent 가중치 조정 |

## Graph 구조

```python
from langgraph.graph import StateGraph, END

# Graph 생성
workflow = StateGraph(PortfolioState)

# Nodes 추가
workflow.add_node("data_collection", collect_data)
workflow.add_node("perspective_analysis", analyze_perspectives)
workflow.add_node("strategy_design", design_strategy)
workflow.add_node("validation", validate_portfolio)
workflow.add_node("retrospection", perform_retrospection)

# Edges 정의
workflow.add_edge("data_collection", "perspective_analysis")
workflow.add_edge("perspective_analysis", "strategy_design")
workflow.add_edge("strategy_design", "validation")

# Conditional Edge (Validation 결과에 따라 분기)
workflow.add_conditional_edges(
    "validation",
    route_validation_result,
    {
        "APPROVED": "retrospection",
        "REVISION_NEEDED": "strategy_design",  # 최대 3회
        "REJECTED": END
    }
)

workflow.add_edge("retrospection", END)
workflow.set_entry_point("data_collection")
```

## Loop 구조

### Perspective ↔ Research Loop (최대 3회)

```python
# Perspective Agent 내부에서 Research Agent 호출
for i in range(3):
    if has_enough_info():
        break
    research_result = await research_agent.query(question)
    update_analysis(research_result)
```

### Strategy ↔ Validation Loop (최대 3회)

```python
def route_validation_result(state: PortfolioState) -> str:
    if state["validation_result"]["is_approved"]:
        return "APPROVED"

    if state["iteration"] >= 3:
        # 부분 승인 또는 거부
        return "APPROVED" if partial_pass else "REJECTED"

    state["iteration"] += 1
    return "REVISION_NEEDED"
```

## CLI 인터페이스

```bash
# 전체 워크플로우 실행
python -m src.orchestration.cli run --profile growth

# Income 프로필로 실행
python -m src.orchestration.cli run --profile income

# 회고 실행
python -m src.orchestration.cli retrospect --prediction-id 2025-01-15-growth

# 백테스팅
python -m src.orchestration.cli backtest --allocation '{"XLK": 0.3, "XLV": 0.2}' --start-date 2015-01-01
```

## 에러 핸들링

### 재시도 정책

| 컴포넌트 | 재시도 횟수 | 백오프 전략 | Timeout |
|----------|-------------|-------------|---------|
| LLM API (Anthropic) | 3회 | Exponential (1s, 2s, 4s) | 60s |
| Market Data (yfinance) | 2회 | Linear (2s, 4s) | 30s |
| Research Agent | 2회 | Linear (1s, 2s) | 20s |

### Fallback 전략

| 장애 상황 | Fallback 동작 |
|-----------|---------------|
| LLM API 장애 | 캐시된 최근 분석 결과 사용 (24시간 이내), 없으면 중단 |
| Market Data 장애 | 캐시된 가격 데이터 사용 (1시간 이내), stale 경고 표시 |
| Research Agent 실패 | Perspective Agent가 자체 분석으로 진행 |
| 개별 Perspective Agent 실패 | 해당 Agent 제외, 나머지로 종합 (최소 2개 필요) |
| Validation Backtest 실패 | 리스크 메트릭만으로 검증 진행 |

## 병렬 실행

Perspective Agents는 병렬로 실행됩니다:

```python
async def analyze_perspectives(state: PortfolioState) -> PortfolioState:
    agents = [
        GeopoliticalAgent(),
        SectorRotationAgent(),
        RayDalioMacroAgent(),
        MonetaryAgent()
    ]

    # 병렬 실행
    tasks = [agent.analyze(state) for agent in agents]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 최소 2개 Agent 성공 필요
    valid_results = [r for r in results if not isinstance(r, Exception)]
    if len(valid_results) < 2:
        raise InsufficientAgentsError("최소 2개 Agent 필요")

    return state
```

## 상태 체크포인트

```python
from langgraph.checkpoint import MemorySaver

# Checkpointer 설정
checkpointer = MemorySaver()
app = graph.compile(checkpointer=checkpointer)

# 중단 후 재개 가능
config = {"configurable": {"thread_id": "portfolio-2025-01-15"}}
result = await app.ainvoke(initial_state, config=config)
```

## 구현 가이드라인

1. **State 불변성**
   - State는 직접 수정하지 않고 새 객체 반환
   - LangGraph 규칙 준수

2. **로깅**
   - 각 노드 실행 전후 로깅
   - 실행 시간 기록

3. **테스트 용이성**
   - 각 노드는 독립적으로 테스트 가능
   - Mock State로 단위 테스트
