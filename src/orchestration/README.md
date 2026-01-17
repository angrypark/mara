# Orchestration Layer

LangGraph를 활용하여 전체 Agent 워크플로우를 관리하는 레이어입니다.

## 책임 (Responsibilities)

- Agent 간 실행 순서 및 데이터 흐름 제어
- State Management (공유 상태 관리)
- 조건부 분기 (Critic의 결정에 따라 재실행)
- 에러 핸들링 및 재시도 로직

## LangGraph Workflow

### Graph 구조

```python
from langgraph.graph import StateGraph, END

# State 정의
class PortfolioState(TypedDict):
    # Data Layer
    market_data: Dict
    news_data: List[Dict]
    reports: List[Dict]

    # Macro Layer
    macro_insights: Dict
    market_regime: str

    # Strategy Layer
    strategy_output: Dict
    target_portfolio: Dict

    # Validation Layer
    validation_results: Dict
    passed_validation: bool

    # Critic Layer
    critic_decision: str
    final_portfolio: Dict
    report: str

    # Retrospection Layer
    retrospection: Dict

    # Control
    iteration: int
    max_iterations: int

# Graph 생성
workflow = StateGraph(PortfolioState)

# Nodes 추가
workflow.add_node("data_collection", collect_data)
workflow.add_node("macro_analysis", analyze_macro)
workflow.add_node("strategy_design", design_strategy)
workflow.add_node("validation", validate_portfolio)
workflow.add_node("critic_review", review_by_critic)
workflow.add_node("retrospection", perform_retrospection)

# Edges 정의
workflow.add_edge("data_collection", "macro_analysis")
workflow.add_edge("macro_analysis", "strategy_design")
workflow.add_edge("strategy_design", "validation")
workflow.add_edge("validation", "critic_review")

# Conditional Edge (Critic 결정에 따라 분기)
workflow.add_conditional_edges(
    "critic_review",
    route_critic_decision,
    {
        "APPROVE": END,
        "APPROVE_WITH_WARNINGS": END,
        "REQUEST_REVISION": "strategy_design",  # 재조정
        "REJECT": "macro_analysis"  # 처음부터 재분석
    }
)

workflow.set_entry_point("data_collection")
```

### Node 구현 예시

```python
async def collect_data(state: PortfolioState) -> PortfolioState:
    """
    Data Layer 실행
    """
    from src.data.collectors import NewsCollector, PriceCollector

    news_collector = NewsCollector()
    price_collector = PriceCollector()

    state["market_data"] = await price_collector.collect()
    state["news_data"] = await news_collector.collect()

    return state

async def analyze_macro(state: PortfolioState) -> PortfolioState:
    """
    Macro Layer 실행 (Multi-Agent Ensemble)
    """
    from src.agents.macro import GeopoliticalAgent, SectorAgent, MonetaryAgent
    from src.agents.macro.ensemble import ensemble_insights

    # 병렬 실행
    geo_agent = GeopoliticalAgent()
    sector_agent = SectorAgent()
    monetary_agent = MonetaryAgent()

    results = await asyncio.gather(
        geo_agent.analyze(state["news_data"]),
        sector_agent.analyze(state["market_data"]),
        monetary_agent.analyze(state["market_data"])
    )

    # Ensemble
    state["macro_insights"] = ensemble_insights(*results)
    state["market_regime"] = state["macro_insights"]["regime"]

    return state
```

### Conditional Routing

```python
def route_critic_decision(state: PortfolioState) -> str:
    """
    Critic의 결정에 따라 다음 노드 결정
    """
    decision = state["critic_decision"]
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)

    if decision in ["APPROVE", "APPROVE_WITH_WARNINGS"]:
        return "APPROVE"

    if iteration >= max_iterations:
        # 최대 반복 횟수 초과 시 강제 종료
        logger.warning(f"Max iterations reached ({max_iterations}). Forcing approval.")
        return "APPROVE_WITH_WARNINGS"

    if decision == "REQUEST_REVISION":
        state["iteration"] = iteration + 1
        return "REQUEST_REVISION"

    if decision == "REJECT":
        state["iteration"] = iteration + 1
        return "REJECT"

    return "APPROVE"
```

