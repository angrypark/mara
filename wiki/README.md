# MARA Wiki

MARA (Macro Asset Rebalance Agent) 시스템의 지식 저장소입니다.

## 구조

### Market Data (`_shared/`)

모든 유저가 공유하는 시장 데이터와 페르소나 분석 이력입니다.

- **market/** — Data Agent가 수집한 거시경제 지표, 섹터 동향, 주요 이벤트
- **personas/** — Perspective Agent 실행 결과 축적 (config YAML의 정적 정의와 별개)

### Users (`users/{user_id}/`)

유저별 분석 결과와 포트폴리오 이력입니다.

| 경로 | 담당 Agent | 내용 |
|------|-----------|------|
| `profile.md` | User Profile Agent | 포트폴리오, 목표, 제약조건, Agent 가중치 |
| `perspective/*.md` | Perspective Agents | 4명 투자자 관점별 분석 결과 |
| `validation/latest.md` | Validation Agent | 최신 리스크 검증 결과 |
| `strategy/current.md` | Strategy Agent | 최신 전략 보고서 |
| `strategy/history/*.md` | Strategy Agent | 날짜별 전략 아카이브 |
| `retrospection/*.md` | Retrospection Agent | 월별 회고 |

## Perspective Agents

4명의 전설적 투자자 관점에서 독립적으로 분석합니다.

| Agent | 핵심 질문 | 고유 분석 |
|-------|----------|----------|
| **George Soros** | 시장이 무엇을 잘못 읽고 있는가? | 반사성 레짐, 시장 괴리, 피드백 루프 |
| **Paul Tudor Jones** | 무엇이 잘못될 수 있는가? | 리스크 레짐, 비대칭 기회, 테일 리스크 |
| **Ray Dalio** | 지금 경제 사이클의 어디에 있는가? | 경제 레짐, 부채 사이클, All Weather 점검 |
| **Stanley Druckenmiller** | 어디에 얼마나 실을 것인가? | 확신도 레짐, 집중 베팅, 미반영 매크로 변화 |

## 규칙

- 덮어쓰지 않고 날짜와 함께 누적한다
- 오래된 정보는 `[outdated]` 플래그를 단다
- 모든 분석 결과에 출처를 명시한다
- 각 Agent는 자기 영역만 관리한다

## 로컬 실행

```bash
# 실시간 반영 (live-reload) — 권장
npx live-server wiki/

# Docsify CLI
npx docsify-cli serve wiki/

# Python HTTP 서버
uv run python -m http.server -d wiki/ 3000
```
