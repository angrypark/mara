# Mara 공개 결과 계약

`GET /api/contracts/<name>`으로 같은 JSON Schema를 읽을 수 있어요. 원본 이벤트는 append-only이고 결과 화면은 버전 있는 투영이에요.

- `workbench` v1.2: 역할 컴포넌트, 당시 입력/출력, 근거, 포트폴리오, flow·독립 평가·개정 이력. v1.0/1.1 원본을 유지해요.
- `flow` v1.0: 단계 ID와 실제 agent ID, 의존 단계, 상태, 출력 기록. R4는 1차/최종 단계별 `snapshot`을 가져요. 출력 검증 실패는 `failed`와 `output:null`이에요.
- `agent-*`: 각 역할의 실제 출력 계약. 대화 변경을 받은 단계는 `change_response`로 수용/일부 수용/거부와 이유를 반환해요.
- `research-plan` v1.0: 에이전트가 요청할 수 있는 검색·수집·페이지 비교·기업 상세·본문 검색·주당 가치 계산. 임의 URL·코드 실행·주문 도구는 없어요.
- `evaluation` v2.0 (v1.0 호환): 기준 실행/시점, 고정 rubric와 해시, 별도 평가자 출력, 코드로 계산한 가중 점수. 투자 승인이나 수익 예측이 아니에요.
- `dialogue`/`dialogue-answer` v1.0: 기존 필드를 유지하고 선택적 `proposed_change`를 추가했어요. `scope`는 `reasoning`, `settings`, `none`이에요.

## 최종 보고서와 fact

- `final-report` v1.0: 확정된 상태·비중·이유·대안·미해결 질문·후속 확인·출처와 구성 근거예요. 원본 역할 출력은 그대로 유지해요.
- `fact-snapshot` v1.0: 논리 fact ID, 원문 전체, 출처·시점·내용 해시와 부모 자료 버전이에요.
- `fact-graph` v1.0: 완료 보고서의 판단과 fact snapshot 연결, 저장 검증 상태와 미확인 항목이에요.
- `price-series` v1.0: 종가 종류, 통화, 요청 기간과 실제 관측점이에요. 근거 없는 값 보간이나 연속 하락 추론은 하지 않아요.

보고서 API의 `view.final_report`와 `view.evidence_graph`에서 확인해요. 저장한 문서는 원본 재조립 결과와 대조하고, 이전 형식에서 만든 표시 문서는 원래 저장본과 구분해요. [fact 저장 구조](../docs/facts.md)를 함께 확인해요.

## 행동 API

모든 POST는 loopback Host, 동일 Origin, 화면의 `X-Mara-CSRF`를 검사해요. `scope`는 `portfolio` 또는 `demo`이며 서로 다른 DB/사용자를 사용해요.

`POST /api/dialogue/<scope>`: `run_id`, `agent_id`, `request_id`, `message`. R4 단계 박스에서 시작하면 선택적 `source_output_id`를 보내며, 서버가 해당 실행·역할·단계의 출력인지 검사해요. 최근 역할 대화는 이어지고 이번 질문의 기준 출력은 고정돼요.

`POST /api/decision-action/<scope>`: `action`(`evaluate` 또는 `revise`), `run_id`, UUID `request_id`. `revise`는 완료된 답변의 `dialogue_request_id`가 필요해요. 같은 요청 ID는 같은 내용일 때 중복 실행하지 않아요. 더 최신 완료 제안이 있으면 과거 기준 변경을 거부해요.

대화 반영은 당시 profile/actual/market과 읽은 근거를 고정한 새 실행이에요. 모든 판단 단계를 재평가하고 Q1까지 연결해요. 개인 목표 변경은 별도 개인 페르소나 대화에서 현재 맥락을 갱신해요. 실제 보유는 계좌 확인 경로로 관리해요. 회고/기억의 대화는 맥락 재검토로, Q1의 대화는 리더 재검토로 전달하며 지식·실제 보유를 직접 덮어쓰지 않아요. 당시 기준의 재검토에는 현재 시장 자료를 소급 수집하지 않아요.

도구의 공개 원문은 content-addressed 보관소, 사용자 요청·읽힌 근거·평가와 대화는 사용자 이벤트에 저장해요. `research_tool_result`는 수집/읽음/활성화 상태를 구분하고, 일반 80,000자와 연구 역할별 예약을 합친 실행 전체 최대 368,000자의 활성 추가 근거 상한 밖 원본도 보존해요. 새 기업은 가격·분류·유효 근거가 있는 기존 후보와 구분하며 자동 매수 후보로 승격하지 않아요.

작업 도중 재시작하면 미완료 상태를 복구 기록으로 남기고 다시 실행할 수 있어요. Q1 실패가 완료 제안이나 높은 품질 점수로 변환되지는 않아요. 확장은 새 버전과 명시적인 역할·도구·계약 등록을 통해 해요.

## 개인 페르소나와 대화

- `persona` v1.0: 현재 profile ID와 버전, 단위·범위가 있는 사실, 기존 기록/직접 진술/미확인/철회 상태, 선호 항목별 원문·해석·출처, 알려진 답변과 활성 입력 생략 내역이에요.
- `persona-reply`: 대화 설명, 정확한 사용자 인용에 근거한 허용 필드 변경, 선택형 후속 질문 최대 1개예요. 실제 채택 항목과 보류 사유는 저장 결과에서 구분해요.
- `GET /api/persona`: 현재 버전과 최근 30개 대화. 전체 원본은 사용자별 이벤트에 보존해요.
- `POST /api/persona/messages`: UUID `request_id`, `persona_id` 또는 null, `message`(4,000자). 수락한 기반 profile과 다른 수정이 생기면 덮어쓰지 않아요. 채택 profile·persona·결과 receipt는 같은 transaction에 저장돼요.
- `POST /api/persona/analyze`: UUID `request_id`, `persona_id`. 충분한 기존 정보가 있으면 상세 폼 없이 시작해요. 수락 시 profile/actual/persona ID와 hash를 고정하고 전 역할·Q1·보고서에 전달해요. 실제 보유나 주문은 바꾸지 않아요.

현재 사실을 철회하면 disputed 상태를 표시하고 해당 숫자를 그대로 계산하지 않아요. 명시적인 현재 값으로 해결한 뒤 분석해요. 관심사는 항목별 출처와 함께 누적하고, 명시 대체만 기존 활성 선호를 바꿔요. 원본은 삭제하지 않아요. 현재 persona와 한정된 최근 대화의 입력 한도는60,000자이며, 새 메시지와 정정 여유를 남기기 위해 채택 전 크기도 검사해요.

상세 입력의 ‘임시 저장’은 초안이에요. 상세 폼으로 생성할 때 최신 profile 버전을 대조하고 persona와 함께 확정해요. 과거 보고서는 당시 persona를 유지하며 현재 버전과 다르면 화면에 표시해요.
