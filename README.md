# MARA: Macro Asset Rebalance Agent

AI 기반 거시 경제 분석 및 개인 맞춤형 동적 포트폴리오 최적화 시스템

## 🚀 Key Features

- **8-Layer Agent Architecture**: Portfolio Input → Data → Macro → Research → Strategy → Rebalancing → Validation → Critic
- **Persona-Based Agents**: Ray Dalio, Warren Buffett 등 다양한 투자 철학을 가진 Agent 추가 가능
- **Dual-Flow Strategy**:
    - **Growth Flow**: 섹터 로테이션 중심, 높은 변동성 허용, 월급으로 리밸런싱
    - **Income Flow**: 현금흐름 창출, 원금 보존, 인플레이션 헤지, 분기별 리밸런싱
- **Agent-Level Tracking**: 모든 Agent의 개별 예측을 저장하고 성과 평가
- **Self-Learning System**: 과거 예측 대비 실제 성과 분석 → Agent 가중치 자동 조정 제안
- **Interactive Visualization**: Timeline & Detail View로 전체 분석 과정 시각화

## 🏗 System Architecture

본 프로젝트는 LangGraph를 활용하여 에이전트 간의 상태(State)를 관리하고 순환 구조를 구현합니다.

### 8-Layer Architecture

```
┌─────────────────────────────────────────────────────────┐
│  0. Portfolio Input Layer                               │
│  현재 포트폴리오 입력 및 정규화                              │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  1. Data Layer                                          │
│  외부 데이터 수집 및 정규화                                 │
│  - MCP Tools Integration (News, Reports, Prices)        │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  2. Macro Layer (Multi-Agent Ensemble)                  │
│  - Geopolitical Agent (지정학 리스크)                     │
│  - Sector Rotation Agent (섹터 사이클)                   │
│  - Ray Dalio Macro Agent (리스크 패리티)                 │
│  - Monetary Agent (금리 정책)                            │
│  → Output: Market Regime & Sector Outlook               │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  3. Research Layer                                      │
│  신규 종목 발굴 및 테마 분석                                │
│  - Theme Investment (AI, 반도체 등)                      │
│  - Warren Buffett Screener (가치주 발굴)                │
│  → Output: Investment Opportunities                     │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  4. Strategy Layer                                      │
│  - Growth/Income Strategy Agent                         │
│  - 3개 후보 전략 생성 (Aggressive, Balanced, Defensive)  │
│  → Output: 3 Strategy Candidates                        │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  5. Rebalancing Layer                                   │
│  - Cash Flow Based (월급 활용)                           │
│  - Threshold Based (괴리 5% 시)                          │
│  - Calendar Based (분기별)                               │
│  → Output: Rebalancing Actions                          │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  6. Validation Layer                                    │
│  정량적 검증 및 리스크 분석                                 │
│  - Backtesting (과거 10년)                               │
│  - Risk Metrics (Sharpe, Max DD, VaR)                   │
│  - Stress Testing (2008, 2020 시나리오)                  │
│  → Output: Performance Metrics & Risk Report            │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  5. Critic Layer                                        │
│  최종 검토 및 의사결정                                      │
│  - Logic Consistency Checker                            │
│  - Cross-Agent Validation                               │
│  - Final Portfolio Generator                            │
│  → Output: Approved Portfolio + Rationale               │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│  6. Retrospection Layer                                 │
│  자가 학습 및 성과 분석                                     │
│  - Prediction vs Actual Comparison                      │
│  - Agent Performance Attribution                        │
│  - Feedback Loop to Macro/Strategy Layers               │
│  → Output: Learning Report & Agent Adjustments          │
└─────────────────────────────────────────────────────────┘
```

### State Management (LangGraph)

각 Layer는 공유 State를 읽고 쓰며, 다음 정보를 전달합니다:

- **MarketState**: 현재 시장 국면, 섹터 전망, 거시 지표
- **StrategyState**: 목표 포트폴리오 비중, 현금 비중, 리밸런싱 계획
- **ValidationState**: 백테스팅 결과, 리스크 메트릭, 경고 사항
- **CriticState**: 승인/거부 여부, 수정 요청, 최종 결정
- **RetrospectionState**: 지난달 예측, 실제 성과, 학습 인사이트

## 📂 Project Structure

```
mara/
├── src/
│   ├── data/              # Data Layer - 외부 데이터 수집 및 정규화
│   ├── agents/            # Agent Layers
│   │   ├── macro/         # Macro Insight Layer
│   │   ├── strategy/      # Strategy Design Layer
│   │   ├── validation/    # Validation Layer
│   │   ├── critic/        # Critic Layer
│   │   └── retrospection/ # Retrospection Layer
│   ├── orchestration/     # LangGraph 워크플로우 관리
│   ├── utils/             # 공통 유틸리티 함수
│   └── config/            # YAML 설정 파일
├── data/                  # 로컬 데이터 저장소
│   ├── raw/               # 원본 데이터
│   ├── processed/         # 전처리된 데이터
│   └── cache/             # 캐시 데이터
├── outputs/               # 출력 결과물
│   ├── reports/           # 포트폴리오 리포트 (Markdown)
│   ├── portfolios/        # 포트폴리오 정의 (JSON)
│   └── logs/              # 실행 로그
├── tests/                 # 테스트 코드
└── docs/                  # 문서
    ├── ARCHITECTURE.md    # 시스템 아키텍처 상세
    └── QUICKSTART.md      # 빠른 시작 가이드
```

각 폴더에는 상세한 설명이 담긴 `README.md`가 포함되어 있습니다.

## 🚦 Quick Start

### 1. 설치

