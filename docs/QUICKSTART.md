# Quick Start Guide

MARA 프로젝트를 빠르게 시작하는 가이드입니다.

## 사전 요구사항

- Python 3.11+
- pip 또는 uv
- Anthropic API Key

## 설치

### 1. 저장소 클론 및 환경 설정

```bash
cd mara
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 또는 uv 사용
uv venv
source .venv/bin/activate
```

### 2. 의존성 설치

```bash
pip install -r requirements.txt

# 또는 uv 사용
uv pip install -r requirements.txt
```

### 3. 환경 변수 설정

```bash
cp .env.example .env
```

`.env` 파일에 API 키 입력:
```bash
ANTHROPIC_API_KEY=sk-ant-your-api-key-here
ALPHA_VANTAGE_API_KEY=your-api-key-here  # 선택사항
```

### 4. 데이터 디렉토리 권한 확인

```bash
chmod -R 755 data outputs
```

## 기본 실행

### 1. 전체 워크플로우 실행

```bash
python -m src.orchestration.cli run --profile growth
```

**출력**:
```
[INFO] Starting MARA workflow for profile: growth
[INFO] Data collection... ✓
[INFO] Macro analysis... ✓
[INFO] Strategy design... ✓
[INFO] Validation... ✓
[INFO] Critic review... ✓

Final Portfolio:
  Cash: 15%
  XLK (Technology): 30%
  XLV (Healthcare): 20%
  ...

Report saved to: outputs/reports/2025-01-15_growth_portfolio.md
```

### 2. 특정 Layer만 실행

```bash
# Macro Analysis만
python -m src.orchestration.cli run --only macro

# Strategy Design만
python -m src.orchestration.cli run --only strategy --profile income
```

### 3. 회고 실행 (월말)

```bash
python -m src.orchestration.cli retrospect \
    --prediction-id 2025-01-15-growth \
    --start-date 2025-01-15 \
    --end-date 2025-02-15
```

## 설정 커스터마이징

### 1. 투자 프로필 수정

[config/profiles/growth.yaml](../src/config/profiles/growth.yaml) 편집:

```yaml
profile_name: growth
risk_tolerance: high
constraints:
  max_single_sector: 0.40  # 단일 섹터 최대 40%
  max_drawdown_tolerance: 0.35  # 최대 낙폭 35%
  min_cash_ratio: 0.05  # 최소 현금 5%
```

### 2. Agent 페르소나 수정

[config/personas/geopolitical.yaml](../src/config/personas/geopolitical.yaml) 편집:

```yaml
agent_name: geopolitical_agent
persona: |
  You are a geopolitical analyst...

sensitivity: conservative  # conservative, moderate, aggressive
```

### 3. Ensemble 가중치 조정

[config/ensemble_weights.yaml](../src/config/ensemble_weights.yaml):

```yaml
macro_ensemble:
  default:
    geopolitical_agent: 0.30
    sector_rotation_agent: 0.40  # 섹터 분석 비중 높임
    monetary_agent: 0.30
```

## 일반적인 사용 시나리오

### Scenario 1: 월별 포트폴리오 리밸런싱

```bash
# 매월 15일 실행
python -m src.orchestration.cli run --profile growth --output outputs/portfolios/

# 생성된 리포트 확인
cat outputs/reports/latest_growth_portfolio.md

# 실행 계획 확인 후 실제 거래
```

### Scenario 2: 새로운 투자 프로필 생성

```bash
# 1. 프로필 파일 복사
cp src/config/profiles/growth.yaml src/config/profiles/my_profile.yaml

# 2. 파일 편집
vim src/config/profiles/my_profile.yaml

# 3. 실행
python -m src.orchestration.cli run --profile my_profile
```

### Scenario 3: 백테스팅으로 전략 검증

```bash
# Strategy 제안 없이 Validation만
python -m src.orchestration.cli backtest \
    --allocation '{"XLK": 0.3, "XLV": 0.2, "AGG": 0.3, "cash": 0.2}' \
    --start-date 2015-01-01 \
    --end-date 2025-01-01
```

**출력**:
```
Backtesting Results (2015-01-01 to 2025-01-01):
  Total Return: 152.3%
  Annual Return: 14.3%
  Sharpe Ratio: 0.77
  Max Drawdown: -28.4%
  Win Rate: 62%
```

### Scenario 4: Stress Test

```bash
python -m src.orchestration.cli stress-test \
    --allocation '{"XLK": 0.3, "XLV": 0.2, ...}' \
    --scenario 2008_financial_crisis
```

## 프로젝트 구조 둘러보기

```
mara/
├── src/
│   ├── data/              # 데이터 수집
│   ├── agents/            # 각 Layer의 Agent 구현
│   │   ├── macro/
│   │   ├── strategy/
│   │   ├── validation/
│   │   ├── critic/
│   │   └── retrospection/
│   ├── orchestration/     # LangGraph 워크플로우
│   ├── utils/             # 유틸리티 함수
│   └── config/            # 설정 파일
├── data/                  # 로컬 데이터 저장
│   ├── raw/
│   ├── processed/
│   └── cache/
├── outputs/               # 출력 파일
│   ├── reports/           # 포트폴리오 리포트
│   ├── portfolios/        # 포트폴리오 JSON
│   └── logs/              # 로그 파일
├── tests/                 # 테스트 코드
└── docs/                  # 문서
```

## 다음 단계

1. **[Flow Definitions](FLOW_DEFINITIONS.md)**: Growth vs Income Flow 상세 설명
2. **[State Persistence](STATE_PERSISTENCE.md)**: DB 스키마 및 데이터 영속성
3. **[UV Setup](UV_SETUP.md)**: Python 환경 관리 가이드
4. **각 Layer별 README**: 구현 세부사항 확인
   - [Data Layer](../src/data/README.md)
   - [Macro Layer](../src/agents/macro/README.md)
   - [Strategy Layer](../src/agents/strategy/README.md)
   - [Validation Layer](../src/agents/validation/README.md)
   - [Critic Layer](../src/agents/critic/README.md)
   - [Retrospection Layer](../src/agents/retrospection/README.md)

## 문제 해결

### API 호출 실패

```bash
# 로그 확인
tail -f outputs/logs/data_collector_$(date +%Y%m%d).log

# 캐시 초기화
rm -rf data/cache/*.pkl
```

### 메모리 부족

```yaml
# config/system.yaml
langgraph:
  max_iterations: 2  # 반복 횟수 줄이기

llm:
  model: claude-sonnet-3-5-20241022  # 더 작은 모델 사용
```

### 느린 실행 속도

```python
# 병렬 실행 활성화
# src/orchestration/graph.py에서
enable_parallel = True
```

## 지원

- GitHub Issues: https://github.com/marv/mara/issues
- 문서: [docs/](../docs/)
