# MARA Flow Definitions

## Overview

MARA는 투자자 상황에 따라 **두 가지 명확한 Flow**를 제공합니다.

## Flow 1: Growth Flow (성장 극대화)

**대상**: 근로소득이 있는 공격적 투자자 (예: 나)

**목표**:
- 수익 극대화
- 섹터 로테이션 활용
- 높은 변동성 허용 (Max DD 35%)

**Flow Diagram**:

```
┌─────────────────────────────────────────────────────────────────┐
│  Growth Flow                                                    │
└─────────────────────────────────────────────────────────────────┘

Input: current_portfolio.yaml (현재 보유 ETF, 현금)
       account: 총 자산 1억, 월 적립 500만원

  ↓

[0. Portfolio Input Layer]
  - Parse current holdings
  - Calculate current allocation
  - Load growth profile config

  ↓

[1. Data Layer]
  - Collect news (Financial Times, Bloomberg)
  - Collect expert reports (PDF parsing)
  - Collect price data (yfinance)
  - Collect economic indicators (FRED)

  ↓

[2. Macro Insight Layer] - 3 Agents in Parallel
  ├─ Geopolitical Agent
  ├─ Sector Rotation Agent  ← Most weighted (0.40)
  └─ Monetary Policy Agent
  → Ensemble → Market Regime + Sector Outlook

  ↓

[3. Research Layer] - 2 Agents
  ├─ Stock Screener Agent (개별 종목 발굴 - Optional)
  └─ Theme Investment Agent (AI, 에너지 전환 등)
  → Discovered Opportunities

  ↓

[4. Strategy Design Layer] - 3 Agents
  ├─ Growth Strategy Agent  ← Primary
  │   → 3 Strategy Candidates (Aggressive, Balanced, Defensive)
  ├─ Cash Management Agent
  │   → Dynamic cash ratio (5-25%)
  └─ Tax Optimization Agent (Optional)
  → 3 Strategy Candidates

  ↓

[5. Rebalancing Layer] - 3 Methods
  ├─ Threshold-based (5% 괴리)
  ├─ Cash-flow based (월급 활용) ← Preferred for Growth
  └─ Opportunistic (VIX spike)
  → 3 Rebalancing Plans

  ↓

[6. Validation Layer]
  - Backtest each strategy (10 years)
  - Calculate risk metrics (Sharpe, Max DD, VaR)
  - Stress test (2008, 2020, 2022)
  - Transaction cost analysis
  → Validation Report

  ↓

[7. Critic Layer]
  - Compare 3 strategies
  - Check consistency (Macro ↔ Strategy)
  - Select best strategy (or flag for user choice)
  - Generate report (Markdown)
  → Final Recommendation

  ↓

Output:
  - outputs/portfolios/2025-01-17_growth_recommendation.json
  - outputs/reports/2025-01-17_growth_report.md
  - DB: predictions table (for retrospection)
```

**Key Characteristics**:
- **Research Layer**: Enabled (신규 종목 발굴)
- **Strategy Candidates**: 3개 (Aggressive, Balanced, Defensive)
- **Primary Agent**: Growth Strategy Agent
- **Rebalancing**: Cash-flow based 우선 (월급으로 조정)
- **Focus**: 수익 극대화, 섹터 로테이션

---

## Flow 2: Income Flow (현금흐름 창출)

**대상**: 은퇴 자산 보호 및 현금흐름 필요 (예: 부모님)

**목표**:
- 매월 안정적 현금흐름 (총 자산의 0.25% = 연 3%)
- 원금 보존 (Max DD 20%)
- 인플레이션 헤지

**Flow Diagram**:

