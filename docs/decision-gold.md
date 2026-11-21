# 당시 정보 기준의 투자 결정 평가

서로 다른 선택이 같은 기준을 충족할 수 있어요. 사례마다 판단 시점, 목적·제약, 당시 근거, 허용하는 선택과 그 전제, 반드시 검산할 값, 기각할 주장을 고정해요. 수익률 순위는 채점 항목에 들어가지 않아요.

## 사례 재생

저장소 루트에서 실행해요. 기본 사례는 네트워크나 모델 호출 없이 재생돼요.

```sh
cases=resources/decision-gold
manifest=$cases/manifest-v1.json
python3 -m mara.decision_gold replay "$cases" "$manifest" fx-lot-reserve
python3 -m mara.decision_gold outcome "$cases" "$manifest" fx-lot-reserve
python3 -m mara.decision_gold outcome "$cases" "$manifest" settlement-window
python3 -m unittest discover -s tests -p 'test_*gold*.py'
```

| 사례 | 동결 목적 | 구분 |
|---|---|---|
| fx-lot-reserve | 환전 가산율·주문당 수수료·최소 준비금과 추가 지출의 불확실성이 매수 단위를 바꾸는지 | 튜닝 |
| settlement-window | 만기 가치와 지급일까지 쓸 수 있는 현금을 구분하는지 | 잠금 회귀 |
| lookthrough-cap | 직접 보유와 펀드 안 동일 발행사, 확인된 지분 범위의 상단과 거래 후 분모를 함께 계산하는지 | 잠금 회귀 |

Git에 배포한 세 사례는 합성 사례예요. 잠금 두 건은 고정된 회귀 검사를 반복하는 데 사용해요. 이미 내용을 본 개발자·모델·평가자를 새 비공개 검증에 투입하면 노출 사실을 기록해요. 공개된 사례에서 얻은 점수를 새 버전 채택 근거로 쓰지 않아요.

## 새 사례와 반복 실험

1. 자료 관리자가 접근이 분리된 폴더에 `<case-id>/input.json`을 만들어요. 네 시각은 **관측·최초 공개·해당 판본의 공개·실제 입수**예요. 시간대를 포함해요. 네 시각 중 하나라도 불명확하거나 cutoff보다 늦으면 해당 판본은 작성자 입력에서 빠져요. 같은 계열에서는 그때 이용 가능한 최신 수정본만 남아요. 자금·보유·제약의 미확인은 그대로 입력하고, 자료 공백이 결정을 바꾸는지 판정 기준에 적어요.
2. 후보 작성에 관여하지 않은 판정자가 당시 정보로 `gold.json`을 먼저 작성해요. 허용 선택, 필요 조건, 피할 수 있었던 오류와 당시 해결할 수 없었던 공백, 반례, 근거 위치와 산식을 남겨요. 버전·시각·독립 판정 근거를 기록해요. 수정 시 이전 버전과 해시, 사유를 보존하고 새 manifest를 만들어요. 가계 자료 등 비공개 사례는 관리 권한이 있는 `.local`에 둬요.
3. 같은 시점에 튜닝한 후보, 이전 Mara, 단일 모델, 간단한 규칙을 등록해요. 후보와 이전 버전은 `kind=mara`, 나머지는 `single`, `simple`이에요. 각 시스템에 버전과 실제 아티팩트 SHA-256을 붙이고 비교 기준, 모델/도구 접근, 호출·토큰·시간 예산과 실패 처리 규칙을 `design.conditions`에 적어요. 단계 수를 같게 만들 수 없다면 통제 실패와 실제 투입량을 함께 보고해요. 예상 반복 수와 평가자, 독립 사례 단위, 보관자와 미노출 확인 근거까지 정해요.
4. 가설 파일에는 `id, observation, source_ref, hypothesis, change_ref, candidate, expected_change, falsifier, target_axis`를 채워요. `candidate`는 후보 ID, `change_ref`는 후보의 버전이에요. `target_axis`는 decision/evidence/suitability/alternatives 중 하나예요. `design.hypothesis_sha256`에 `mara.decision_gold.digest(proposal)`을 넣어요. 시험 전에 manifest·가설·코드 버전을 독립 보관자에게 동결해요. 설명에 적은 추가 예측은 사람이 검증할 때까지 미검증이에요.
5. 작성자는 `replay` 출력만 받아요. Git 저장소·원본/수정본·gold·사후 경로에 접근할 수 없는 새 세션에서 각 후보를 생성해요. 원고별 원본 해시와 중립화 내역을 보관하고, 시스템명·출처를 추정할 머리말/경로만 가려요. 실행 중단·재시도·토큰·시간도 남겨요. 같은 시점·예산인지 검증할 수 없으면 소급 비교로 표시해요. 검증에는 `case_id, system, repeat, author, run_id, text, started_at, input_sha256, input_mode, closed_book, conditions_sha256, costs`를 사용해요. 입력과 조건 해시는 각각 재생 JSON과 등록 조건의 정규화 SHA-256이에요.
6. `prepare`가 사례·대조군·반복마다 익명 A/B와 역순 A/B를 만들어요. 보관자는 `private.json`을 보관하고 평가자에게 배정한 packet만 전달해요. 두 사람 또는 서로의 답을 볼 수 없는 호출을 사용하고 문체 등 정체 추정 가능성을 남겨요. 각 축에 양쪽 원문에서 실제로 찾을 수 있는 인용, 당시 자료/골드 기준 ID, 선택 사유와 필수 조건 통과 여부를 기록해요. 판정 불일치, 실패, 누락은 원본 투표에 남겨요. 평가자 간 의견을 조정해 하나의 원래 점수로 덮지 않아요.
7. `compare`에서 사례 단위 승/패/동률과 이견을 확인해요. 같은 사례의 두 작성 반복이나 순서 반전 표는 독립 사례 수를 늘리지 않아요. 잠금 전 범위, 반복, 독립·미노출 확인, 주요 축 퇴행, 세 대조군 각각의 단측 부호검정(가족 오류율 0.05 보정)과 등록 가설 충족을 확인해요. 독립 사례 가정은 도구가 증명하지 못해요. 잠금 2건은 모두 이겨도 단측 p=0.25여서 이 문턱을 통과할 수 없어요. 실패하면 개선 가설을 보류하고 새 변경과 새 잠금 표본으로 돌아가요.

