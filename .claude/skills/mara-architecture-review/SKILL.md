---
name: mara-architecture-review
description: |
  MARA 프로젝트의 6-Layer Agent Pipeline 아키텍처를 점검하고 검증하는 스킬.
  Use when: (1) 새로운 Agent 추가 시 아키텍처 적합성 검증, (2) AGENT.md 품질 리뷰,
  (3) Layer 간 의존성 분석, (4) Input/Output 스키마 검증, (5) 전체 시스템 구조 점검.
  Triggers: "아키텍처 리뷰", "architecture review", "Agent 검증", "시스템 점검",
  "Layer 분석", "AGENT.md 검토", "의존성 분석", "스키마 검증"
---

# MARA Architecture Review Skill

6-Layer Agent Pipeline 아키텍처 점검 및 검증 도구.

## Architecture Overview

```
User Profile → Data → Perspective Agents → Strategy → Validation → Retrospection
                          (병렬)              ↓          ↓
                            ↑            Feedback    Feedback
                       Research ←──────────┘           │
                                                       ↓
                                               Agent 가중치 조정
```

## Review Checklist

### 1. Layer 구조 검증

| Layer | 폴더 | 필수 파일 |
|-------|------|----------|
| Perspective | `src/agents/perspective/` | README.md + 각 Agent 서브폴더/AGENT.md |
| Research | `src/agents/research/` | AGENT.md, README.md |
| Strategy | `src/agents/strategy/` | AGENT.md, README.md |
| Validation | `src/agents/validation/` | AGENT.md, README.md |
| Retrospection | `src/agents/retrospection/` | AGENT.md, README.md |

### 2. AGENT.md 필수 섹션

모든 AGENT.md는 다음 섹션 포함 필수:

```markdown
## Mission        # 한 문장 목표 정의
## Identity       # Agent 페르소나
## Input          # Python dict 형태 입력 스키마
## Output         # Python dict 형태 출력 스키마
## Framework      # Step-by-step 분석 절차
## Rules          # 제약조건 및 가이드라인
## Example        # JSON 형태 예시
```

### 3. Agent 독립성 평가 기준

| 기준 | 설명 | 평가 |
|------|------|------|
| Mission 명확성 | 한 문장으로 목표 정의 가능 | ✅/❌ |
| Input 명세 | Python dict 스키마 명시 | ✅/❌ |
| Output 명세 | Python dict 스키마 명시 | ✅/❌ |
| 독립 실행 가능 | Mock 데이터로 테스트 가능 | ✅/❌ |

### 4. 의존성 규칙

**허용**:
- 단방향 의존성 (위 → 아래)
- State를 통한 간접 통신
- 표준 JSON 인터페이스

**금지**:
- 순환 의존성
- Agent 간 직접 호출
- 하드코딩된 Agent 참조

### 5. 점검 명령

```bash
# Layer별 AGENT.md 존재 확인
find src/agents -name "AGENT.md" | sort

# README.md 존재 확인
find src/agents -name "README.md" | sort

# Perspective Agent 서브폴더 확인
ls -la src/agents/perspective/
```

## Review Process

### Step 1: 폴더 구조 확인

```bash
tree src/agents -L 2
```

예상 구조:
```
src/agents/
├── perspective/
│   ├── README.md
│   ├── geopolitical/AGENT.md
│   ├── sector_rotation/AGENT.md
│   ├── monetary/AGENT.md
│   └── ray_dalio_macro/AGENT.md
├── research/
│   ├── AGENT.md
│   └── README.md
├── strategy/
│   ├── AGENT.md
│   └── README.md
├── validation/
│   ├── AGENT.md
│   └── README.md
└── retrospection/
    ├── AGENT.md
    └── README.md
```

### Step 2: AGENT.md 품질 검사

각 AGENT.md 파일에서 확인:

1. **Mission**: 한 문장, 동사로 시작
2. **Input/Output**: Python dict 또는 Pydantic 스키마
3. **Example**: 실제 JSON 예시 포함
4. **Rules**: 최소 3개 이상 규칙

### Step 3: 의존성 분석

```
DataState ────────────────────────────────────┐
     │                                         │
     ▼                                         │
Perspective Agents (병렬) ←→ Research Agent    │
     │                                         │
     ▼                                         │
Strategy Aggregator                            │
     │                                         │
     ▼                                         │
Validator ◄────────────────────────────────────┘
     │
     ▼
Evaluator
```

순환 의존성 없음 확인 필수.

### Step 4: 평가 리포트 생성

| 평가 항목 | 점수 | 기준 |
|----------|------|------|
| Agent 독립성 | /10 | Mission, Input/Output 명확성 |
| 확장성 | /10 | 새 Agent 추가 용이성 |
| 유지보수성 | /10 | 문서화, 에러 처리 |
| 테스트 용이성 | /10 | Mock 데이터 테스트 가능 |
| 문서화 | /10 | AGENT.md 품질 |

## Common Issues

### Issue 1: Mission 불명확
**문제**: "다양한 분석을 수행한다"
**해결**: "제안된 포트폴리오의 리스크 조건 충족 여부를 검증한다"

### Issue 2: Input/Output 스키마 누락
**문제**: 자연어로만 설명
**해결**: Python dict 또는 Pydantic 형태로 명세

### Issue 3: 순환 의존성
**문제**: Agent A → Agent B → Agent A
**해결**: State를 통한 간접 통신으로 변경

## Reference Files

- Architecture details: [references/architecture.md](references/architecture.md)
- Agent list: [references/agents.md](references/agents.md)
