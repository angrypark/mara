# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MARA (Macro Asset Rebalance Agent) is an AI-driven portfolio optimization system that uses multiple specialized agents to analyze macroeconomic conditions and provide personalized portfolio rebalancing recommendations. Built with LangGraph for agent orchestration.

## Development Commands

```bash
# Install dependencies (using uv - preferred)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Or with pip
pip install -r requirements.txt

# Run the full workflow
python -m src.orchestration.cli run --profile growth
python -m src.orchestration.cli run --profile income

# Run retrospection (monthly evaluation)
python -m src.orchestration.cli retrospect --prediction-id 2025-01-15-growth

# Run backtest
python -m src.orchestration.cli backtest --allocation '{"XLK": 0.3, "XLV": 0.2}' --start-date 2015-01-01

# Linting and formatting
ruff check src/ --fix
black src/ tests/
mypy src/

# Run tests
pytest
pytest tests/test_specific.py -v
pytest --cov=src --cov-report=html
```

## Architecture

### 6-Layer Agent Pipeline

1. **User Profile Layer** → 현재 포트폴리오, 투자 목표(공격/균형/안정), 리스크 허용도 정의
2. **Data Layer** → 리포트/뉴스/트윗 수집 및 요약, 가격 변동 분석
3. **Perspective Agents** → 다양한 관점(Geopolitical, Sector Rotation, Ray Dalio Macro, Monetary)에서 병렬 분석 및 리밸런싱 제안
4. **Strategy Layer** → 여러 Agent 제안을 종합하여 최종 포트폴리오 조정 방향 제시
5. **Validation Layer** → Backtest, 리스크 측정으로 목표 조건 충족 여부 검증 (Strategy ↔ Validation 루프)
6. **Retrospection Layer** → 시간 경과 후 예측 vs 실제 비교, Agent 가중치 조정 제안

### Tools

Agent가 LangGraph Tool로 호출하는 도구들 (`src/tools/`):
- **Price Tool** (`src/tools/market/price.py`): 종목의 현재가, 과거 가격, 수익률 조회
- **Portfolio Loader** (`src/tools/market/portfolio.py`): ETF/펀드 구성 종목 조회
- **Backtest Tool** (`src/tools/analysis/backtest.py`): 포트폴리오 과거 성과 시뮬레이션
- **Risk Tool** (`src/tools/analysis/risk.py`): MDD, VaR, Volatility, Beta 계산

> **Note**: 뉴스/리포트 수집은 Tool이 아닌 Data Layer(`src/data/collectors/`)에서 처리

### Loop Termination Conditions

**Perspective Agent ↔ Research Agent (최대 3회)**:
- 종료: 충분한 정보 확보 시 조기 종료 / 3회 도달 시 현재까지 수집된 정보로 진행
- 실패: Research Agent 응답 실패 시 자체 분석으로 fallback

**Strategy ↔ Validation Loop (최대 3회)**:
- ✅ 성공: 모든 리스크 조건 충족
- ⚠️ 부분 승인: 3회 후에도 일부 미충족 시, 위반 사항 명시 + 사용자 확인 요청
- ❌ 거부: 핵심 리스크(MDD) 위반 시 보수적 대안 제시

### Persona-Based Agent System

Agents are defined by their investment philosophy (Persona):
- **Config files**: `src/config/personas/*.yaml` - define analysis framework and output format
- **Flow configs**: `src/config/flows/{growth,income}.yaml` - which personas to use with what weights

To add a new agent:
1. Create persona config in `src/config/personas/`
2. Add to flow config with weight and layer assignment

### State Management (LangGraph)

Key state objects passed through the pipeline:
- `UserProfileState`: 포트폴리오, 투자 목표, 리스크 허용도
- `DataState`: 시장 데이터 요약, 가격 변동, 핵심 인사이트
- `PerspectiveState`: 각 Agent별 평가 및 리밸런싱 제안
- `StrategyState`: 종합된 포트폴리오 조정 방향, 최종 비중
- `ValidationState`: 백테스팅 결과, 리스크 메트릭, 승인/거부
- `RetrospectionState`: 예측 vs 실제, 학습 인사이트, Agent 가중치 조정

### Output Schemas

Core Pydantic models (`src/core/models.py`):
- `RebalanceProposal`: 개별 Agent 리밸런싱 제안 (ticker, action, target_weight, confidence, rationale)
- `PerspectiveOutput`: Perspective Agent 전체 출력 (market_outlook, proposals[], risk_assessment)
- `PortfolioAllocation`: 최종 포트폴리오 배분 (ticker, weight, rationale)
- `StrategyOutput`: Strategy Layer 출력 (allocations[], dominant_perspective, dissenting_views)
- `ValidationResult`: Validation 결과 (is_approved, risk_metrics, violations[], feedback)

### Database Tables

