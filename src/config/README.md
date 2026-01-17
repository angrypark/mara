# Configuration

프로젝트의 모든 설정을 YAML 파일로 관리하는 폴더입니다.

## 파일 구조

```
config/
├── profiles/              # 투자자 프로필 설정
│   ├── growth.yaml
│   └── income.yaml
├── personas/              # Agent 페르소나 정의
│   ├── geopolitical.yaml
│   ├── sector_rotation.yaml
│   ├── monetary.yaml
│   ├── growth_strategy.yaml
│   ├── income_strategy.yaml
│   └── cash_management.yaml
├── data_sources.yaml      # 데이터 소스 설정
├── thresholds.yaml        # Validation 및 Critic 임계값
├── ensemble_weights.yaml  # Agent 가중치
└── system.yaml            # 시스템 전역 설정
```

## 설정 파일 예시

### 1. Investment Profile (`profiles/growth.yaml`)

```yaml
profile_name: growth
description: 근로소득 기반 공격적 투자자

investor:
  age: 35
  income_stability: high  # high, medium, low
  risk_tolerance: high
  investment_horizon: 10_years
  monthly_contribution: 5000000  # KRW

constraints:
  max_single_sector: 0.40
  max_single_position: 0.15
  max_drawdown_tolerance: 0.35
  min_cash_ratio: 0.05
  max_cash_ratio: 0.30
  rebalancing_threshold: 0.05  # 5% 이상 괴리 시 리밸런싱

targets:
  expected_annual_return: 0.10
  target_volatility: 0.20
  target_sharpe: 0.50

preferences:
  sector_rotation: true
  individual_stocks: false
  leverage: false
  options: false
  international_exposure: 0.20  # 20% 해외 자산

asset_universe:
  - SPY   # S&P 500
  - QQQ   # Nasdaq 100
  - XLK   # Technology
  - XLV   # Healthcare
  - XLF   # Financials
  - XLE   # Energy
  - VNQ   # Real Estate
  - AGG   # Bonds
  - TLT   # Long-term Bonds
```

### 2. Agent Persona (`personas/geopolitical.yaml`)

```yaml
agent_name: geopolitical_agent
persona: |
  You are a former CIA geopolitical analyst with 20 years of experience
  monitoring global power dynamics, trade relations, and regional conflicts.

  Your analysis focuses on:
  - US-China relations and technology decoupling
  - Supply chain resilience and reshoring trends
  - Energy security and commodity geopolitics
  - Regional conflicts and their market impacts

  You provide balanced, data-driven assessments and avoid sensationalism.
  You always cite specific events, policy changes, or expert opinions.

analysis_framework:
  - step: "Identify major geopolitical events in the past month"
  - step: "Assess impact on global trade and investment flows"
  - step: "Evaluate risk to specific sectors (tech, energy, defense)"
  - step: "Determine favorable/unfavorable regions for investment"

output_format:
  regime: "geopolitical_tension_high | stable | improving"
  favorable_regions: ["US", "India", "EU"]
  unfavorable_regions: ["China", "Russia"]
  themes: ["supply_chain_resilience", "defense_spending"]
  confidence: 0.75
  citations: ["source1", "source2"]

data_sources:
  - financial_times
  - bloomberg_geopolitics
  - council_on_foreign_relations
  - stratfor

sensitivity: conservative  # conservative, moderate, aggressive
```

### 3. Data Sources (`data_sources.yaml`)

```yaml
news:
  providers:
    - name: financial_times
      enabled: true
      update_frequency: 3600  # seconds
      cache_ttl: 7200
      topics:
        - "global markets"
        - "central banks"
        - "geopolitics"

    - name: bloomberg
      enabled: true
      update_frequency: 1800
      cache_ttl: 3600
      topics:
        - "equity markets"
        - "commodities"

prices:
  providers:
    - name: yahoo_finance
      enabled: true
      update_frequency: 900  # 15분
      cache_ttl: 1800
      tickers:
        - SPY
        - QQQ
        - XLK
        - XLV
        - TLT

    - name: alpha_vantage
      enabled: false
      api_key: ${ALPHA_VANTAGE_API_KEY}

reports:
  providers:
    - name: mcp_pdf_reader
      enabled: true
      update_frequency: 86400  # daily
      cache_ttl: 259200  # 3 days
      directories:
        - "/Users/marv/reports/macro"
        - "/Users/marv/reports/sectors"

economic_indicators:
  providers:
    - name: fred
      enabled: true
      update_frequency: 86400
      indicators:
        - FEDFUNDS  # Fed Funds Rate
        - UNRATE    # Unemployment
        - CPIAUCSL  # CPI
        - GDP       # GDP
```

