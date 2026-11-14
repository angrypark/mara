# 상시 화면과 토스증권 연동

## 현재 실행 상태

로컬 주소는 **http://127.0.0.1:8788**이에요. macOS LaunchAgent `com.angrypark.mara`가 로그인 시 시작하고 종료 시 재시작해요. Mac이 꺼져 있거나 잠자기 중일 때까지 실행되는 원격 서버는 아니에요.

화면은 합성 데이터 전용이에요. 다음 주 평가 버튼으로 7일 뒤 평가·회고·지식 점검을 실행하고 기록을 저장해요. 실제 시간 기준으로는 60초마다 예정일을 확인하고 주 1회 모의 평가를 실행해요. 테스트 버튼으로 미래 날짜까지 진행했다면 그 다음 예정일 전에는 자동 실행하지 않아요.

```sh
cd /Users/angrypark/code/workspace/repos/mara
python3 scripts/service.py status
python3 scripts/service.py restart
python3 scripts/service.py stop
# 다시 등록하고 시작하기
python3 scripts/service.py install
```

상태·모의 DB는 `.local/service/`, 로그는 `.local/service/logs/`에 있어요. UI는 loopback만 수신하며 Host 확인, CSP, 동일 출처·CSRF 검사를 적용해요. 토스 주문 API나 실거래 활성화 경로는 UI와 상시 서비스에 없어요.

## 합의한 한도

- 시장: 미국 주식
- 총 운용금액: 30,000,000원
- 1회 주문금액: 1,000,000원
- 하루 주문금액: 3,000,000원
- 일일 기준: 한국 시간 00:00–24:00, 매수·매도 금액 합산
- 주문 방식: 정수 수량 지정가, DAY, 미국 정규장만

달러 주문금액은 유효한 USD/KRW 환율(rate와 midRate 중 큰 값)로 환산하고, 1%의 수수료·환율 여유를 더해 한도를 검사해요. 이 1%는 실제 수수료율이나 최대 손실 보장이 아니에요. 거절·취소된 주문도 그날 예약한 한도에서 자동 차감하지 않아 보수적으로 계산해요. 다른 앱에서 발생한 주문은 별도 집계되지 않으므로 이 프로그램 외의 매매까지 포함한 증권사 계좌 전체 일일 한도를 보장하지 않아요.

총 운용금액은 확인된 달러 현금과 주식의 현재 평가액 합계예요. 시세 상승으로 한도를 넘은 경우에도 주문을 멈추며 자동 매도하지 않아요. 한도를 넘는 주문을 잘게 나누어 보내는 기능은 없어요.

## 비밀 설정 템플릿

아래 두 파일은 이미 로컬에 만들었고 Git에서 제외해요. 권한은 0600이에요.

- `.local/toss/credentials.json`: `client_id`, `client_secret`, `account_seq`
- `.local/toss/policy.json`: 위 한도, `allowed_symbols`, `live_enabled: false`

`credentials.json`에 토스에서 발급한 두 값을 직접 채워주세요. 키를 채팅에 보내거나 저장소에 커밋하지 않아요. `account_seq`는 계좌번호가 아니라 API가 반환한 계좌 식별 키예요. 설정된 계좌가 없고 종합매매 계좌가 정확히 하나일 때만 조회 검증 후 계좌 식별 키를 반영해요. 여러 계좌 중 첫 계좌를 임의로 선택하지 않아요.

토스는 이미 키 발급·허용 IP 등록을 마쳤다고 알려주셨어요. 자격증명을 입력한 뒤 `python3 -m mara.connection`으로 인증·계좌·보유·매수가능금액·미체결 조회를 검증할 수 있어요. 성공한 조회의 확인 시각이 상시 화면에 표시돼요. 실제 보유 정보는 모의 포트폴리오에 섞지 않아요. 토큰은 같은 디렉터리의 `access-token.json`에 0600으로 캐시해요. 동시에 다른 프로그램에서 같은 client의 토큰을 재발급하면 이전 토큰이 무효화될 수 있어요.

## 조회와 모의 주문

다음 명령은 **사용자가 직접** 필요한 설정을 채운 뒤 실행해요. `accounts`는 계좌번호 전체를 출력하지 않고 계좌 식별 키와 끝 네 자리만 보여줘요.

```sh
python3 -m mara.trading accounts
# 주문 없이 연결을 확인하고 화면 상태에 반영해요.
python3 -m mara.connection
```

