# MARA Documentation

이 폴더는 MARA 프로젝트의 핵심 문서를 포함합니다.

## 문서 목록

### 1. [SYSTEM_SUMMARY.md](SYSTEM_SUMMARY.md)
**전체 시스템 요약 ⭐ 먼저 읽기**

MARA 시스템의 전체 설계를 요약합니다.

- 유저별 분석 결과 저장 방식
- Agent 추가 및 정리 방식 (Persona-Based)
- 과거 시점 분석 결과의 Agent별 평가
- 시각화 구조

### 2. [FLOW_DEFINITIONS.md](FLOW_DEFINITIONS.md)
**Growth Flow vs Income Flow 상세 설명**

두 가지 투자 Flow의 차이점, Agent 구성, 실행 순서를 설명합니다.

- Growth Flow: 성장 극대화 (나)
- Income Flow: 현금흐름 창출 (부모님)

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
- Persona-Based Agent System (Ray Dalio, Warren Buffett 등)
- Agent별 성과 평가 및 가중치 조정
- Evaluation Triggers

### 5. [VISUALIZATION_GUIDE.md](VISUALIZATION_GUIDE.md)
**시각화 가이드**

리밸런싱 시점별 분석 결과 시각화 방법을 설명합니다.

- Timeline View (전체 히스토리)
- Detail View (특정 시점 상세)
- Data Files 구조
- Visualization 생성 Workflow

### 6. [QUICKSTART.md](QUICKSTART.md)
**빠른 시작 가이드**

프로젝트 설치 및 기본 실행 방법을 설명합니다.

- 설치 방법
- 기본 실행
- 일반적인 사용 시나리오

### 7. [UV_SETUP.md](UV_SETUP.md)
**Python 환경 관리 (UV)**

uv를 사용한 Python 버전 및 의존성 관리 방법을 설명합니다.

- UV 설치 및 설정
- 의존성 관리
- 개발 워크플로우

## 추가 문서

### Layer별 상세 문서
각 Layer의 구현 세부사항은 해당 폴더의 README.md를 참조하세요.

- [Data Layer](../src/data/README.md)
- [Macro Layer](../src/agents/macro/README.md)
- [Strategy Layer](../src/agents/strategy/README.md)
- [Validation Layer](../src/agents/validation/README.md)
- [Critic Layer](../src/agents/critic/README.md)
- [Retrospection Layer](../src/agents/retrospection/README.md)

### Agent Prompt 문서
각 Agent의 LLM System Prompt:

- [Geopolitical Agent](../src/agents/macro/AGENT_PROMPT.md)
- [Growth Strategy Agent](../src/agents/strategy/AGENT_PROMPT.md)

### Configuration

**Flow 설정**:
- [Growth Flow Config](../src/config/flows/growth.yaml)
- [Income Flow Config](../src/config/flows/income.yaml)

**Persona 설정**:
- [Ray Dalio Macro](../src/config/personas/ray_dalio_macro.yaml)
- [Warren Buffett Value](../src/config/personas/warren_buffett_value.yaml)

### Sample Outputs

**데이터 파일**:
- [2025-01-17 Full Prediction](../outputs/data/marv_2025-01-17_full.json)
- [2025-01-17 Evaluation](../outputs/data/marv_2025-01-17_evaluation.json)

**시각화**:
- [Timeline View](../outputs/visualizations/marv_timeline.html) - 전체 히스토리
- [Detail View](../outputs/visualizations/marv_2025-01-17_detail.html) - 특정 시점 상세

## 읽는 순서 추천

1. **처음 시작**: [SYSTEM_SUMMARY.md](SYSTEM_SUMMARY.md) - 전체 시스템 이해
2. **Flow 이해**: [FLOW_DEFINITIONS.md](FLOW_DEFINITIONS.md) - Growth vs Income
3. **데이터 구조**: [STATE_PERSISTENCE.md](STATE_PERSISTENCE.md) - DB 스키마
4. **Agent 시스템**: [AGENT_TRACKING.md](AGENT_TRACKING.md) - Persona 기반 Agent
5. **시각화 확인**: [VISUALIZATION_GUIDE.md](VISUALIZATION_GUIDE.md) - 결과 확인
6. **실행 방법**: [QUICKSTART.md](QUICKSTART.md) - 프로젝트 실행
