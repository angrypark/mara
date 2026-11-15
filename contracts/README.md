# Mara 공개 결과 계약

`GET /api/contracts/<name>`으로 같은 JSON Schema를 읽을 수 있어요. 원본 이벤트는 append-only이고 결과 화면은 버전 있는 투영이에요.

- `workbench` v1.2: 역할 컴포넌트, 당시 입력/출력, 근거, 포트폴리오, flow·독립 평가·개정 이력. v1.0/1.1 원본을 유지해요.
- `flow` v1.0: 단계 ID와 실제 agent ID, 의존 단계, 상태, 출력 기록. R4는 1차/최종 단계별 `snapshot`을 가져요. 출력 검증 실패는 `failed`와 `output:null`이에요.
- `agent-*`: 각 역할의 실제 출력 계약. 대화 변경을 받은 단계는 `change_response`로 수용/일부 수용/거부와 이유를 반환해요.
- `research-plan` v1.0: 에이전트가 요청할 수 있는 검색·수집·페이지 비교·기업 상세·본문 검색·주당 가치 계산. 임의 URL·코드 실행·주문 도구는 없어요.
- `evaluation` v1.0: 기준 실행/시점, 고정 rubric와 해시, 별도 평가자 출력, 코드로 계산한 가중 점수. 투자 승인이나 수익 예측이 아니에요.
- `dialogue`/`dialogue-answer` v1.0: 기존 필드를 유지하고 선택적 `proposed_change`를 추가했어요. `scope`는 `reasoning`, `settings`, `none`이에요.

## 행동 API

모든 POST는 loopback Host, 동일 Origin, 화면의 `X-Mara-CSRF`를 검사해요. `scope`는 `portfolio` 또는 `demo`이며 서로 다른 DB/사용자를 사용해요.

`POST /api/dialogue/<scope>`: `run_id`, `agent_id`, `request_id`, `message`. R4 단계 박스에서 시작하면 선택적 `source_output_id`를 보내며, 서버가 해당 실행·역할·단계의 출력인지 검사해요. 최근 역할 대화는 이어지고 이번 질문의 기준 출력은 고정돼요.

`POST /api/decision-action/<scope>`: `action`(`evaluate` 또는 `revise`), `run_id`, UUID `request_id`. `revise`는 완료된 답변의 `dialogue_request_id`가 필요해요. 같은 요청 ID는 같은 내용일 때 중복 실행하지 않아요. 더 최신 완료 제안이 있으면 과거 기준 변경을 거부해요.

대화 반영은 당시 profile/actual/market과 읽은 근거를 고정한 새 실행이에요. 모든 판단 단계를 재평가하고 Q1까지 연결해요. 목표·보유 변경은 설정 화면을 거쳐야 해요. 회고/기억의 대화는 맥락 재검토로, Q1의 대화는 리더 재검토로 전달하며 지식·실제 보유를 직접 덮어쓰지 않아요. 당시 기준의 재검토에는 현재 시장 자료를 소급 수집하지 않아요.

도구의 공개 원문은 content-addressed 보관소, 사용자 요청·읽힌 근거·평가와 대화는 사용자 이벤트에 저장해요. `research_tool_result`는 수집/읽음/활성화 상태를 구분하고, 실행 전체 활성 추가 근거 80,000자 상한 밖 원본도 보존해요. 새 기업은 가격·분류·유효 근거가 있는 기존 후보와 구분하며 자동 매수 후보로 승격하지 않아요.

작업 도중 재시작하면 미완료 상태를 복구 기록으로 남기고 다시 실행할 수 있어요. Q1 실패가 완료 제안이나 높은 품질 점수로 변환되지는 않아요. 확장은 새 버전과 명시적인 역할·도구·계약 등록을 통해 해요.
