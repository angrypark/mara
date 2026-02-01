# MARA Agent Reference

## Agent 목록

### Perspective Agents

| Agent | AGENT.md 위치 | Mission |
|-------|--------------|---------|
| Geopolitical | `src/agents/perspective/geopolitical/AGENT.md` | 지정학적 이벤트가 시장에 미치는 영향 분석 및 리밸런싱 제안 |
| Sector Rotation | `src/agents/perspective/sector_rotation/AGENT.md` | 경기 사이클에 따른 최적 섹터 배분 분석 및 제안 |
| Monetary | `src/agents/perspective/monetary/AGENT.md` | 통화정책 변화가 자산군에 미치는 영향 분석 및 제안 |
| Ray Dalio Macro | `src/agents/perspective/ray_dalio_macro/AGENT.md` | All Weather 전략 기반 거시경제 분석 및 제안 |

### Other Agents

| Agent | AGENT.md 위치 | Mission |
|-------|--------------|---------|
| Research | `src/agents/research/AGENT.md` | Perspective Agent 요청에 따라 심층 조사 수행 |
| Strategy Aggregator | `src/agents/strategy/AGENT.md` | 여러 Perspective Agent 제안을 가중치 기반으로 종합 |
| Validator | `src/agents/validation/AGENT.md` | 포트폴리오가 리스크 허용 범위 내에서 목표 달성 가능한지 검증 |
| Evaluator | `src/agents/retrospection/AGENT.md` | 과거 예측의 정확도 평가 및 Agent 가중치 조정 제안 |

## AGENT.md 표준 구조

```markdown
# [Agent Name]

## Mission
한 문장으로 Agent의 핵심 목표 정의 (동사로 시작)

## Identity
Agent의 페르소나 및 전문 분야 정의

## Input
Python dict 형태의 입력 스키마
- 각 필드의 타입과 의미 설명
- 필수/선택 필드 구분

## Output
Python dict 형태의 출력 스키마
- 각 필드의 타입과 의미 설명
- 표준 인터페이스 준수

## Framework
Step-by-step 분석/처리 절차
- Step 1: ...
- Step 2: ...
- Step N: ...

## Rules
1. 규칙 1
2. 규칙 2
...

## Example
실제 Input/Output JSON 예시
```

## Agent 간 통신

### Perspective Agent ↔ Research Agent
```
Perspective Agent → Query 1 → Research Agent
                 ← Findings 1 ←
                 → Query 2 (follow-up) →
                 ← Findings 2 ←
                 → Query 3 (final check) →
                 ← Final Findings ←
```
최대 3회 반복, 충분한 정보 확보 시 조기 종료

### Strategy ↔ Validation Loop
```
Strategy Layer → Proposed Allocation → Validator
                                          ↓
                                    [Validation]
                                          ↓
             ← Approved ← [All Passed?] → Feedback →
                              ↓
                        [Iteration < 3?]
                              ↓
                    Yes: Strategy 재조정
                    No: Conditional/Reject
```

## 새 Agent 추가 절차

1. **Persona YAML 생성**
   ```bash
   touch src/config/personas/new_agent.yaml
   ```

2. **AGENT.md 생성**
   ```bash
   mkdir src/agents/perspective/new_agent/
   touch src/agents/perspective/new_agent/AGENT.md
   ```

3. **Flow 설정에 추가**
   ```yaml
   # src/config/flows/growth.yaml
   perspective_agents:
     - name: new_agent
       weight: 0.20
   ```

4. **README.md 업데이트**
   - `src/agents/perspective/README.md`에 새 Agent 추가
   - `docs/README.md`에 링크 추가

## Agent 평가 기준

| 기준 | 설명 |
|------|------|
| Mission 명확성 | 한 문장으로 목표 정의 가능 |
| Input 명세 | Python dict 스키마로 명확히 정의 |
| Output 명세 | Python dict 스키마로 명확히 정의 |
| 독립 실행 가능 | Mock 데이터로 단독 테스트 가능 |
| Rules 구체성 | 명확하고 측정 가능한 규칙 |
| Example 품질 | 실제 사용 가능한 JSON 예시 |
