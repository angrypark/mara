# MARA Documentation

이 폴더는 MARA 프로젝트의 핵심 문서를 포함합니다.

## 문서 목록

### 1. [SYSTEM_SUMMARY.md](SYSTEM_SUMMARY.md)
**전체 시스템 요약**

MARA 시스템의 전체 설계를 요약합니다.

- 6-Layer Agent Pipeline 개요
- 유저별 분석 결과 저장 방식
- Agent 추가 및 정리 방식 (Persona-Based)
- 시각화 구조

### 2. [FLOW_DEFINITIONS.md](FLOW_DEFINITIONS.md)
**Growth Flow vs Income Flow 상세 설명**

두 가지 투자 Flow의 차이점, Agent 구성, 실행 순서를 설명합니다.

- Growth Flow: 성장 극대화 (공격적 투자자)
- Income Flow: 현금흐름 창출 (안정 수익 투자자)

### 3. [STATE_PERSISTENCE.md](STATE_PERSISTENCE.md)
**데이터 영속성 및 DB 스키마**

예측 저장, 성과 분석, 과거 데이터 참조 시스템을 설명합니다.

- Database Schema (SQLite)
- Data Flow (입력 → 예측 → 저장 → 성과 분석)
- Repository Pattern

### 4. [AGENT_TRACKING.md](AGENT_TRACKING.md)
**Agent별 추적 및 성과 평가 시스템**

각 Layer의 모든 Agent 예측을 저장하고, 회고 시점에 Agent별 성과를 평가하며, 시각화하는 시스템을 설명합니다.

- Agent-Level Predictions 저장
- Persona-Based Agent System
- Agent별 성과 평가 및 가중치 조정

### 5. [VISUALIZATION_GUIDE.md](VISUALIZATION_GUIDE.md)
**시각화 가이드**

리밸런싱 시점별 분석 결과 시각화 방법을 설명합니다.

- Timeline View (전체 히스토리)
- Detail View (특정 시점 상세)
- Data Files 구조

### 6. [QUICKSTART.md](QUICKSTART.md)
**빠른 시작 가이드**

프로젝트 설치 및 기본 실행 방법을 설명합니다.

- 설치 방법 (uv / pip)
- 환경 변수 설정
- 기본 실행

### 7. [UV_SETUP.md](UV_SETUP.md)
**Python 환경 관리 (UV)**

uv를 사용한 Python 버전 및 의존성 관리 방법을 설명합니다.

## Layer별 상세 문서

각 Layer의 구현 세부사항은 해당 폴더의 README.md를 참조하세요.

| Layer | README 위치 |
|-------|-------------|
| Data Layer | [src/data/README.md](../src/data/README.md) |
| Perspective Agents | [src/agents/perspective/README.md](../src/agents/perspective/README.md) |
| Research Agent | [src/agents/research/README.md](../src/agents/research/README.md) |
| Strategy Layer | [src/agents/strategy/README.md](../src/agents/strategy/README.md) |
| Validation Layer | [src/agents/validation/README.md](../src/agents/validation/README.md) |
| Retrospection Layer | [src/agents/retrospection/README.md](../src/agents/retrospection/README.md) |
| Orchestration | [src/orchestration/README.md](../src/orchestration/README.md) |

## Agent 명세 (AGENT.md)

각 Agent의 상세 명세는 AGENT.md 파일에서 확인할 수 있습니다.

### Perspective Agents

| Agent | AGENT.md 위치 |
|-------|--------------|
| Geopolitical | [perspective/geopolitical/AGENT.md](../src/agents/perspective/geopolitical/AGENT.md) |
| Sector Rotation | [perspective/sector_rotation/AGENT.md](../src/agents/perspective/sector_rotation/AGENT.md) |
| Monetary | [perspective/monetary/AGENT.md](../src/agents/perspective/monetary/AGENT.md) |
| Ray Dalio Macro | [perspective/ray_dalio_macro/AGENT.md](../src/agents/perspective/ray_dalio_macro/AGENT.md) |

### Other Agents

| Agent | AGENT.md 위치 |
|-------|--------------|
| Research | [research/AGENT.md](../src/agents/research/AGENT.md) |
| Strategy Aggregator | [strategy/AGENT.md](../src/agents/strategy/AGENT.md) |
| Validator | [validation/AGENT.md](../src/agents/validation/AGENT.md) |
| Evaluator | [retrospection/AGENT.md](../src/agents/retrospection/AGENT.md) |

## Configuration

**Flow 설정**:
- [Growth Flow Config](../src/config/flows/growth.yaml)
- [Income Flow Config](../src/config/flows/income.yaml)

**Persona 설정**:
- [Ray Dalio Macro](../src/config/personas/ray_dalio_macro.yaml)
- [Warren Buffett Value](../src/config/personas/warren_buffett_value.yaml)

**설정 가이드**: [src/config/README.md](../src/config/README.md)

## 읽는 순서 추천

1. **처음 시작**: [SYSTEM_SUMMARY.md](SYSTEM_SUMMARY.md) - 전체 시스템 이해
2. **Flow 이해**: [FLOW_DEFINITIONS.md](FLOW_DEFINITIONS.md) - Growth vs Income
3. **데이터 구조**: [STATE_PERSISTENCE.md](STATE_PERSISTENCE.md) - DB 스키마
4. **Agent 시스템**: [AGENT_TRACKING.md](AGENT_TRACKING.md) - Persona 기반 Agent
5. **시각화 확인**: [VISUALIZATION_GUIDE.md](VISUALIZATION_GUIDE.md) - 결과 확인
6. **실행 방법**: [QUICKSTART.md](QUICKSTART.md) - 프로젝트 실행

## 아키텍처 요약

```
┌─────────────────────────────────────────────────────────────────┐
│                     6-Layer Agent Pipeline                       │
├─────────────────────────────────────────────────────────────────┤
│  User Profile → Data → Perspective Agents → Strategy            │
│                          (병렬)              ↓                   │
│                            ↑              Validation             │
│                            └── Research ←──┘ (Loop)              │
│                                            ↓                     │
│                                      Retrospection               │
└─────────────────────────────────────────────────────────────────┘
```

## 기술 스택

| 카테고리 | 기술 |
|----------|------|
| Orchestration | LangGraph |
| LLM | Claude Opus 4.5 (Anthropic) |
| Data Sources | yfinance, pandas-datareader (FRED) |
| Optimization | cvxpy |
| Analysis | pandas, numpy, scipy |
| Visualization | plotly, matplotlib |
| Database | SQLite (SQLAlchemy) |
