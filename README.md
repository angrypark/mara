# MARA: Macro Asset Rebalance Agent

AI 기반 거시 경제 분석 및 개인 맞춤형 포트폴리오 리밸런싱 시스템

## Overview

MARA는 Telegram Bot을 통해 사용자의 명령을 받아 여러 AI Agent를 순차 실행하고, 포트폴리오 리밸런싱 보고서를 생성합니다. 각 Agent는 자신의 전문 분야에서 독립적으로 분석하고, 결과를 wiki에 축적하여 시간이 지날수록 더 정확한 분석을 제공합니다.

## Architecture

```
Telegram (@Mara1Bot)
  ↓
MaraBot (메인 오케스트레이터)
  ├── User Profile Agent    → 투자 프로필 로드
  ├── Data Agent            → 시장 데이터 수집 + 리서치
  ├── Perspective Agents    → 4명의 전설적 투자자 관점 분석
  │   ├── George Soros          (반사성 이론 — 시장 괴리 포착)
  │   ├── Paul Tudor Jones      (방어 우선 매크로 — 리스크 관리)
  │   ├── Ray Dalio             (All Weather — 경제 사이클)
  │   └── Stanley Druckenmiller (집중 베팅 매크로 — 확신도 기반)
  ├── Validation Agent      → 리스크 검증
  └── Strategy Agent        → 최종 보고서 작성

  (월 1회)
  └── Retrospection Agent   → 예측 vs 실제 비교, Agent 성과 회고
```

## Key Features

- **Multi-Agent Pipeline**: 6단계 Agent 파이프라인이 순차 실행
- **Perspective-Based Analysis**: Soros(반사성), PTJ(방어), Dalio(사이클), Druckenmiller(집중) 4명의 전설적 투자자 관점의 독립 분석
- **Knowledge Accumulation**: LLM Wiki 패턴으로 분석 결과를 wiki에 누적
- **Risk Validation**: 모든 제안은 리스크 검증을 거침
- **Self-Learning**: Retrospection을 통한 Agent 성과 평가 및 개선
- **Two Investment Flows**: 공격적(Growth) / 안정(Income) 프로필 지원
- **Telegram Integration**: 모바일에서 언제든 분석 요청 및 결과 확인

## Quick Start

### 1. 요구사항

- [Claude Code](https://claude.ai/code) (v2.1.80+)
- [Bun](https://bun.sh) (Telegram 채널 플러그인용)
- claude.ai 계정 로그인

### 2. Telegram Bot 설정

```bash
# Claude Code에서 Telegram 플러그인 설치
/plugin install telegram@claude-plugins-official
/reload-plugins

# Bot 토큰 설정
/telegram:configure <YOUR_BOT_TOKEN>

# 채널 활성화하여 시작
claude --channels plugin:telegram@claude-plugins-official
```

### 3. 사용

Telegram에서 @Mara1Bot에 메시지:

| 명령 | 설명 |
|------|------|
| "growth 프로필 리밸런싱 해줘" | 전체 파이프라인 실행 |
| "내 포트폴리오 보여줘" | 현재 프로필 조회 |
| "현재 시장 상황 알려줘" | Data Agent만 실행 |
| "지난달 결과 회고해줘" | Retrospection 실행 |

## Project Structure

```
mara/
├── AGENT.md                    # MaraBot 메인 동작 지침
├── CLAUDE.md                   # Claude Code 가이드
├── TECHSPEC.md                 # 기획 배경
├── .claude/agents/             # Sub Agent 정의 (6개)
├── src/
│   ├── agents/                 # Agent별 상세 AGENT.md
│   │   ├── user_profile/
│   │   ├── data/
│   │   ├── perspective/        # 4개 관점 Agent
│   │   ├── validation/
│   │   ├── strategy/
│   │   └── retrospection/
│   └── config/                 # Flow, Persona 설정
├── wiki/                       # 지식 축적 (LLM Wiki)
├── outputs/                    # 보고서, 포트폴리오
└── docs/                       # 문서
```

## Disclaimer

본 프로젝트는 교육 및 연구 목적으로 개발되었습니다. 실제 투자 결정은 개인의 책임 하에 이루어져야 합니다.
