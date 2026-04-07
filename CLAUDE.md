# CLAUDE.md

This file provides guidance to Claude Code when working with this project.

## Project Overview

MARA (Macro Asset Rebalance Agent)는 AI 기반 포트폴리오 리밸런싱 시스템이다. Telegram Bot(Mara1Bot)을 통해 사용자 명령을 받아 여러 Sub Agent를 순차 실행하고, 최종 보고서를 생성한다.

## Architecture

### Telegram → MaraBot → Sub Agents

```
사용자 (Telegram @Mara1Bot)
  ↓
MaraBot (AGENT.md 기반 오케스트레이터)
  ├── 1. User Profile Agent    → 프로필 로드 또는 저장
  ├── 2. Data Agent            → 시장 데이터 수집 + 리서치
  ├── 3. Perspective Agents    → 관점별 분석 (4개 병렬 가능, 상호 독립)
  │       ├── George Soros          ─┐
  │       ├── Paul Tudor Jones       │ 의존 관계 없음 → 병렬 실행 권장
  │       ├── Ray Dalio              │
  │       └── Stanley Druckenmiller ─┘
  ├── 4. Validation Agent      → 리스크 검증
  └── 5. Strategy Agent        → 최종 보고서 작성
  
  (월 1회) Retrospection Agent  → 성과 회고
```

### Sub Agent 이중 구조

**Source of Truth는 `src/agents/*/AGENT.md`**. `.claude/agents/`는 thin wrapper다.

| 계층 | 역할 | 내용 |
|------|------|------|
| `.claude/agents/*.md` | **실행 정의** (thin wrapper) | 모델 지정, 도구 허용 목록, AGENT.md 경로 참조만 |
| `src/agents/*/AGENT.md` | **도메인 로직** (source of truth) | 분석 프레임워크, 출력 형식, wiki 규칙, 판단 기준 |

