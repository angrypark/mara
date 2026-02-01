# Data Layer

외부 데이터 수집, 분석 및 요약을 담당하는 레이어입니다.

## 책임 (Responsibilities)

- 뉴스, 리포트 등 외부 데이터 수집
- 가격 데이터 분석 및 기술적 지표 계산
- LLM 기반 텍스트 요약 및 핵심 인사이트 추출
- 데이터 캐싱 및 갱신 로직

## 구조

```
data/
├── collectors/          # 데이터 수집기
│   ├── news.py          # 뉴스 수집 (RSS, 웹 스크래핑)
│   └── report.py        # 전문가 리포트 수집
├── analyzers/           # 데이터 분석기
│   ├── price.py         # 가격 변동 분석 (yfinance)
│   └── sentiment.py     # 감성 분석
└── summarizer.py        # 텍스트 요약 (LLM 기반)
```

## 주요 모듈

### `collectors/`

각 데이터 소스별 수집기 구현

- **news.py**: 뉴스 데이터 수집 (RSS, 웹 스크래핑)
- **report.py**: 전문가 리포트 수집 (공개 PDF)

### `analyzers/`

데이터 분석 및 지표 계산

- **price.py**: yfinance 기반 가격 변동 추이, 기술적 지표 분석
- **sentiment.py**: 텍스트 감성 분석

### `summarizer.py`

LLM 기반 텍스트 요약, 핵심 인사이트 추출

## 데이터 흐름

```
External Sources → Collectors → Analyzers/Summarizer → DataState → Perspective Agents
```

## Output: DataState

Data Layer의 출력은 `DataState`로 다음 정보를 포함합니다:

- 시장 데이터 요약
- 가격 변동 분석 결과
- 핵심 인사이트 (뉴스/리포트에서 추출)

## 에러 핸들링

| 컴포넌트 | 재시도 횟수 | 백오프 전략 | Timeout |
|----------|-------------|-------------|---------|
| Market Data (yfinance) | 2회 | Linear (2s, 4s) | 30s |

### Fallback 전략

- **Market Data 장애**: 캐시된 가격 데이터 사용 (1시간 이내), stale 데이터 경고 표시

## 구현 가이드라인

1. **모든 Collector는 BaseCollector 추상 클래스를 상속**
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

## 참고

> **Note**: 뉴스/리포트 수집은 Tool이 아닌 이 Data Layer에서 처리됩니다.
> Agent가 호출하는 Price Tool, Backtest Tool 등은 `src/tools/`에 위치합니다.