- `agent_predictions`: Individual agent analyses per run
- `agent_evaluations`: Performance comparison (predicted vs actual) after 1 month
- `agent_personas`: Persona definitions and default weights

## Project Structure

```
mara/
├── src/
│   ├── core/              # 핵심 도메인
│   │   ├── state.py       # LangGraph State 정의 (6개 State 클래스)
│   │   ├── models.py      # 도메인 모델 (Pydantic) - Output Schemas
│   │   ├── profile.py     # User Profile 로더 (YAML → UserProfileState)
│   │   └── exceptions.py  # 커스텀 예외 (MARAException 계층)
│   ├── data/              # Data Layer
│   │   ├── collectors/    # 데이터 수집 (news.py, report.py)
│   │   ├── analyzers/     # 데이터 분석 (price.py, sentiment.py)
│   │   └── summarizer.py  # LLM 기반 텍스트 요약
│   ├── tools/             # LangGraph Tools
│   │   ├── market/        # price.py, portfolio.py
│   │   └── analysis/      # backtest.py, risk.py
│   ├── agents/            # Agent Layers
│   │   ├── perspective/   # base.py, factory.py (Persona YAML → Agent)
│   │   ├── research/      # agent.py (웹 검색, 심층 조사)
│   │   ├── strategy/      # aggregator.py, optimizer.py (cvxpy)
│   │   ├── validation/    # validator.py (리스크 검증, 피드백)
│   │   └── retrospection/ # evaluator.py (예측 vs 실제, 가중치 조정)
│   ├── orchestration/     # LangGraph 워크플로우
│   │   ├── graph.py       # 메인 그래프 정의
│   │   ├── nodes.py       # 노드 함수들
│   │   └── cli.py         # CLI 엔트리포인트
│   ├── db/                # SQLite 데이터베이스
│   │   ├── models.py      # SQLAlchemy 모델
│   │   ├── repository.py  # 데이터 접근 계층
│   │   └── migrations/    # Alembic 마이그레이션
│   ├── utils/             # 공통 유틸리티 (llm.py, cache.py, logging.py)
│   └── config/            # YAML 설정 파일
│       ├── flows/         # growth.yaml, income.yaml
│       ├── personas/      # ray_dalio_macro.yaml 등
│       └── profiles/      # 사용자 투자 프로필
├── data/                  # 로컬 데이터 (raw/, processed/, cache/)
├── outputs/               # 출력 (reports/, portfolios/, visualizations/, logs/)
├── tests/                 # unit/, integration/, fixtures/
└── docs/                  # 문서
```

## Key Configuration Files

- `src/config/flows/growth.yaml` - Aggressive investor flow (higher equity, sector rotation focus)
- `src/config/flows/income.yaml` - Retiree flow (income-focused, lower drawdown tolerance)
- `src/config/personas/ray_dalio_macro.yaml` - All Weather strategy persona
- `src/config/personas/warren_buffett_value.yaml` - Value investing persona
- `src/config/ensemble_weights.yaml` - Agent 간 가중치 설정

## Environment Setup

Required environment variables in `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
ALPHA_VANTAGE_API_KEY=...  # optional
```

## Error Handling

### Retry Policy
| Component | Retries | Backoff | Timeout |
|-----------|---------|---------|---------|
| LLM API (Anthropic) | 3 | Exponential (1s, 2s, 4s) | 60s |
| Market Data (yfinance) | 2 | Linear (2s, 4s) | 30s |
| Research Agent | 2 | Linear (1s, 2s) | 20s |

### Fallback Strategy
- **LLM API 장애**: 캐시된 최근 분석 결과 사용 (24시간 이내), 없으면 중단
- **Market Data 장애**: 캐시된 가격 데이터 사용 (1시간 이내), stale 경고 표시
- **Research Agent 실패**: Perspective Agent가 자체 분석으로 진행 (research_failed 플래그)
- **개별 Perspective Agent 실패**: 해당 Agent 제외, 나머지로 종합 (최소 2개 필요)
- **Validation Backtest 실패**: 리스크 메트릭만으로 검증 (backtest_skipped 경고)

### Exception Hierarchy (`src/core/exceptions.py`)
```python
MARAException          # Base exception
├── DataFetchError     # 데이터 수집 실패
├── LLMResponseError   # LLM 응답 파싱/검증 실패
├── ValidationError    # 리스크 검증 실패 (3회 후에도 미충족)
├── AgentTimeoutError  # Agent 실행 시간 초과
└── InsufficientAgentsError  # 최소 Agent 수(2개) 미달
```

## Tech Stack

- **Orchestration**: LangGraph
- **LLM**: Claude Opus 4.5 (Anthropic)
- **Data Sources**: yfinance, pandas-datareader (FRED)
- **Optimization**: cvxpy (Mean-Variance Optimization)
- **Analysis**: pandas, numpy, scipy
- **Visualization**: plotly, matplotlib

## Python Version

Requires Python 3.11+ (< 3.13)
