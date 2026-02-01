# Perspective Agents

다양한 관점에서 시장을 분석하고 리밸런싱을 제안하는 Agent 레이어입니다. Persona 기반으로 동적 생성됩니다.

## 책임 (Responsibilities)

- 다양한 관점(지정학, 섹터, 매크로, 금리)에서 병렬 분석
- Research Agent와의 multi-hop 소통 (최대 3회)으로 심층 분석
- Price Tool을 통해 시장 가격 정보 조회
- 각 Agent가 독립적으로 리밸런싱 제안 수행

## 구조

```
perspective/
├── README.md                    # Layer 설명 (현재 파일)
├── base.py                      # BasePerspectiveAgent 추상 클래스
├── factory.py                   # Persona YAML → Agent 인스턴스 생성
│
├── geopolitical/                # Geopolitical Agent
│   └── AGENT.md                 # Agent 명세
│
├── sector_rotation/             # Sector Rotation Agent
│   └── AGENT.md                 # Agent 명세
│
├── monetary/                    # Monetary Agent
│   └── AGENT.md                 # Agent 명세
│
└── ray_dalio_macro/             # Ray Dalio Macro Agent
    └── AGENT.md                 # Agent 명세
```

## Agents

| Agent | 폴더 | 관점 | 분석 포커스 |
|-------|------|------|-------------|
| Geopolitical | [geopolitical/](geopolitical/AGENT.md) | 지정학적 리스크 | 미중 관계, 공급망 재편, 에너지 안보 |
| Sector Rotation | [sector_rotation/](sector_rotation/AGENT.md) | 섹터 로테이션 | 경기 사이클, 섹터별 모멘텀, 기술 혁신 |
| Monetary | [monetary/](monetary/AGENT.md) | 통화정책 및 유동성 | 중앙은행 정책, 금리 경로, 유동성 상황 |
| Ray Dalio Macro | [ray_dalio_macro/](ray_dalio_macro/AGENT.md) | All Weather | 경제 레짐 분석, 리스크 패리티 |

## Persona 기반 Agent 시스템

Agent는 YAML 설정 파일에서 동적으로 생성됩니다:

- **Config files**: `src/config/personas/*.yaml` - 분석 프레임워크 및 출력 형식 정의
- **Flow configs**: `src/config/flows/{growth,income}.yaml` - 어떤 페르소나를 어떤 가중치로 사용할지 정의

## Research Agent와의 Multi-hop 통신

Perspective Agent는 Research Agent와 최대 3회까지 반복 소통하여 심층 분석을 수행합니다.

```
Perspective Agent → "AI 반도체 관련 최신 동향 조사" → Research Agent
Research Agent → 조사 결과 반환 → Perspective Agent
Perspective Agent → "추가로 NVIDIA의 경쟁사 동향 조사" → Research Agent
...
```

### Loop 종료 조건

- **조기 종료**: 충분한 정보 확보 시
- **최대 반복**: 3회 도달 시 현재까지 수집된 정보로 진행
- **실패 처리**: Research Agent 응답 실패 시 자체 분석으로 fallback

## 공통 Output Schema

모든 Perspective Agent는 동일한 출력 형식을 따릅니다:

```python
class PerspectiveOutput(BaseModel):
    """Perspective Agent 전체 출력"""
    agent_id: str
    timestamp: datetime
    market_outlook: Literal["BULLISH", "NEUTRAL", "BEARISH"]
    confidence: float
    proposals: list[RebalanceProposal]
    risk_assessment: str
    research_queries: list[str]
```

## 에러 핸들링

| 컴포넌트 | 재시도 횟수 | 백오프 전략 | Timeout |
|----------|-------------|-------------|---------|
| LLM API (Anthropic) | 3회 | Exponential (1s, 2s, 4s) | 60s |
| Research Agent | 2회 | Linear (1s, 2s) | 20s |

### Fallback 전략

- **Research Agent 실패**: Perspective Agent가 자체 분석으로 진행
- **개별 Perspective Agent 실패**: 해당 Agent 제외하고 나머지로 종합 (최소 2개 Agent 필요)

## 새 Agent 추가 방법

1. `src/agents/perspective/`에 새 폴더 생성 (예: `warren_buffett/`)
2. 해당 폴더에 `AGENT.md` 작성
3. `src/config/personas/`에 페르소나 YAML 파일 생성
4. `src/config/flows/{growth,income}.yaml`에 가중치 및 레이어 할당

### 예시: 새로운 Agent 추가

```
# 1. 폴더 생성
src/agents/perspective/warren_buffett/AGENT.md

# 2. Persona 설정
src/config/personas/warren_buffett_value.yaml

# 3. Flow 설정에 추가
src/config/flows/growth.yaml
```