```
┌─────────────────────────────────────────────────────────────────┐
│  Income Flow                                                    │
└─────────────────────────────────────────────────────────────────┘

Input: current_portfolio.yaml (현재 보유 채권, 배당주, REIT)
       account: 총 자산 20억, 월 필요 현금 500만원 (연 3%)

  ↓

[0. Portfolio Input Layer]
  - Parse current holdings
  - Calculate current yield
  - Load income profile config

  ↓

[1. Data Layer]
  - Collect news (focus: bond market, dividend stocks)
  - Collect expert reports
  - Collect price + dividend data
  - Collect inflation indicators (CPI, TIPS spread)

  ↓

[2. Macro Insight Layer] - 3 Agents in Parallel
  ├─ Geopolitical Agent
  ├─ Monetary Policy Agent  ← Most weighted (0.40)
  └─ Sector Rotation Agent (defensive sectors)
  → Ensemble → Market Regime + Risk Assessment

  ↓

[3. Research Layer] - 2 Agents (Different Focus)
  ├─ Alternative Asset Agent (REITs, TIPS, Municipal Bonds)
  └─ Dividend Screener Agent (High-yield, stable dividend stocks)
  → Discovered Opportunities (income-focused)

  ↓

[4. Strategy Design Layer] - 3 Agents
  ├─ Income Strategy Agent  ← Primary
  │   → 3 Strategy Candidates (Conservative, Balanced, Growth-Income)
  ├─ Cash Management Agent
  │   → Higher cash ratio (15-25% for liquidity)
  └─ Inflation Hedge Agent (NEW)
      → TIPS, Gold, I-Bonds allocation
  → 3 Strategy Candidates

  ↓

[5. Rebalancing Layer] - 2 Methods (Simpler)
  ├─ Calendar-based (분기별)  ← Preferred for Income
  └─ Threshold-based (3% 괴리, tighter than Growth)
  → 2 Rebalancing Plans

  ↓

[6. Validation Layer]
  - Backtest (focus on downside protection)
  - Calculate risk metrics (특히 Max DD, CVaR)
  - Stress test (recession scenarios)
  - Yield stability analysis (NEW)
  → Validation Report

  ↓

[7. Critic Layer]
  - Check if required yield (3%) is achievable
  - Verify Max DD < 20%
  - Ensure inflation hedge (40%+)
  - Generate report with monthly distribution plan
  → Final Recommendation

  ↓

Output:
  - outputs/portfolios/2025-01-17_income_recommendation.json
  - outputs/reports/2025-01-17_income_report.md
    (includes monthly cash flow plan)
  - DB: predictions table (for retrospection)
```

**Key Characteristics**:
- **Research Layer**: Alternative assets (REITs, TIPS, muni bonds)
- **Strategy Candidates**: 3개 (Conservative, Balanced, Growth-Income)
- **Primary Agent**: Income Strategy Agent
- **Rebalancing**: Calendar-based 우선 (분기별, 예측 가능)
- **Focus**: 안정적 현금흐름, 원금 보존, 인플레이션 헤지

---

## Flow Comparison

| Aspect | Growth Flow | Income Flow |
|--------|-------------|-------------|
| **Target User** | 근로소득 있는 젊은 투자자 | 은퇴자, 안정적 현금 필요 |
| **Primary Goal** | 수익 극대화 | 현금흐름 + 원금 보존 |
| **Risk Tolerance** | High (Max DD 35%) | Low (Max DD 20%) |
| **Research Focus** | 성장 섹터, 테마 | 배당주, REIT, 채권 |
| **Strategy Agent** | Growth Strategy | Income Strategy |
| **Rebalancing** | Cash-flow based (월급) | Calendar-based (분기) |
| **Equity Allocation** | 70-90% | 30-50% |
| **Cash Ratio** | 5-25% | 15-25% |
| **Macro Weight** | Sector Rotation (0.40) | Monetary Policy (0.40) |

---

## Agent Selection by Flow

### Growth Flow Agents

**Macro Layer**:
- Geopolitical Agent (weight: 0.30)
- **Sector Rotation Agent (weight: 0.40)** ← 높은 가중치
- Monetary Policy Agent (weight: 0.30)

**Research Layer**:
- Stock Screener Agent (optional)
- Theme Investment Agent (AI, 에너지 전환)

**Strategy Layer**:
- **Growth Strategy Agent** (primary)
- Cash Management Agent
- Tax Optimization Agent (optional)

**Rebalancing Layer**:
- Threshold-based (5%)
- **Cash-flow based** (preferred)
- Opportunistic

---

### Income Flow Agents

**Macro Layer**:
- Geopolitical Agent (weight: 0.30)
- Sector Rotation Agent (weight: 0.30, defensive focus)
- **Monetary Policy Agent (weight: 0.40)** ← 높은 가중치 (금리 중요)

**Research Layer**:
- Alternative Asset Agent (REITs, TIPS, muni bonds)
- Dividend Screener Agent

**Strategy Layer**:
- **Income Strategy Agent** (primary)
- Cash Management Agent (higher cash target)
- Inflation Hedge Agent

**Rebalancing Layer**:
- **Calendar-based (분기별)** (preferred)
- Threshold-based (3%, tighter)

---

## Flow Execution

```bash
# Growth Flow 실행
python -m src.orchestration.cli run --flow growth --user marv

# Income Flow 실행
python -m src.orchestration.cli run --flow income --user parents

# 또는 profile로 실행 (profile이 flow를 결정)
python -m src.orchestration.cli run --profile growth
python -m src.orchestration.cli run --profile income
```

---

## Flow Configuration Location

```
config/
├── flows/
│   ├── growth.yaml      # Growth Flow 정의
│   └── income.yaml      # Income Flow 정의
├── profiles/
│   ├── growth.yaml      # Growth 투자자 프로필
│   └── income.yaml      # Income 투자자 프로필
└── personas/
    ├── geopolitical.yaml
    ├── sector_rotation.yaml
    └── ...
```

---

## Next Steps

1. ✅ Flow 정의 완료
2. 🔄 Flow별 Config 상세 설계
3. 🔄 State 영속성 설계 (DB 스키마)
