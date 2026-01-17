# Utils

공통으로 사용되는 유틸리티 함수 및 헬퍼 모듈입니다.

## 주요 모듈

### 1. Logging (`logging.py`)

구조화된 로깅 설정:

```python
import logging
from pathlib import Path
from datetime import datetime

def setup_logger(
    name: str,
    log_dir: Path,
    level: int = logging.INFO
) -> logging.Logger:
    """
    구조화된 로거 설정

    Args:
        name: 로거 이름
        log_dir: 로그 파일 저장 경로
        level: 로그 레벨

    Returns:
        설정된 Logger 객체
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 파일 핸들러
    log_file = log_dir / f"{name}_{datetime.now():%Y%m%d}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)

    # 포맷터
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    return logger

# 사용 예시
logger = setup_logger("macro_agent", Path("outputs/logs"))
logger.info("Starting macro analysis")
```

### 2. Metrics (`metrics.py`)

금융 메트릭 계산:

```python
import numpy as np
import pandas as pd

def calculate_sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.04
) -> float:
    """Sharpe Ratio 계산"""
    excess_returns = returns - risk_free_rate / 252
    return np.sqrt(252) * excess_returns.mean() / excess_returns.std()

def calculate_max_drawdown(returns: pd.Series) -> float:
    """Max Drawdown 계산"""
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    return drawdown.min()

def calculate_sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.04
) -> float:
    """Sortino Ratio (하방 변동성만 고려)"""
    excess_returns = returns - risk_free_rate / 252
    downside_returns = excess_returns[excess_returns < 0]
    downside_std = downside_returns.std()
    return np.sqrt(252) * excess_returns.mean() / downside_std

def calculate_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Value at Risk (VaR)"""
    return returns.quantile(1 - confidence)

def calculate_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    """Conditional VaR (CVaR) - VaR 초과 시 평균 손실"""
    var = calculate_var(returns, confidence)
    return returns[returns < var].mean()
```

### 3. Portfolio Optimization (`portfolio.py`)

포트폴리오 최적화 유틸리티:

```python
import cvxpy as cp
import numpy as np
from typing import Dict, List

def optimize_portfolio(
    expected_returns: np.ndarray,
    cov_matrix: np.ndarray,
    constraints: Dict,
    objective: str = "sharpe"
) -> np.ndarray:
    """
    Mean-Variance Optimization

    Args:
        expected_returns: 각 자산의 기대 수익률
        cov_matrix: 공분산 행렬
        constraints: 제약 조건
        objective: 목적 함수 ("sharpe", "min_variance", "max_return")

    Returns:
        최적 가중치 배열
    """
    n_assets = len(expected_returns)
    weights = cp.Variable(n_assets)

    # 제약 조건
    constraints_list = [
        cp.sum(weights) == 1,  # 가중치 합 = 1
        weights >= 0  # 숏 금지
    ]

    # 추가 제약
    if "max_single_asset" in constraints:
        constraints_list.append(
            weights <= constraints["max_single_asset"]
        )

    # 목적 함수
    if objective == "sharpe":
        portfolio_return = expected_returns @ weights
        portfolio_risk = cp.quad_form(weights, cov_matrix)
        objective_func = cp.Maximize(portfolio_return / cp.sqrt(portfolio_risk))

    elif objective == "min_variance":
        portfolio_risk = cp.quad_form(weights, cov_matrix)
        objective_func = cp.Minimize(portfolio_risk)

    elif objective == "max_return":
        portfolio_return = expected_returns @ weights
        objective_func = cp.Maximize(portfolio_return)

        # 리스크 제약 추가
        if "max_volatility" in constraints:
            portfolio_risk = cp.quad_form(weights, cov_matrix)
            constraints_list.append(
                portfolio_risk <= constraints["max_volatility"] ** 2
            )

    # 최적화 실행
    problem = cp.Problem(objective_func, constraints_list)
    problem.solve()

    return weights.value
```

### 4. Data Validation (`validation.py`)

데이터 검증 유틸리티:

```python
import pandas as pd
from typing import List

def validate_price_data(df: pd.DataFrame) -> bool:
    """
    가격 데이터 검증

    - 결측치 확인
    - 이상치 확인 (일일 변동 > 20%)
    - 중복 날짜 확인
    """
    # 결측치
    if df.isnull().any().any():
        missing = df.isnull().sum()
        print(f"Missing values found: {missing}")
        return False

    # 이상치
    returns = df.pct_change()
    outliers = (returns.abs() > 0.20).any(axis=1)
    if outliers.any():
        print(f"Outliers found on dates: {df.index[outliers].tolist()}")
        return False

    # 중복
    if df.index.duplicated().any():
        print("Duplicate dates found")
        return False

    return True

def clean_price_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    가격 데이터 클리닝

    - Forward fill로 결측치 처리
    - 이상치 제거 (median 값으로 대체)
    """
    # 결측치
    df = df.fillna(method='ffill')

    # 이상치
    returns = df.pct_change()
    outliers = returns.abs() > 0.20

    for col in df.columns:
        mask = outliers[col]
        if mask.any():
            median_value = df[col].rolling(5, center=True).median()
            df.loc[mask, col] = median_value[mask]

    return df
```

