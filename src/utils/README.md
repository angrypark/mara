# Utils

공통으로 사용되는 유틸리티 함수 및 헬퍼 모듈입니다.

## 구조

```
utils/
├── llm.py               # LLM 클라이언트 (Anthropic)
├── cache.py             # 캐싱 유틸리티
└── logging.py           # 로깅 설정
```

## 주요 모듈

### 1. LLM Client (`llm.py`)

Anthropic Claude API 호출을 위한 래퍼

```python
from src.utils.llm import LLMClient

client = LLMClient()
response = await client.generate(
    prompt="Analyze the current market conditions",
    system="You are a financial analyst",
    temperature=0.3
)
```

**특징**:
- 재시도 로직 (Exponential backoff)
- Rate limiting 처리
- 응답 캐싱 (선택적)

### 2. Cache (`cache.py`)

API 응답 및 데이터 캐싱

```python
from src.utils.cache import SimpleCache
from pathlib import Path

cache = SimpleCache(Path("data/cache"))

# 캐시 조회 (TTL 1시간)
data = cache.get("market_data", ttl=3600)

if data is None:
    data = fetch_market_data()
    cache.set("market_data", data)
```

**지원 백엔드**:
- SQLite (기본)
- Redis (선택)

### 3. Logging (`logging.py`)

구조화된 로깅 설정

```python
from src.utils.logging import setup_logger
from pathlib import Path

logger = setup_logger("perspective_agent", Path("outputs/logs"))
logger.info("Starting analysis")
logger.error("Failed to fetch data", exc_info=True)
```

**특징**:
- 파일 + 콘솔 출력
- 일별 로그 파일 로테이션
- 구조화된 로그 포맷

## 에러 핸들링 정책

| 컴포넌트 | 재시도 횟수 | 백오프 전략 | Timeout |
|----------|-------------|-------------|---------|
| LLM API (Anthropic) | 3회 | Exponential (1s, 2s, 4s) | 60s |
| 캐시 조회 | 1회 | 없음 | 5s |

## 사용 예시

```python
from src.utils.llm import LLMClient
from src.utils.cache import SimpleCache
from src.utils.logging import setup_logger
from pathlib import Path

# 로깅 설정
logger = setup_logger("my_agent", Path("outputs/logs"))

# 캐시 설정
cache = SimpleCache(Path("data/cache"))

# LLM 클라이언트
llm = LLMClient()

async def analyze():
    logger.info("Starting analysis")

    # 캐시 확인
    cached_result = cache.get("analysis_result", ttl=3600)
    if cached_result:
        logger.info("Cache hit!")
        return cached_result

    # LLM 호출
    logger.info("Cache miss, calling LLM")
    result = await llm.generate(
        prompt="Analyze market conditions",
        system="You are a financial analyst"
    )

    # 캐시 저장
    cache.set("analysis_result", result)
    logger.info("Analysis complete")

    return result
```

## 구현 가이드라인

1. **싱글톤 패턴**
   - LLM 클라이언트는 싱글톤으로 관리
   - 불필요한 인스턴스 생성 방지

2. **에러 전파**
   - 재시도 후에도 실패 시 예외 발생
   - 상위 레이어에서 처리

3. **캐시 키 네이밍**
   - 명확한 네이밍 규칙 사용
   - 예: `{module}_{function}_{params_hash}`

4. **로그 레벨**
   - DEBUG: 상세 디버깅 정보
   - INFO: 일반 실행 정보
   - WARNING: 주의가 필요한 상황
   - ERROR: 에러 발생
