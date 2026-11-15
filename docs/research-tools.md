# 분석 자료 수집 도구

조사·검증일: 2026-11-15. `PortfolioSetup.generate`가 기본 가격·환율·후보를 준비한 뒤, R2의 자료 수집 코드인 `Research.enrich`를 호출해요. 최초 생성과 주간 평가에 같은 경로를 사용해요. 기존 보고서를 다시 쓰지는 않아요.

## 역할과 자료

| 도구 | 공식 공급자 | 분석에 전달하는 내용 | 주요 사용 역할 |
|---|---|---|---|
| `sec_filings` | SEC submissions | 최근 공시 종류·일자·원문 링크 | R2, Buffett, Marks, R4 |
| `sec_financials` | SEC companyfacts | 최대 3개 연간 기간의 매출·이익·영업현금·설비투자, 최근 현금·자산·부채·자본 | Buffett, Marks, R4 |
| `treasury` | US Treasury | 최근 6일 만기별 국채 par 금리, 장단기 차이 | R2, Marks, R4 |
| `bls` | BLS | CPI·실업률, 최대 14개월 관측 | R2, Marks, R4 |
| `fed` | Federal Reserve | 정책 발표 RSS의 날짜·제목·요약·링크 | R2, Marks, R4 |
| `fund_profile` | iShares | ITOT·IVV 목적·추종지수·보수 | Bogle, R4 |
| `fund_holdings` | iShares | 구성 CSV 원본, 상위 10개·섹터 합계·구성 수 | Bogle, R4 |
| `candles` | 토스증권 | 최대 80 수정 일봉, 5/20/60거래일 가격 변화·거래량 | R2, Marks, R4 |
| `orderbook` | 토스증권 | 관측 시각의 양방향 최우선 호가·스프레드 | Marks, R4 |

별도 유료 데이터 키는 추가로 요구하지 않아요. 토스 자료는 기존 자격증명을 이용한 계좌 정보 없는 읽기 전용 GET이에요. 공공 공급자에는 계좌·프로필·소득·목표를 전송하지 않아요. 후보 종목 조회는 수행해요.

ITOT·IVV는 분산 대안을 비교할 자료예요. 이 자료를 수집했다는 이유로 사용자 후보나 매수 대상에 추가하지 않아요. 기업은 실제 보유 우선, 이후 후보 순서로 최대 8개를 수집하며 나머지는 `not_deeply_collected`에 남겨요. SEC ticker 목록 조회가 실패하면 출처와 조사일이 있는 로컬 목록을 사용하되, 모든 기업을 최신 submissions의 ticker와 다시 대조해요. 일치하지 않으면 기업 자료를 채택하지 않아요.

## 시점과 해석

- 원본은 수집 시각·URL·SHA-256을 가진 파일로 보존해요. 6시간 캐시를 재사용하면 최초 수집 시각도 유지해요. 같은 내용의 여러 조회 영수증을 보존하고, 반복 횟수를 신뢰도로 환산하지 않아요.
- 연간 기간과 순간 잔액을 구분하며 분기·누적 수치를 연간 수치에 섞지 않아요. 단위·기간·공시일·접수번호·공시 유형을 유지해요. 수정 공시는 해당 공시일 이후에만 알려진 정보로 취급해요. 부채 태그는 중복 가능성이 있어 자동 합산하지 않아요.
- 공시 목록은 본문을 읽었다는 뜻이 아니에요. 유지·성장 설비투자 구분, 부채 만기, 경쟁우위, 정상 이익, 적정 가치는 별도 검토가 필요해요.
- ETF의 알려진 구성 비중 합계가 맞아도 파생상품·포트폴리오 간 중복 분석이 완전하다고 표시하지 않아요. 운용사 섹터 분류로 사용자의 토스 섹터 제한을 덮어쓰지 않아요.
- 수정 일봉은 배당 재투자 총수익률이 아니에요. Sharpe·상관·변동성용 `risk_history`를 자동 생성하지 않아요. 국채 par 금리도 일별 무위험 수익률과 달라요.
- 호가의 시간대·통화·양방향 가격·수량·교차 여부를 검사해요. 과거의 유효한 관측을 현재 체결 가능성으로 해석하지 않아요. 빈 호가는 자료 부족으로 남겨요.
- BLS 관측 월과 실제 발표 시점은 달라요. 현재 빈티지를 과거에 알았던 자료로 소급하지 않아요. Fed RSS는 기업·산업·지정학 뉴스 전반을 포괄하지 않아요.

## 원본과 제한된 분석 입력

시장 스냅샷의 `research`는 `mara.research/1.0.0` 계약을 따라요. 각 호출의 `collected`, `failed`, `skipped`, 대상, 이유, fact ID, 원본 영수증을 기록해요. 실패한 공급자의 응답 형식 변화는 해당 도구의 실패로 격리해요. 기본 위험 검증과 `actionable_risky_allocation=false`를 자료 수집 성공만으로 해제하지 않아요.

공공 HTTP 요청은 최대 48회이고 새 요청 시작은 150초까지예요. 각 요청은 10초 제한, 응답은 8MB 제한이에요. 전체 수집이 180초를 넘으면 다음 도구를 건너뛰어요. 기업 재무는 누적 36,000자까지, 전체 fact는 44,000자까지 채택해요. 초과한 자료는 원본을 남기고 활성 입력에서 제외한 이유를 표시해요.

모델에는 역할별 projection을 전달해요. 재무 관점에는 수치·기간을 유지하고 Bogle·회고·기억에는 세부 재무 표를 줄여요. 이전 시장 자료는 최대 8,000자까지 요약하고 제외한 fact ID를 명시해요. 이전 제안·관점별 이유·반대 의견·회고는 이 시장 자료 예산으로 잘라내지 않아요. 연구 자료를 포함하는 전체 payload는 160,000자 제한이에요. 원본 시장 스냅샷과 저장된 에이전트 입력은 수정하지 않아요.

`GET /api/contracts/research`에서 계약을 읽을 수 있어요. 화면의 시장 근거 컴포넌트에서 도구별 상태·실제 사실·원본을 탐색해요. `GET /api/research-raw/{run_id}/{sha256}`는 현재 사용자의 실행이 참조한 원본만 반환하고 해시를 검증해요. `provenance`와 `all_occurrences`로 동일 원본의 조회 영수증을 확인할 수 있어요.

확장 시에는 공급자 파서를 `research_sources.py`에, 허용된 읽기 경로와 예산·실패 처리를 `research.py`에 추가해요. `TOOLS` 역할 책임, 가이드, 시점·단위·결측 테스트를 함께 갱신해요. 새 데이터의 수집과 투자 검증 통과는 별개예요.

## 공식 출처

- [SEC EDGAR API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [SEC 개발자 자료](https://www.sec.gov/about/developer-resources), [SEC ticker 목록](https://www.sec.gov/files/company_tickers.json)
- [Treasury 금리 자료](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)
- [BLS API](https://www.bls.gov/developers/)
- [Federal Reserve RSS](https://www.federalreserve.gov/feeds/feeds.htm)
- [iShares ITOT](https://www.ishares.com/us/products/239724/ishares-core-s-p-total-u-s-stock-market-etf), [iShares IVV](https://www.ishares.com/us/products/239726/ishares-core-s-p-500-etf)
- [토스증권 시장 자료](https://developers.tossinvest.com/docs/market-data), [공식 OpenAPI 계약](https://openapi.tossinvest.com/openapi-docs/latest/openapi.json)
