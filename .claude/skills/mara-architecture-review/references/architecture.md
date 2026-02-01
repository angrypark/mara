# MARA Architecture Reference

## 6-Layer Agent Pipeline

### Layer 1: User Profile Layer
**역할**: 현재 포트폴리오, 투자 목표, 리스크 허용도 정의

**State**: `UserProfileState`
```python
{
    "portfolio": dict,           # 현재 포트폴리오
    "goal": str,                 # "aggressive" | "balanced" | "defensive"
    "risk_tolerance": {
        "max_drawdown": float,   # 최대 허용 낙폭
        "max_volatility": float, # 최대 허용 변동성
        "max_var_95": float      # 95% VaR 제한
    }
}
```

### Layer 2: Data Layer
**역할**: 뉴스, 리포트 수집 및 요약 / 가격 변동 분석

**State**: `DataState`
```python
{
    "market_summary": str,       # 시장 상황 요약
    "price_changes": dict,       # 가격 변동 분석
    "key_insights": list[str]    # 핵심 인사이트
}
```

**구성요소**:
- Data Collector: 뉴스 (RSS/웹 스크래핑), 리포트 수집
- Data Summarizer: LLM 기반 텍스트 요약
- Price Analyzer: yfinance 기반 가격 변동 분석

### Layer 3: Perspective Agents
**역할**: 다양한 관점에서 병렬 분석 및 리밸런싱 제안

**State**: `PerspectiveState`
```python
{
    "agent_id": str,
    "market_outlook": "BULLISH" | "NEUTRAL" | "BEARISH",
    "proposals": list[RebalanceProposal],
    "risk_assessment": str
}
```

**Agents**:
| Agent | 관점 | 폴더 |
|-------|------|------|
| Geopolitical | 지정학적 리스크 | `perspective/geopolitical/` |
| Sector Rotation | 섹터 순환 | `perspective/sector_rotation/` |
| Monetary | 통화정책 | `perspective/monetary/` |
| Ray Dalio Macro | All Weather 전략 | `perspective/ray_dalio_macro/` |

**Research Agent와의 통신**:
- 최대 3회 multi-hop 소통
- 종료: 충분한 정보 확보 시 조기 종료
- 실패: Research Agent 응답 실패 시 자체 분석으로 fallback

### Layer 4: Strategy Layer
**역할**: 여러 Agent 제안을 종합하여 최종 포트폴리오 조정 방향 제시

**State**: `StrategyState`
```python
{
    "allocations": list[PortfolioAllocation],
    "dominant_perspective": str,
    "dissenting_views": list[str]
}
```

**종합 방법**:
1. 각 Agent의 가중치 적용 (과거 성과 기반)
2. 상충되는 제안 조율
3. 제약조건 검증 (섹터/종목 한도)
4. cvxpy 기반 최적화

### Layer 5: Validation Layer
**역할**: Backtest, 리스크 측정으로 목표 조건 충족 여부 검증

**State**: `ValidationState`
```python
{
    "is_approved": bool,
    "approval_type": "full" | "conditional" | "rejected",
    "risk_metrics": dict,
    "violations": list[str],
    "feedback": str | None
}
```

**Loop 종료 조건**:
- ✅ 성공: 모든 리스크 조건 충족
- ⚠️ 부분 승인: 3회 후에도 일부 미충족 시 사용자 확인 요청
- ❌ 거부: 핵심 리스크(MDD) 위반 시 보수적 대안 제시

### Layer 6: Retrospection Layer
**역할**: 시간 경과 후 예측 vs 실제 비교, Agent 가중치 조정 제안

**State**: `RetrospectionState`
```python
{
    "prediction_accuracy": dict,
    "agent_performance": dict,
    "weight_adjustments": dict,
    "learning_insights": list[str]
}
```

## Tools

| Tool | 기능 | 위치 |
|------|------|------|
| Price Tool | 가격 조회 | `src/tools/market/price.py` |
| Portfolio Loader | ETF 구성 조회 | `src/tools/market/portfolio.py` |
| Backtest Tool | 백테스팅 | `src/tools/analysis/backtest.py` |
| Risk Tool | 리스크 계산 | `src/tools/analysis/risk.py` |

## State Management (LangGraph)

모든 Layer는 공유 State를 읽고 쓰며 다음 Layer로 전달:
```
UserProfileState → DataState → PerspectiveState → StrategyState → ValidationState → RetrospectionState
```

## 설계 원칙

| 원칙 | 적용 |
|------|------|
| Layer 분리 | data/ → agents/ → orchestration/ 순서로 의존성 흐름 |
| Persona 기반 확장 | factory.py가 YAML에서 Agent 동적 생성 |
| 도구-에이전트 분리 | tools/는 순수 함수, agents/는 LLM 호출 로직 |
| State 중심 설계 | core/state.py에 모든 State 클래스 정의 |