각 명령의 입력 예시는 테스트의 `config()`·`ballots_for()`와 익명 packet 안의 `ballot_format`에 있어요. 테스트 투표는 프로그램 검증용 합성값이에요. 실제 검토에 사람이 쓴 근거 또는 독립 평가 호출의 원본을 사용해요.

```sh
python3 -m mara.decision_gold freeze "$cases" --design design.json > manifest.json
python3 -m mara.gold_cycle register hypothesis.json manifest.json registration.json
python3 -m mara.gold_cycle reserve registration.json manifest.json custodian.sqlite3
python3 -m mara.decision_gold replay "$cases" manifest.json CASE_ID > author-input.json
python3 -m mara.decision_gold prepare "$cases" manifest.json submissions.json private-batch
python3 -m mara.gold_cycle seal registration.json manifest.json private-batch custodian.sqlite3
# 위 봉인 후에만 packets/를 배포하고 독립 표를 수집해요.
python3 -m mara.decision_gold compare "$cases" manifest.json private-batch ballots.json > regression.json
python3 -m mara.gold_cycle decide registration.json "$cases" manifest.json private-batch ballots.json decision.json --ledger custodian.sqlite3
```

`reserve`는 노출 전 사례 보관자가 한 번 실행해요. 다른 실험이 같은 사건 단위를 다시 예약하면 원장 전체 변경을 취소해요. 공개 회귀 표본은 예약 단계에서 거부해요. 평가 전 배치와 첫 판정의 투표를 원장에 봉인하고, 같은 등록은 동일한 근거로만 재현해요. 같은 원장·ID를 계속 쓰고 접근을 분리해야 해요. 기계는 다른 저장소에서 이미 봤는지 증명할 수 없어요. `decide`는 원고와 투표에서 결과를 다시 계산하고 채택 여부를 새 파일에 써요. 매매·서비스 배포·개인화 변경은 실행하지 않아요.

## 사후 회고와 기준의 관계

사후 경로는 별도 `outcome.json`에 같은 통화, 날짜, 자금흐름과 비용 기준을 적고 비교해요. 표본 기간 수익률, 관측점 기준 최대낙폭, 이전 고점 회복일, 보류·대안과의 차이를 산출해요. 관측점 사이 고점·저점은 보이지 않아요. 미회복과 미관측을 구분해요. 선택하지 않은 대안은 실제 체결, 세금, 중도 인출이나 시장 충격을 관측할 수 없어요. 같은 시장·환율 경로 아래의 모형 차이를 운이나 운용 능력으로 인과 귀속할 수 없어요.

A1은 리더·분석자의 당시 과정을 보는 기준이고, R4는 해당 제안의 제약과 수치 검증, Q1은 근거·본문 품질, B1은 독립 단일 모델과의 내용 비교예요. R6 실제 성과는 확인된 보유와 현금흐름을 요구해요. 이번 도구는 별도 실행되며 기존 점수와 운영 원장을 수정하지 않아요. A1 전 과정 운영 자동채점이나 미확인 계좌의 수익률은 검증 범위에 포함하지 않았어요.

시점이 닫힌 자료로 가설을 세우고 검증 단계를 분리하는 방법은 day-trader-skill, 공개 시각에 따라 보이는 정보와 모의 체결을 구분하는 원리는 DAS Replay를 참고했어요. 이 평가에서는 몇 년 동안 필요한 현금·회복·환율을 기준으로 재구성했어요. [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) · [DAS Replay](https://dasreplay.com/support/getting-started/what-is-real-and-what-is-simulated/)