## 실행 모드

### 1. Full Run (전체 실행)
```python
from src.orchestration.graph import create_portfolio_graph

graph = create_portfolio_graph()
app = graph.compile()

initial_state = {
    "iteration": 0,
    "max_iterations": 3
}

result = await app.ainvoke(initial_state)
print(result["final_portfolio"])
```

### 2. Partial Run (특정 Layer만 실행)
```python
# Macro Analysis만 재실행
partial_graph = StateGraph(PortfolioState)
partial_graph.add_node("macro_analysis", analyze_macro)
partial_graph.set_entry_point("macro_analysis")
partial_graph.add_edge("macro_analysis", END)

app = partial_graph.compile()
result = await app.ainvoke({"news_data": [...], "market_data": [...]})
```

### 3. Retrospection Run (월말 회고)
```python
# 매월 15일 실행
from src.orchestration.graph import create_retrospection_graph

retro_graph = create_retrospection_graph()
app = retro_graph.compile()

result = await app.ainvoke({
    "prediction_id": "2025-01-15-growth",
    "actual_returns": {...}
})
```

## 에러 핸들링

```python
async def safe_node_execution(node_func, state, max_retries=3):
    """
    Node 실행 시 에러 처리 및 재시도
    """
    for attempt in range(max_retries):
        try:
            return await node_func(state)
        except ExternalAPIError as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
        except Exception as e:
            logger.error(f"Unexpected error in {node_func.__name__}: {e}")
            raise

    raise MaxRetriesExceeded(f"Failed after {max_retries} attempts")
```

## 병렬 실행 최적화

```python
# Macro Layer의 3개 Agent를 병렬 실행
async def analyze_macro_parallel(state: PortfolioState) -> PortfolioState:
    agents = [
        GeopoliticalAgent(),
        SectorAgent(),
        MonetaryAgent()
    ]

    # 동시 실행
    tasks = [agent.analyze(state) for agent in agents]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 에러 체크
    valid_results = [r for r in results if not isinstance(r, Exception)]

    if len(valid_results) < 2:
        raise InsufficientAgentResults("Less than 2 agents succeeded")

    return ensemble_insights(valid_results)
```

## 상태 저장 및 체크포인트

```python
from langgraph.checkpoint import MemorySaver

# Checkpointer 설정
checkpointer = MemorySaver()
app = graph.compile(checkpointer=checkpointer)

# 중단 후 재개 가능
config = {"configurable": {"thread_id": "portfolio-2025-01-15"}}
result = await app.ainvoke(initial_state, config=config)

# 나중에 재개
result = await app.ainvoke(None, config=config)
```

## 구현 파일 구조

```
orchestration/
├── graph.py                 # 메인 Graph 정의
├── nodes/
│   ├── data_node.py         # Data Layer 노드
│   ├── macro_node.py        # Macro Layer 노드
│   ├── strategy_node.py     # Strategy Layer 노드
│   ├── validation_node.py   # Validation Layer 노드
│   ├── critic_node.py       # Critic Layer 노드
│   └── retrospection_node.py # Retrospection 노드
├── routing.py               # Conditional routing 로직
├── error_handlers.py        # 에러 핸들링
└── cli.py                   # CLI 인터페이스
```

## CLI 인터페이스

```bash
# 전체 워크플로우 실행
python -m src.orchestration.cli run --profile growth

# Macro Analysis만 실행
python -m src.orchestration.cli run --only macro

# 회고 실행
python -m src.orchestration.cli retrospect --prediction-id 2025-01-15-growth

# 이전 실행 재개
python -m src.orchestration.cli resume --thread-id portfolio-2025-01-15
```

## 모니터링 및 로깅

```python
import logging
from langgraph.graph import Graph

logger = logging.getLogger(__name__)

# 각 노드 실행 전후 로깅
async def logged_node(node_func):
    async def wrapper(state):
        logger.info(f"Starting {node_func.__name__}")
        start_time = time.time()

        result = await node_func(state)

        elapsed = time.time() - start_time
        logger.info(f"Completed {node_func.__name__} in {elapsed:.2f}s")

        return result
    return wrapper
```
