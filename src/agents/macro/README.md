# Macro Insight Layer

거시 경제 분석을 담당하는 Multi-Agent Ensemble 레이어입니다.

## 책임 (Responsibilities)

- 다양한 관점에서 거시 경제 분석
- 시장 국면(Market Regime) 판단
- 섹터별 전망 및 투자 테마 도출
- Ensemble 방식으로 다수의 의견 종합

## Agent 구조

### 1. Geopolitical Agent (`geopolitical_agent.py`)
**관점**: 지정학적 리스크 및 국제 관계

- 미중 관계 분석 (무역 전쟁, 기술 패권 경쟁)
- 공급망 재편 (리쇼어링, 프렌드쇼어링)
- 에너지 안보 (러시아-우크라이나, 중동)
- 지역별 투자 매력도 평가

**출력**:
```json
{
  "regime": "geopolitical_tension_high",
  "favorable_regions": ["US", "India"],
  "unfavorable_regions": ["China"],
  "themes": ["supply_chain_resilience", "defense_spending"]
}
```

### 2. Sector Rotation Agent (`sector_rotation_agent.py`)
**관점**: 경기 사이클 및 섹터 로테이션

- 경기 사이클 단계 판단 (초기, 중기, 후기, 침체)
- 섹터별 모멘텀 분석 (반도체, AI, 헬스케어, 에너지 등)
- 기술 혁신 트렌드 (AI 시대, 클라우드 전환)
- Value vs Growth 관점

**출력**:
```json
{
  "cycle_stage": "mid_cycle",
  "overweight_sectors": ["technology", "healthcare"],
  "underweight_sectors": ["utilities", "consumer_staples"],
  "themes": ["ai_infrastructure", "aging_population"]
}
```

### 3. Monetary Policy Agent (`monetary_agent.py`)
**관점**: 통화정책 및 유동성

- 중앙은행 정책 분석 (Fed, ECB, BoJ)
- 금리 경로 예측 (인상/인하 사이클)
- 유동성 상황 분석 (QE/QT, M2 증가율)
- 채권 vs 주식 매력도

**출력**:
```json
{
  "policy_stance": "neutral_to_easing",
  "rate_forecast": {"2025Q1": 4.5, "2025Q2": 4.25},
  "liquidity": "improving",
  "asset_preference": "equities_over_bonds"
}
```

## Ensemble Logic

각 Agent의 출력을 종합하여 최종 Market State를 생성합니다.

### `ensemble.py`
- 각 Agent의 신뢰도(confidence) 가중치 적용
- 상충되는 의견 조정 (예: Geopolitical은 부정적, Monetary는 긍정적)
- 최종 Market Regime 결정 (Bull, Bear, Sideways, Volatile)

```python
def ensemble_macro_insights(
    geo_output: dict,
    sector_output: dict,
    monetary_output: dict,
    weights: dict = {"geo": 0.3, "sector": 0.4, "monetary": 0.3}
) -> MarketState:
    """
    다수의 Macro Agent 출력을 종합하여 MarketState 생성
    """
    pass
```

## 구현 가이드라인

1. **각 Agent는 독립적으로 실행 가능**
   - 다른 Agent의 출력에 의존하지 않음
   - 병렬 실행으로 성능 최적화

2. **Persona 기반 Prompting**
   - `config/personas/` 폴더에 각 Agent의 페르소나 정의
   - 예: Geopolitical Agent는 "전직 CIA 분석가" 페르소나

3. **근거 제시 필수**
   - 모든 판단에 대해 인용 출처 명시 (뉴스 링크, 리포트 페이지)
   - Critic Layer에서 검증 가능하도록

4. **설정 가능한 민감도**
   - Conservative vs Aggressive 모드
   - 예: Conservative는 확실한 시그널만 반영

## 출력 스키마

```python
@dataclass
class MarketState:
    regime: str  # "bull", "bear", "sideways", "volatile"
    confidence: float  # 0.0 ~ 1.0
    sector_outlook: Dict[str, float]  # sector -> expected return
    themes: List[str]  # 투자 테마
    risks: List[str]  # 주요 리스크
    citations: List[str]  # 근거 자료
    timestamp: datetime
```
