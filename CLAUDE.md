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

### 5-Layer Agent Pipeline

1. **User Profile Layer** → 현재 포트폴리오, 투자 목표(공격/균형/안정), 리스크 허용도 정의
2. **Data Layer** → 리포트/뉴스/트윗 수집 및 요약, 가격 변동 분석
3. **Perspective Agents** → 다양한 관점(Geopolitical, Sector Rotation, Ray Dalio Macro, Monetary)에서 병렬 분석 및 리밸런싱 제안
4. **Strategy Layer** → 여러 Agent 제안을 종합하여 최종 포트폴리오 조정 방향 제시
5. **Validation Layer** → Backtest, 리스크 측정으로 목표 조건 충족 여부 검증 (Strategy ↔ Validation 루프)
6. **Retrospection Layer** → 시간 경과 후 예측 vs 실제 비교, Agent 가중치 조정 제안

### Tools

Agent가 사용하는 도구들 (`src/tools/`):
- **Price Tool**: 특정 종목의 현재가, 과거 가격, 수익률 조회
- **Portfolio Loader**: 특정 기관/펀드의 포트폴리오 다운로드
- **News Fetcher**: 최신 뉴스 및 트윗 수집
- **Report Fetcher**: 전문가 리포트 수집
- **Backtest Tool**: 포트폴리오 백테스팅 수행

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

### Database Tables

- `agent_predictions`: Individual agent analyses per run
- `agent_evaluations`: Performance comparison (predicted vs actual) after 1 month
- `agent_personas`: Persona definitions and default weights

## Project Structure

```
mara/
├── src/
│   ├── data/              # Data Layer - 데이터 수집, 요약, 가격 분석
│   ├── tools/             # Tools - Agent가 사용하는 도구들
│   │   ├── price/         # Price Tool
│   │   ├── portfolio/     # Portfolio Loader
│   │   ├── news/          # News Fetcher
│   │   ├── report/        # Report Fetcher
│   │   └── backtest/      # Backtest Tool
│   ├── agents/            # Agent Layers
│   │   ├── perspective/   # Perspective Agents (지정학, 섹터, 매크로, 금리)
│   │   ├── research/      # Research Agent
│   │   ├── strategy/      # Strategy Layer
│   │   ├── validation/    # Validation Layer
│   │   └── retrospection/ # Retrospection Layer
│   ├── orchestration/     # LangGraph 워크플로우 관리
│   ├── utils/             # 공통 유틸리티 함수
│   └── config/            # YAML 설정 파일
│       ├── flows/         # growth.yaml, income.yaml
│       ├── personas/      # ray_dalio_macro.yaml, warren_buffett_value.yaml 등
│       └── profiles/      # 투자 프로필 설정
├── data/                  # 로컬 데이터 저장소 (raw, processed, cache)
├── outputs/               # 출력 결과물 (reports, portfolios, logs, visualizations)
├── tests/                 # 테스트 코드
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

## Tech Stack

- **Orchestration**: LangGraph
- **LLM**: Claude Opus 4.5 (Anthropic)
- **Data Sources**: MCP Tools, Yahoo Finance, FRED
- **Optimization**: cvxpy (Mean-Variance Optimization)
- **Analysis**: pandas, numpy, scipy
- **Visualization**: matplotlib, plotly

## Python Version

Requires Python 3.11+ (< 3.13)
