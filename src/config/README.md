# Configuration

프로젝트의 모든 설정을 YAML 파일로 관리하는 폴더입니다.

## 구조

```
config/
├── flows/                   # 워크플로우 설정
│   ├── growth.yaml          # 공격적 투자자 Flow
│   └── income.yaml          # 안정 수익 투자자 Flow
├── personas/                # Agent 페르소나 정의
│   ├── ray_dalio_macro.yaml
│   ├── warren_buffett_value.yaml
│   ├── geopolitical.yaml
│   └── sector_rotation.yaml
├── profiles/                # 사용자 투자 프로필
└── ensemble_weights.yaml    # Agent 간 가중치
```

## 주요 설정 파일

### 1. Flow 설정 (`flows/`)

워크플로우별 Agent 구성 및 가중치 정의

**growth.yaml** - 공격적 투자자 Flow:
- 높은 주식 비중, 섹터 로테이션 적극 활용
- 변동성 허용 범위 높음

**income.yaml** - 안정 수익 투자자 Flow:
- 안정적 배당 + 인플레이션 헤지
- 낮은 변동성 목표, 원금 보존 우선

### 2. Persona 설정 (`personas/`)

각 Perspective Agent의 투자 철학 및 분석 프레임워크 정의

```yaml
# 예시: ray_dalio_macro.yaml
agent_name: ray_dalio_macro
persona: |
  You are Ray Dalio, founder of Bridgewater Associates...

analysis_framework:
  - step: "Analyze the economic machine"
  - step: "Identify the current market regime"
  - step: "Apply All Weather principles"

output_format:
  market_outlook: "BULLISH | NEUTRAL | BEARISH"
  proposals: [...]
  confidence: 0.75
```

### 3. Profile 설정 (`profiles/`)

사용자 투자 프로필 정의 (리스크 허용도, 투자 목표 등)

### 4. Ensemble Weights (`ensemble_weights.yaml`)

Agent 간 가중치 설정

```yaml
# 프로필별 Agent 가중치
strategy_ensemble:
  growth:
    ray_dalio_macro: 0.30
    sector_rotation: 0.40
    geopolitical: 0.20
    monetary: 0.10

  income:
    ray_dalio_macro: 0.40
    sector_rotation: 0.20
    geopolitical: 0.20
    monetary: 0.20
```

## 새 Agent 추가 방법

1. **Persona 파일 생성**: `personas/`에 새 YAML 파일 생성
2. **Flow에 추가**: `flows/{growth,income}.yaml`에 가중치 및 레이어 할당

```yaml
# personas/new_agent.yaml
agent_name: new_agent
persona: |
  Your investment philosophy description...

analysis_framework:
  - step: "Step 1"
  - step: "Step 2"

# flows/growth.yaml에 추가
personas:
  - name: new_agent
    weight: 0.15
    layer: perspective
```

## 환경 변수

`.env` 파일로 민감 정보 관리:

```bash
# 필수
ANTHROPIC_API_KEY=sk-ant-your-api-key-here

# 선택
ALPHA_VANTAGE_API_KEY=your-api-key-here
FRED_API_KEY=your-api-key-here
```

## 설정 로드

```python
from src.config.loader import ConfigLoader
from pathlib import Path

config = ConfigLoader(Path("src/config"))

# 프로필 로드
growth_profile = config.load_profile("growth")

# 페르소나 로드
ray_dalio = config.load_persona("ray_dalio_macro")

# Flow 로드
growth_flow = config.load_flow("growth")
```

## 구현 가이드라인

1. **YAML 형식 유지**
   - 모든 설정은 YAML 파일로 관리
   - 환경별 설정은 환경 변수로 분리

2. **버전 관리**
   - 설정 변경 시 주석으로 변경 이유 명시
   - 중요 설정 변경은 코드 리뷰 필수

3. **민감 정보 분리**
   - API 키 등은 `.env` 파일에 저장
   - `.env.example`로 템플릿 제공