```bash
# 의존성 설치
pip install -r requirements.txt

# 환경 변수 설정
cp .env.example .env
# .env 파일에 ANTHROPIC_API_KEY 입력
```

### 2. 기본 실행

```bash
# Growth 프로필로 전체 워크플로우 실행
python -m src.orchestration.cli run --profile growth

# Income 프로필로 실행
python -m src.orchestration.cli run --profile income
```

### 3. 출력 확인

```bash
# 생성된 리포트 확인
cat outputs/reports/latest_growth_portfolio.md

# 포트폴리오 JSON 확인
cat outputs/portfolios/latest_growth_portfolio.json
```

더 자세한 사용법은 [Quick Start Guide](docs/QUICKSTART.md)를 참고하세요.

## 🎯 Use Cases

### 1. 월별 포트폴리오 리밸런싱
매월 15일 실행하여 최신 거시 경제 상황을 반영한 포트폴리오 제안을 받습니다.

### 2. 투자 전략 백테스팅
제안된 포트폴리오를 과거 10년 데이터로 시뮬레이션하여 예상 성과를 확인합니다.

### 3. 리스크 관리
현재 포트폴리오의 Max Drawdown, VaR 등을 계산하여 리스크를 모니터링합니다.

### 4. 성과 회고
매달 예측 vs 실제 성과를 비교하여 시스템을 개선합니다.

## 🛠 Customization

### 투자 프로필 커스터마이징

[src/config/profiles/](src/config/profiles/)에서 프로필을 수정하거나 새로 생성할 수 있습니다.

```yaml
# src/config/profiles/my_profile.yaml
profile_name: my_profile
risk_tolerance: medium
constraints:
  max_drawdown_tolerance: 0.25
  min_cash_ratio: 0.10
```

### Agent 페르소나 수정

[src/config/personas/](src/config/personas/)에서 각 Agent의 분석 관점을 조정할 수 있습니다.

```yaml
# src/config/personas/geopolitical.yaml
sensitivity: conservative  # conservative, moderate, aggressive
```

### Ensemble 가중치 조정

[src/config/ensemble_weights.yaml](src/config/ensemble_weights.yaml)에서 Agent 간 가중치를 조정할 수 있습니다.

```yaml
macro_ensemble:
  default:
    geopolitical_agent: 0.30
    sector_rotation_agent: 0.40
    monetary_agent: 0.30
```

## 📚 Documentation

### 📖 읽는 순서

1. **[System Summary](docs/SYSTEM_SUMMARY.md)** ⭐ - 전체 시스템 요약 (처음 읽기)
2. **[Flow Definitions](docs/FLOW_DEFINITIONS.md)** - Growth vs Income Flow
3. **[Agent Tracking](docs/AGENT_TRACKING.md)** - Agent별 추적 및 성과 평가
4. **[Visualization Guide](docs/VISUALIZATION_GUIDE.md)** - 시각화 결과 확인
5. **[Quick Start](docs/QUICKSTART.md)** - 설치 및 실행

### Core Documentation
- [System Summary](docs/SYSTEM_SUMMARY.md) - 전체 시스템 설계 요약
- [Flow Definitions](docs/FLOW_DEFINITIONS.md) - Growth vs Income Flow 상세
- [State Persistence](docs/STATE_PERSISTENCE.md) - DB 스키마 및 데이터 영속성
- [Agent Tracking](docs/AGENT_TRACKING.md) - Agent별 예측 저장 및 성과 평가
- [Visualization Guide](docs/VISUALIZATION_GUIDE.md) - Timeline & Detail View 가이드
- [Quick Start](docs/QUICKSTART.md) - 빠른 시작 가이드
- [UV Setup](docs/UV_SETUP.md) - Python 환경 관리

### Layer Documentation
- [Data Layer](src/data/README.md) - 데이터 수집 및 정규화
- [Macro Layer](src/agents/macro/README.md) - 거시 경제 분석
- [Strategy Layer](src/agents/strategy/README.md) - 투자 전략 수립
- [Validation Layer](src/agents/validation/README.md) - 백테스팅 및 리스크 분석
- [Critic Layer](src/agents/critic/README.md) - 최종 검토 및 의사결정
- [Retrospection Layer](src/agents/retrospection/README.md) - 성과 분석 및 자가 학습

### Configuration
- **Flow 설정**: [Growth](src/config/flows/growth.yaml) | [Income](src/config/flows/income.yaml)
- **Persona 설정**: [Ray Dalio](src/config/personas/ray_dalio_macro.yaml) | [Warren Buffett](src/config/personas/warren_buffett_value.yaml)

### Sample Outputs
- **데이터**: [Prediction](outputs/data/marv_2025-01-17_full.json) | [Evaluation](outputs/data/marv_2025-01-17_evaluation.json)
- **시각화**: [Timeline](outputs/visualizations/marv_timeline.html) | [Detail](outputs/visualizations/marv_2025-01-17_detail.html)

## 🔧 Tech Stack

- **Orchestration**: LangGraph
- **LLM**: Claude Opus 4.5 (Anthropic)
- **Data Sources**: MCP Tools, Yahoo Finance, FRED
- **Optimization**: cvxpy (Mean-Variance Optimization)
- **Analysis**: pandas, numpy, scipy
- **Visualization**: matplotlib, plotly
- **Configuration**: YAML
- **Caching**: SQLite / Redis

## 📝 License

MIT License

## 🤝 Contributing

이슈 및 Pull Request를 환영합니다!

## ⚠️ Disclaimer

본 프로젝트는 교육 및 연구 목적으로 개발되었습니다. 실제 투자 결정은 개인의 책임 하에 이루어져야 하며, 본 시스템의 제안은 참고용으로만 활용하시기 바랍니다.