확인한 `account_seq`를 credentials와 policy 양쪽에 넣고, 정책의 `allowed_symbols`에 운용 대상으로 검토한 종목을 명시해요. 특정 종목을 이번 작업에서 임의로 정하지 않았어요.

실제 분석용 Mara 사용자 토큰을 `MARA_TOKEN` 환경변수에 설정하고 다음 명령을 실행할 수 있어요.

```sh
python3 -m mara.trading snapshot
python3 -m mara.trading plan --report-id COMPLETED_LIVE_REPORT_ID
```

snapshot은 계좌 보유·매수가능금액·미체결·가격·종목 정보·환율·시장 시간을 조회해 사용자별 DB에 저장해요. 매수가능금액은 현금 잔고와 동일하지 않으므로 실제 포트폴리오의 현금으로 자동 덮어쓰지 않아요. plan은 당일 검증된 라이브 제안과 확인된 실제 보유를 대조해 주문안을 저장해요. 합성 데모 제안으로는 주문안을 만들지 않아요.

가격 60초, 조회 묶음 120초 이내의 자료를 요구해요. 유효한 환율·정규장 시간·허용 종목·보유 수량 일치·매도 가능 수량·매수 가능 금액을 검사해요. 매도 주문의 예상 대금을 다음 매수의 현금으로 가정하지 않아요. 포트폴리오 구성 비중은 일반 코드가 정수 수량으로 내림 계산하므로 목표 비중과 정확히 같지 않을 수 있어요.

## 실주문 코드의 경계

`mara.trading`에는 사용자가 직접 운영할 수 있는 `execute` 코드가 있어요. 이번 작업에서는 **호출하지 않았고**, 설치한 LaunchAgent와도 연결하지 않았어요. `live_enabled=false`와 `.local/toss/STOP` 파일로 중지된 상태예요. 실주문 전송이나 실거래 자동매매 활성화를 에이전트가 대신 수행하지 않아요.

사용자가 실거래 코드를 직접 운영하는 경우에도 주문 의도를 DB에 먼저 저장하고, 같은 보고서의 재전송을 차단해요. 서버의 멱등성 키는 10분만 유효하므로 타임아웃을 자동 재시도하지 않아요. 접수 응답을 체결로 간주하지 않고 상세 주문 상태를 다시 확인해요. 부분 체결·대기·취소·알 수 없는 상태에서는 다음 주문을 멈춰요. 가격이 원래 지정가에서 0.5% 이상 움직이면 추격 주문을 하지 않아요.

미확인 주문은 토스 화면에서 먼저 확인하고, 주문 ID와 로컬 intent ID를 명시해 조회 결과를 연결해요.

```sh
python3 -m mara.trading reconcile --order-id BROKER_ORDER_ID --intent-id LOCAL_INTENT_ID
```

조정은 기존 기록을 삭제하지 않아요. 매매 후 실제 보유·현금·입출금은 다시 확인해 Mara의 실제 포트폴리오에 반영해야 해요. 부분 체결 후 나머지 주문을 이어 보내거나 주문 가격을 자동 정정하지 않아요. 이 단계는 완전 무인 실거래 운영이 아니라, 사용자가 검토·운영할 수 있도록 준비한 보수적인 주문 실행 코드예요.

동일 토스 계좌는 하나의 Mara DB와 credential 디렉터리로 관리해야 해요. 다른 DB·다른 프로세스·외부 매매까지 통합하는 증권사 전체 한도 시스템은 아니에요.

## 확인한 공식 규격

확인일 2026-11-14, OpenAPI 1.2.28 기준이에요.

- [공식 API 가이드](https://developers.tossinvest.com/docs)
- [기능·인증 개요](https://openapi.tossinvest.com/openapi-docs/overview.md)
- [OpenAPI 원본](https://openapi.tossinvest.com/openapi-docs/latest/openapi.json)

OAuth2 Client Credentials, 계좌별 `X-Tossinvest-Account`, 문자열 decimal 수량·가격, 10분 유효 `clientOrderId`, REST 주문 상세·미체결 조회를 반영했어요. 고정된 한도를 추측한 고속 재시도 대신 직렬 저빈도 호출과 429 중단을 사용해요. 모델·클라이언트는 비밀 키를 분석 문맥이나 실행 보고서에 포함하지 않아요.

연결 표시는 최근 24시간 이내에 검증한 자격증명·계좌에만 유효해요. 화면 자체는 토스 API를 반복 호출하지 않으며, 표시 시각은 실시간 잔고 갱신 시각이 아니에요.
