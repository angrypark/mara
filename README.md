# Mara

개인의 목표와 생활 맥락에 맞는 포트폴리오를 여러 관점으로 검토하고, 실제 결과와 판단 과정을 회고하는 도구예요. 제안과 실제 보유를 분리하고 당시 근거를 보존해요. 기본 실행과 상시 화면은 실제 주문을 전송하지 않아요. 사용자가 직접 운영하는 토스증권 주문 코드는 별도 모듈로 제공해요.

Python 3.9 이상, 외부 Python 의존성 없이 저장소 루트에서 실행할 수 있어요.

```sh
python3 -m mara --help
python3 -m unittest discover -s tests -v
python3 -m examples.demo
```

마지막 명령은 임시 DB에서 최초 생성과 다음 주 평가를 보여주는 **합성 데모**예요. 실제 시장이나 투자 분석이 아니며 기존 데이터에 쓰지 않아요.

## 의사결정 작업실과 독립 평가

흐름도에서 역할 박스를 선택하면 당시 결과·입력·근거와 대화를 볼 수 있어요. R4의 관점 검증과 최종 검증은 별도 단계예요. 대화의 판단 변경을 선택해 반영하면 당시 자료를 고정한 새 실행에서 전체 후속 검증과 Q1 평가를 거쳐요. 원본과 실제 보유는 보존하고, 목표·보유 변경은 설정 화면에서 다뤄요.

에이전트는 SEC 목록 검색, 최대 200개 기업 수집, 페이지 비교, 개별 재무·공시 본문, 가정이 명시된 주당 가치 계산 도구를 사용할 수 있어요. 공개 원본은 별도 보관하고 활성 추가 근거는 실행 전체 80,000자로 제한해요. 수집·실제 읽음·공백을 구분해요. SEC 목록/본문 접근 제한은 숨기지 않으며 확인된 일부 공식 IR 보조 자료를 사용할 수 있어요.

Q1은 작성 호출과 분리된 평가자로 [공개 보고서 조사](guides/reference-reports.md)와 고정 [rubric](resources/evaluation-rubric.json)에 따라 8개 항목을 채점해요. 총점은 코드가 계산하고 R4의 거부를 해제하지 않아요. 같은 모델을 별도 호출하는 구조이며 미래 성과 평가가 아니에요. [공개 계약과 API](contracts/README.md)에 버전과 확장 경로를 설명했어요.

## 상시 실행 화면

**http://127.0.0.1:8788**에서 투자 맥락·섹터·위험 기준을 입력하고, 토스 보유를 확인해 초기 제안과 평가를 생성해요. 입력 임시 저장과 모델 설정도 화면에서 할 수 있어요. [포트폴리오 평가](docs/portfolio-evaluation.md)에 지표·제약·자료 한계를, [서비스 관리·토스증권 설정](docs/service-toss.md)에 운용 한도와 실행 방법을 정리했어요. 로그인 후 자동 시작하며 실제 주문을 전송하지 않아요. 합성 데모는 별도 영역이에요.