| Agent | Wrapper | Source of Truth | Model |
|-------|---------|----------------|-------|
| User Profile | .claude/agents/user-profile.md | src/agents/user_profile/AGENT.md | Haiku |
| Data | .claude/agents/data-collector.md | src/agents/data/AGENT.md | Sonnet |
| Perspective | .claude/agents/perspective-analyst.md | src/agents/perspective/*/AGENT.md | Sonnet |
| Validation | .claude/agents/risk-validator.md | src/agents/validation/AGENT.md | Sonnet |
| Strategy | .claude/agents/strategy-synthesizer.md | src/agents/strategy/AGENT.md | Sonnet |
| Retrospection | .claude/agents/retrospection-evaluator.md | src/agents/retrospection/AGENT.md | Sonnet |

## Wiki (지식 축적)

Karpathy LLM Wiki 패턴 적용. 공통 데이터와 유저별 데이터를 분리하여 관리한다. Docsify로 웹 브라우징 가능.

```
wiki/
├── index.html              # Docsify SPA
├── _sidebar.md             # 글로벌 네비게이션
├── README.md               # Wiki 홈페이지
│
├── _shared/                        # 유저 무관 공통 데이터
│   ├── market/
│   │   ├── macro.md                # Data Agent 갱신
│   │   ├── sectors.md              # 섹터 데이터
│   │   └── events.md              # 주요 이벤트 타임라인
│   └── personas/
│       └── ray_dalio.md            # 페르소나 Agent 실행 결과 축적
│
└── users/
    └── {user_id}/                  # Telegram user_id
        ├── profile.md              # 프로필 + 포트폴리오 + 제약조건 + Agent 가중치
        ├── watchlist.md            # 관심 종목
        ├── perspective/
        │   ├── george_soros.md
        │   ├── paul_tudor_jones.md
        │   ├── ray_dalio.md
        │   └── stanley_druckenmiller.md
        ├── validation/
        │   └── latest.md
        ├── strategy/
        │   ├── current.md          # 최신 전략 보고서
        │   └── history/
        │       └── {YYYY-MM-DD}.md # 날짜별 아카이브
        └── retrospection/
            └── {YYYY-MM}.md        # 월별 회고
```

### Wiki 조회

```bash
# 실시간 반영 (live-reload) — 권장
npx live-server wiki/

# Docsify CLI (live-reload 불안정)
npx docsify-cli serve wiki/

# 단순 정적 서버 (새로고침 수동)
uv run python -m http.server -d wiki/ 3000
```

### Frontmatter 규약

모든 wiki 마크다운은 YAML frontmatter를 포함해야 한다:

```markdown
---
title: George Soros Analysis
date: 2026-04-06
agent: perspective_george_soros
user: marv
tags: [perspective, george_soros]
---
```

### Config vs Wiki Persona

| Config (`src/config/personas/*.yaml`) | Wiki (`wiki/_shared/personas/*.md`) |
|--------------------------------------|-------------------------------------|
| 정적 정의: 투자 철학, 목표 배분 | 런타임 결과: 레짐 판단 이력, 분석 축적 |

## Config Files

- `src/config/flows/growth.yaml` — 공격적 투자자 Flow (Agent 가중치, 제약 조건)
- `src/config/flows/income.yaml` — 안정 수익 투자자 Flow
- `src/config/personas/george_soros.yaml` — George Soros 반사성 이론 전략 설정
- `src/config/personas/paul_tudor_jones.yaml` — Paul Tudor Jones 방어 우선 매크로 설정
- `src/config/personas/ray_dalio.yaml` — Ray Dalio All Weather 전략 설정
- `src/config/personas/stanley_druckenmiller.yaml` — Stanley Druckenmiller 집중 베팅 매크로 설정

### Config 소비 경로

```
flows/*.yaml
  → MaraBot이 읽음 → agent_weights, constraints를 Perspective/Validation/Strategy Agent에 전달

personas/*.yaml
  → Perspective Agent가 직접 읽음 → 분석 프레임워크, 레짐 분류, 목표 배분 기준으로 사용
  → 예: Ray Dalio Agent가 ray_dalio.yaml의 target_allocations을 참조하여 레짐별 배분 결정
  → 예: George Soros Agent가 george_soros.yaml의 divergence 기준으로 괴리 분석
```

## Output Validation

각 Agent의 출력은 `src/contracts/` YAML 스키마 대비 자동 검증된다.

### 구조

```
src/contracts/           # Agent별 출력 스키마 (YAML)
├── user_profile.yaml
├── data_summary.yaml
├── perspective_common.yaml    # 4개 Perspective 공통 규약
├── perspective_george_soros.yaml
├── perspective_paul_tudor_jones.yaml
├── perspective_ray_dalio.yaml
├── perspective_stanley_druckenmiller.yaml
├── validation_report.yaml
├── strategy_report.yaml
└── retrospection_report.yaml

src/validation/
└── validate.py          # Python validator (stdlib only)
```

### 사용법

```bash
uv run python src/validation/validate.py <agent_name> <output_file>
# 예: uv run python src/validation/validate.py perspective_geopolitical outputs/intermediate/2026-04-06_growth/03_perspective_geopolitical.md
```

- Exit 0 = PASS, Exit 1 = FAIL, Exit 2 = ERROR
- JSON 출력: `{ "status": "PASS|FAIL", "errors": [...], "warnings": [...] }`
- Perspective contract는 `perspective_common.yaml`을 상속 (`inherits` 키)

### 중간 결과 저장

파이프라인 실행 시 모든 Agent 출력을 `outputs/intermediate/{date}_{profile}/`에 저장한다.
상세 경로와 검증 프로세스는 `AGENT.md`의 Output Validation 섹션을 참조.

## Project Structure

```
mara/
├── AGENT.md                    # MaraBot 메인 오케스트레이터 지침
├── CLAUDE.md                   # 이 파일
├── README.md                   # 프로젝트 소개
├── TECHSPEC.md                 # 원본 기획 배경
├── .claude/agents/             # Claude Code subagent 정의 (6개)
├── src/agents/                 # Agent별 상세 AGENT.md
├── src/config/                 # Flow, Persona, Profile YAML 설정
├── src/contracts/              # Agent별 출력 스키마 (YAML)
├── src/validation/             # 출력 검증 스크립트
├── wiki/                       # Agent 지식 축적 (_shared/ + users/{uid}/, Docsify 서빙)
└── outputs/                    # 검증 중간 결과 (intermediate/)
```

## Rules

- 한국어로 대화한다.
- 코드 수정 대신 AGENT.md와 config 파일을 통해 Agent 동작을 정의한다.
- 새 기능은 MCP skill로 추가한다.
- wiki 내용은 덮어쓰지 않고 날짜와 함께 누적한다.
- 모든 분석 결과에 출처를 명시한다.

## Error Handling

| 실패 지점 | 동작 | 파이프라인 |
|-----------|------|-----------|
| Data Agent 수집 실패 | wiki/_shared/market/ 캐시된 최근 데이터 사용, stale 경고 | 계속 진행 |
| 개별 Perspective Agent 실패 | 해당 Agent 건너뛰고 나머지로 진행 | 최소 2개 성공 필요 |
| 전체 Perspective < 2개 | 파이프라인 중단, 사용자에게 알림 | 중단 |
| Validation Agent 실패 | 검증 없이 Strategy에 경고 표시 | 계속 (validation_skipped) |
| Strategy Agent 실패 | Perspective 결과를 요약하여 직접 전달 | 대체 |

## Retrospection 트리거

- **수동**: Telegram에서 "회고" 명령
- **자동**: Claude Code의 `/schedule`로 크론 등록 가능 (예: 매월 15일)
  ```
  /schedule "매월 15일 retrospection 실행" --cron "0 9 15 * *"
  ```

## 데이터 생명주기

| 디렉토리 | 보관 정책 | 비고 |
|----------|----------|------|
| `outputs/intermediate/` | 최근 5회 실행분 보관 | 디버깅용 |
| `wiki/_shared/` | 전체 보관 (누적) | 오래된 정보는 `[outdated]` 플래그 |
| `wiki/users/*/strategy/history/` | 전체 보관 | 날짜별 개별 파일 |
| `wiki/users/*/retrospection/` | 전체 보관 | 월별 개별 파일 |

## Strategy 복구 전략

`wiki/users/{user_id}/strategy/current.md` 업데이트 전 반드시 기존 내용을 `wiki/users/{user_id}/strategy/history/{date}.md`에 아카이브한다. 오작동 시 `history/`의 최신 파일로 `current.md`를 복원한다.

## Environment

```
ANTHROPIC_API_KEY=sk-ant-...    # 필수
TELEGRAM_BOT_TOKEN=...          # Telegram 채널용
```