### 5. Text Processing (`text.py`)

텍스트 처리 유틸리티 (뉴스, 리포트 분석용):

```python
import re
from typing import List

def extract_key_sentences(text: str, keywords: List[str], context: int = 1) -> List[str]:
    """
    키워드가 포함된 문장 추출

    Args:
        text: 원본 텍스트
        keywords: 찾을 키워드 리스트
        context: 전후 문장 개수

    Returns:
        관련 문장 리스트
    """
    sentences = re.split(r'[.!?]+', text)
    relevant = []

    for i, sent in enumerate(sentences):
        if any(keyword.lower() in sent.lower() for keyword in keywords):
            start = max(0, i - context)
            end = min(len(sentences), i + context + 1)
            relevant.extend(sentences[start:end])

    return list(set(relevant))

def summarize_with_llm(text: str, max_length: int = 500) -> str:
    """
    LLM을 활용한 텍스트 요약
    """
    # Anthropic API 호출
    from anthropic import Anthropic

    client = Anthropic()
    response = client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=max_length,
        messages=[{
            "role": "user",
            "content": f"Summarize the following text in {max_length} characters:\n\n{text}"
        }]
    )

    return response.content[0].text
```

### 6. Caching (`cache.py`)

간단한 캐싱 유틸리티:

```python
import pickle
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Optional

class SimpleCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str, ttl: int = 3600) -> Optional[Any]:
        """
        캐시 조회

        Args:
            key: 캐시 키
            ttl: Time to Live (초)

        Returns:
            캐시된 값 또는 None
        """
        cache_file = self.cache_dir / f"{key}.pkl"

        if not cache_file.exists():
            return None

        # TTL 체크
        file_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if datetime.now() - file_time > timedelta(seconds=ttl):
            cache_file.unlink()  # 만료된 캐시 삭제
            return None

        with open(cache_file, 'rb') as f:
            return pickle.load(f)

    def set(self, key: str, value: Any):
        """캐시 저장"""
        cache_file = self.cache_dir / f"{key}.pkl"
        with open(cache_file, 'wb') as f:
            pickle.dump(value, f)

    def clear(self):
        """모든 캐시 삭제"""
        for cache_file in self.cache_dir.glob("*.pkl"):
            cache_file.unlink()
```

### 7. Date Utilities (`dates.py`)

날짜 처리 유틸리티:

```python
import pandas as pd
from datetime import datetime, timedelta

def get_trading_days(start: datetime, end: datetime) -> pd.DatetimeIndex:
    """
    거래일만 반환 (주말 제외)
    """
    dates = pd.date_range(start, end, freq='B')  # Business days
    return dates

def get_last_trading_day(date: datetime = None) -> datetime:
    """
    가장 최근 거래일 반환
    """
    if date is None:
        date = datetime.now()

    while date.weekday() >= 5:  # 토요일(5), 일요일(6)
        date -= timedelta(days=1)

    return date

def get_month_end(date: datetime = None) -> datetime:
    """
    월말 거래일 반환
    """
    if date is None:
        date = datetime.now()

    # 다음 달 1일
    next_month = (date.replace(day=1) + timedelta(days=32)).replace(day=1)
    # 하루 뺀 날짜 (이전 달 마지막 날)
    last_day = next_month - timedelta(days=1)

    return get_last_trading_day(last_day)
```

## 사용 예시

```python
from src.utils.metrics import calculate_sharpe_ratio, calculate_max_drawdown
from src.utils.cache import SimpleCache
from src.utils.logging import setup_logger

# 로깅 설정
logger = setup_logger("my_agent", Path("outputs/logs"))

# 캐시 사용
cache = SimpleCache(Path("data/cache"))
data = cache.get("market_data", ttl=3600)

if data is None:
    logger.info("Cache miss, fetching data...")
    data = fetch_market_data()
    cache.set("market_data", data)
else:
    logger.info("Cache hit!")

# 메트릭 계산
sharpe = calculate_sharpe_ratio(returns)
max_dd = calculate_max_drawdown(returns)
logger.info(f"Sharpe: {sharpe:.2f}, Max DD: {max_dd:.2%}")
```
