# Data Layer

외부 데이터 수집 및 정규화를 담당하는 레이어입니다.

## 책임 (Responsibilities)

- MCP Tools를 통한 외부 데이터 수집
- 데이터 소스별 어댑터 구현
- 수집된 데이터의 정규화 및 검증
- 데이터 캐싱 및 갱신 로직

## 주요 모듈

### `collectors/`
각 데이터 소스별 수집기 구현
- `news_collector.py`: 뉴스 데이터 수집 (Financial Times, Bloomberg, etc.)
- `report_collector.py`: 전문가 리포트 수집 (PDF 파싱 포함)
- `price_collector.py`: 주가 및 ETF 가격 데이터 수집
- `economic_collector.py`: 거시 경제 지표 수집 (금리, 인플레이션, 고용 등)

### `normalizers/`
데이터 정규화 및 변환
- `schema.py`: 공통 데이터 스키마 정의
- `text_normalizer.py`: 텍스트 데이터 정규화 (뉴스, 리포트)
- `timeseries_normalizer.py`: 시계열 데이터 정규화 (가격, 지표)

### `cache/`
데이터 캐싱 로직
- `cache_manager.py`: 캐시 저장/조회/갱신
- `cache_policy.py`: 데이터 소스별 캐시 정책 (TTL 설정)

## 데이터 흐름

```
MCP Tools → Collectors → Normalizers → Cache → Agent Layers
```

## 설정 예시

```yaml
data_sources:
  news:
    providers: ["financial_times", "bloomberg", "reuters"]
    update_frequency: "1h"
    cache_ttl: 3600

  prices:
    providers: ["yahoo_finance", "alpha_vantage"]
    update_frequency: "15m"
    cache_ttl: 900

  reports:
    providers: ["mcp_pdf_reader"]
    update_frequency: "daily"
    cache_ttl: 86400
```

## 구현 가이드라인

1. **모든 Collector는 `BaseCollector` 추상 클래스를 상속**
   - `collect()`: 데이터 수집
   - `validate()`: 수집된 데이터 검증
   - `transform()`: 정규화된 형태로 변환

2. **에러 핸들링**
   - API 장애 시 재시도 로직 (exponential backoff)
   - 부분 실패 허용 (일부 소스 실패해도 계속 진행)

3. **캐싱 전략**
   - 자주 변하지 않는 데이터는 긴 TTL (리포트)
   - 실시간성이 중요한 데이터는 짧은 TTL (가격)

4. **로깅**
   - 수집 시작/종료 시각
   - 수집된 데이터 건수
   - 에러 발생 시 상세 로그