### 4. Validation Thresholds (`thresholds.yaml`)

```yaml
validation:
  growth:
    min_annual_return: 0.07
    max_drawdown: 0.35
    min_sharpe: 0.50
    min_win_rate: 0.55

  income:
    min_annual_return: 0.03
    max_drawdown: 0.20
    min_sharpe: 0.30
    min_dividend_yield: 0.025

  stress_test:
    scenarios:
      - name: "2008_financial_crisis"
        max_portfolio_loss: 0.45  # 벤치마크 대비 +5% 이내
      - name: "2020_covid"
        max_portfolio_loss: 0.40
      - name: "2022_inflation"
        max_portfolio_loss: 0.25

critic:
  approve:
    min_consistency_score: 0.80
    min_validation_confidence: 0.85
    max_critical_issues: 0

  approve_with_warnings:
    min_consistency_score: 0.70
    min_validation_confidence: 0.75
    max_critical_issues: 0
    max_warnings: 3

  reject:
    critical_issues_threshold: 1
```

### 5. Ensemble Weights (`ensemble_weights.yaml`)

```yaml
macro_ensemble:
  default:
    geopolitical_agent: 0.30
    sector_rotation_agent: 0.40
    monetary_agent: 0.30

  # 시장 국면별 동적 가중치
  by_regime:
    bull_market:
      geopolitical_agent: 0.25
      sector_rotation_agent: 0.50
      monetary_agent: 0.25

    bear_market:
      geopolitical_agent: 0.35
      sector_rotation_agent: 0.30
      monetary_agent: 0.35

    volatile:
      geopolitical_agent: 0.40
      sector_rotation_agent: 0.30
      monetary_agent: 0.30

strategy_ensemble:
  growth:
    growth_strategy_agent: 0.70
    cash_management_agent: 0.30

  income:
    income_strategy_agent: 0.80
    cash_management_agent: 0.20
```

### 6. System Configuration (`system.yaml`)

```yaml
system:
  environment: development  # development, production
  log_level: INFO
  max_retries: 3
  timeout: 300  # seconds

  langgraph:
    max_iterations: 3
    checkpoint_enabled: true
    checkpoint_backend: memory  # memory, postgres

  llm:
    provider: anthropic
    model: claude-opus-4
    temperature: 0.3
    max_tokens: 8000

  cache:
    backend: sqlite  # sqlite, redis
    path: /Users/marv/mara/data/cache/cache.db

  output:
    reports_dir: /Users/marv/mara/outputs/reports
    portfolios_dir: /Users/marv/mara/outputs/portfolios
    logs_dir: /Users/marv/mara/outputs/logs

  notifications:
    enabled: true
    email: marv@example.com
    slack_webhook: ${SLACK_WEBHOOK_URL}
```

## 설정 로드 유틸리티

```python
# src/config/loader.py
import yaml
from pathlib import Path
from typing import Dict, Any

class ConfigLoader:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir

    def load_profile(self, profile_name: str) -> Dict[str, Any]:
        path = self.config_dir / "profiles" / f"{profile_name}.yaml"
        return self._load_yaml(path)

    def load_persona(self, agent_name: str) -> Dict[str, Any]:
        path = self.config_dir / "personas" / f"{agent_name}.yaml"
        return self._load_yaml(path)

    def load_data_sources(self) -> Dict[str, Any]:
        path = self.config_dir / "data_sources.yaml"
        return self._load_yaml(path)

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        with open(path, 'r') as f:
            return yaml.safe_load(f)

# 사용 예시
from src.config.loader import ConfigLoader

config = ConfigLoader(Path("src/config"))
growth_profile = config.load_profile("growth")
geo_persona = config.load_persona("geopolitical")
```

## 환경 변수

`.env` 파일로 민감 정보 관리:

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
ALPHA_VANTAGE_API_KEY=...
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
```

`.env.example` 파일로 템플릿 제공:
```bash
# .env.example
ANTHROPIC_API_KEY=your_api_key_here
ALPHA_VANTAGE_API_KEY=your_api_key_here
SLACK_WEBHOOK_URL=your_webhook_url_here
```