분석 실행 방식은 HTML에서 **Codex CLI** 또는 **OpenAI API**를 선택해 저장해요. Codex는 이 Mac의 CLI 로그인을 사용하며 API 키를 따로 입력하지 않아요. [실행 설정과 제한](docs/service-toss.md#codex--api-실행-설정)을 확인해요. 아래 CLI 명령 예시는 기존 HTTP API 제공자용이에요.

**분석 리포트** 탭에서는 시황 → 세 투자 관점 → 리더 제안 → 위험 평가 → 투자 결과·과정 회고 → 출처를 읽어요. 관점별 비중 비교, 실제·제안·지난 제안 비교, 섹터 상한과 미확인 노출을 표시해요. [리포트 구성과 해석](docs/reports.md)에 표시 기준을 정리했어요. 별도 모의 리포트로 화면을 확인하거나 브라우저 인쇄로 PDF를 저장할 수 있어요.

## 최초 설정과 포트폴리오 생성

```sh
# 로컬 운영자: 새 사용자 토큰을 한 번 출력해요. 개인 비밀 저장소에 보관해요.
python3 -m mara create-user my-account
# 출력 토큰을 MARA_TOKEN 환경변수에 설정해요. 소스 코드에 저장하지 않아요.

python3 -m mara profile /private/profile.json --as-of 2026-11-14
python3 -m mara holdings /private/holdings.json
python3 -m mara market /private/market.json

# 실제 모델 호출에 필요한 MARA_API_KEY, MARA_MODEL을 환경변수에 설정해요.
python3 -m mara run --as-of 2026-11-14
```

`--db /private/mara-v1.sqlite3`는 모든 명령 앞에 지정할 수 있어요. 기본은 `.local/mara-v1.sqlite3`예요. 기존 wiki나 DB를 덮어쓰지 않도록 새 경로를 사용해요. 토큰을 잃으면 DB의 로컬 관리자가 별도 복구 절차를 마련해야 하므로 안전하게 보관해요.

입력 형식은 [profile](examples/profile.json), [holdings](examples/holdings.json), [market](examples/market.json)에 있어요. 예시 종목·가격은 합성이며 라이브 모드에서 거부해요. 실제 팩은 `synthetic`을 false로 지정하거나 생략하고 출처를 검증해요.

- profile: 자산 총액, 투자 시장, 목표·기간, 소득·지출, 현금 필요 금액·시점, 손실·집중 한도, 납입 금액·주기, 리밸런싱 주기와 추가 제약을 입력해요.
- holdings: 실제 수량과 현금, 기준통화, 확인일, 구성 이유, 마지막 **실제** 리밸런싱일을 입력해요. 아직 투자하지 않았다면 positions={}와 cash에 투자 가능 금액을 넣어요.
- market: 기준통화 가격, 관측·인지 시점, 원문 URL, 자산별 시장·비용·스트레스 가정, 사실 텍스트·발표/인지/만료 시점·불확실성을 입력해요. `stress_loss`는 시나리오 가정이며 보장된 최대 손실이 아니에요.

모델 설정은 `MARA_MODEL`에 사용할 모델 ID, `MARA_API_KEY`에 비밀 키를 지정해요. 기본 엔드포인트는 OpenAI Chat Completions이고 JSON mode를 지원하는 모델이 필요해요. `MARA_API_URL`로 호환 HTTPS 엔드포인트를 지정할 수 있어요. 모델에 사용자의 투자 맥락이 전달되므로 신뢰하는 제공자를 설정해요. 별도 검색 도구를 모델에 허용하지 않고 검증된 시장 팩을 입력해요. 실패 시 합성 모델로 대체하지 않아요.

## 다음 주 평가

```sh
# 실제 변동이 없어도 확인일을 갱신한 holdings를 기록해요.
python3 -m mara holdings /private/holdings-20261121.json
# 외부 입출금이 있었다면 기록해요. 없으면 생략해요.
python3 -m mara cashflow /private/deposit.json
python3 -m mara market /private/market-20261121.json
python3 -m mara tick --as-of 2026-11-21
python3 -m mara report
```

입출금 형식은 `{"date":"2026-11-18","amount":1000,"reference":"unique-bank-reference"}`예요. 출금은 음수예요. 배당·이자·수수료·세금은 실제 최종 현금에 반영해요. 외부 납입으로 다시 입력하지 않아요.

`tick`은 마지막 완료에서 7일이 지났을 때만 실행해요. `due --as-of YYYY-MM-DD`로 확인할 수 있어요. 리밸런싱 주기는 profile과 마지막 실제 변경일을 기준으로 별도 계산해요. 다음 주에도 기존 구성을 유지할 수 있고, 제안은 실제 수량을 바꾸지 않아요. 실제 변경 후에는 이유를 포함한 `holdings`를 별도로 기록해요.

출력에는 현재 평가, 납입을 제외한 성과, 이전 판단과의 연결, 세 관점 원문, 정량·정성 검증, 최종 제안·반대 의견·위험·다음 확인과 다음 일정이 들어 있어요. 실제 보유가 구간 양 끝에서 확인되지 않으면 수익률은 미확인으로 남겨요.

## 정기 실행

운영자 스케줄러가 매일 `tick`을 호출해도 기본 평가는 주 1회예요. 예를 들어 환경변수를 비밀 저장소에서 주입하는 실행 스크립트를 만들고 다음 명령을 cron 또는 LaunchAgent에서 호출해요.

```sh
python3 -m mara tick --as-of "$(date +%F)" --market-url https://your-trusted-feed.example/mara/latest.json
python3 -m mara prune-shared --as-of "$(date +%F)"
```

feed는 위 market JSON 계약과 같은 실제 자료를 반환해야 해요. 임의 뉴스 사이트 URL을 넣는 기능이 아니에요. HTTPS, 30초 제한, 2 MB 제한, 리다이렉트 차단, 날짜·필드 검증을 적용해요. 평가일과 맞지 않는 팩은 거부해요. 시장 휴장일 가격은 최대 7일 전 관측을 허용하지만 팩의 as_of는 평가일이어야 해요.

개인 정보·모델·시장 공급자·계정은 이 저장소에 포함하지 않아요. 배포 환경에서 위 설정과 실제 팩을 연결해야 실제 주간 운영을 시작할 수 있어요. 이번 구현 작업은 사용자 계정이나 OS 스케줄러를 임의로 등록하지 않아요.

## 지식 정리와 복원

주간 회고 후 memory agent가 추가·통합·수정·비활성화·보관을 제안하고, 근거·소유권 검증 뒤 적용해요. 전체 활성 집합을 점검하며 원본은 남겨요. 공통 시장 지식은 로컬 운영자가 `shared-knowledge FILE --as-of DATE`로 관리하고 사용자 정보의 자동 승격은 금지해요.

`knowledge FILE --as-of DATE`로 검토한 변경을 적용할 수도 있어요. 기본 추가 형식은 다음과 같아요. refs에는 같은 사용자 실행 또는 공통 시장의 실제 event ID가 필요해요.

```json
{
  "action": "add", "reason": "이번 회고에서 확인한 검증 누락",
  "text": "현금 필요 시점과 신용 만기를 함께 확인해요.",
  "topic": "liquidity", "condition": "은퇴 인출기", "perspective": "all",
  "category": "lesson", "roles": ["validation", "leader"],
  "refs": ["실제 event ID"], "valid_until": null, "priority": 7
}
```

기존 항목의 변경은 `key`를 지정해요. 복원은 `{"action":"restore","key":"...","version_event":"이전 knowledge event ID","reason":"잘못된 정리 복원"}`이에요. 만료일도 복원되므로 이미 지난 정보가 자동으로 다시 유효해지지는 않아요. 보호된 principle/rare_risk를 비활성화하려면 invalidating_refs로 반증 근거를 제공해야 해요.

```sh
python3 -m mara guide validation /private/reviewed-guide.md --reason '검증 누락 보완' --as-of 2026-11-21
python3 -m mara restore-guide EVENT_ID --reason '잘못 적용한 지침 복원' --as-of 2026-11-22
python3 -m mara export /private/new-audit-export.json
```

가이드·철학 변경과 에이전트 가중치 변경은 단기 성과로 자동 적용하지 않아요. 원본·버전·근거는 `report --id EVENT_ID`로 확인할 수 있어요. 강제 종료로 잠금이 남았다면 실행 프로세스가 끝났는지 확인하고 `recover --reason '확인한 이유' --as-of DATE`로 해제해요.

## 문서와 검증 범위

- [구조·데이터 모델·역할·보존 정책](docs/architecture.md)
- [요구사항 대응과 검증](docs/requirements.md)
- [Buffett 가이드](guides/personas/buffett.md), [Marks 가이드](guides/personas/marks.md), [Bogle 가이드](guides/personas/bogle.md)
- [역할별 가이드](guides/roles/)

원문 주주서한·메모·강연·의회 증언을 직접 대조해 조사했어요. 확인된 견해와 MARA 실행 규칙을 구분하고, 출처·조사일·사례 결과·한계를 각 문서에 적었어요. 기존 `wiki/`는 내용과 파일을 그대로 보존해요.

### 대화로 개인 맥락 만들기

Mara 첫 화면의 ‘나의 페르소나’에서 상황·목표·관심사를 이야기해요. 기존 저장값으로 시작하고, 실제 사용자 발언과 모델 해석을 구분해 버전으로 보존해요. ‘페르소나로 분석하기’는 해당 버전을 모든 투자 에이전트와 평가자에 고정 전달해요. 상세 폼은 접힌 설정으로 유지하며, 임시 저장은 현재 페르소나를 바꾸지 않아요. [개인 대화 계약](contracts/README.md#개인-페르소나와-대화)에서 변경·충돌·복구 기준을 확인할 수 있어요.
