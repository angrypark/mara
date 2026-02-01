# Research Agent

Perspective Agent의 요청에 따라 웹 검색 및 심층 조사를 수행하는 Agent입니다.

## 책임 (Responsibilities)

- Perspective Agent로부터 조사 요청 수신
- 웹 검색을 통한 최신 정보 수집
- 신규 섹터/테마 발굴
- 조사 결과를 Perspective Agent에 반환

## 구조

```
research/
└── agent.py             # 웹 검색, 심층 조사 수행
```

## Multi-hop 통신 흐름

Research Agent는 Perspective Agent와 최대 3회까지 반복 소통합니다.

```
┌─────────────────────┐         ┌─────────────────────┐
│  Perspective Agent  │         │   Research Agent    │
└─────────┬───────────┘         └──────────┬──────────┘
          │                                │
          │  1. 조사 요청                  │
          │  "AI 반도체 최신 동향"         │
          │──────────────────────────────▶│
          │                                │
          │  2. 조사 결과 반환             │
          │◀──────────────────────────────│
          │                                │
          │  3. 추가 조사 요청             │
          │  "NVIDIA 경쟁사 동향"          │
          │──────────────────────────────▶│
          │                                │
          │  4. 추가 결과 반환             │
          │◀──────────────────────────────│
          │                                │
          ▼                                ▼
```

## 조사 유형

### 1. 테마/섹터 조사

새로운 투자 테마나 섹터 트렌드 발굴

```python
# 요청 예시
{
    "query_type": "theme_research",
    "query": "2025년 AI 인프라 투자 트렌드",
    "context": "현재 기술 섹터 비중 30%"
}

# 응답 예시
{
    "findings": [
        "AI 데이터센터 전력 수요 급증으로 에너지 섹터 주목",
        "엣지 AI 칩셋 시장 확대 예상",
        "AI 메모리 수요 증가로 HBM 관련주 강세"
    ],
    "relevant_tickers": ["NVDA", "AMD", "MRVL", "MU"],
    "sources": ["Bloomberg", "Reuters", "Company Reports"]
}
```

### 2. 기업 분석

특정 기업에 대한 심층 조사

```python
# 요청 예시
{
    "query_type": "company_research",
    "query": "NVIDIA의 최근 실적 및 전망",
    "context": "AI 반도체 시장 리더"
}
```

### 3. 거시경제 조사

거시경제 이벤트나 정책 변화 조사

```python
# 요청 예시
{
    "query_type": "macro_research",
    "query": "Fed 금리 정책 전망 2025",
    "context": "현재 금리 4.5%"
}
```

## 에러 핸들링

| 컴포넌트 | 재시도 횟수 | 백오프 전략 | Timeout |
|----------|-------------|-------------|---------|
| Research Agent 웹 검색 | 2회 | Linear (1s, 2s) | 20s |

### Fallback 전략

Research Agent가 실패하면:
1. Perspective Agent에 `research_failed` 플래그 전달
2. Perspective Agent는 자체 분석으로 fallback

## Output Schema

```python
class ResearchResult(BaseModel):
    """Research Agent 출력"""
    query: str                        # 원본 조사 요청
    findings: list[str]               # 조사 결과 요약
    relevant_tickers: list[str]       # 관련 종목
    sources: list[str]                # 참조 소스
    confidence: float                 # 결과 신뢰도 (0-1)
    timestamp: datetime
```

## 구현 가이드라인

1. **소스 다양화**
   - 단일 소스에 의존하지 않음
   - 여러 뉴스/리포트 소스에서 교차 검증

2. **최신 정보 우선**
   - 가능한 최신 정보를 우선적으로 수집
   - 날짜 정보 명시

3. **객관성 유지**
   - 다양한 관점의 의견 수집
   - 편향된 정보 필터링

4. **출처 명시**
   - 모든 정보에 출처 명시
   - Perspective Agent가 검증 가능하도록
