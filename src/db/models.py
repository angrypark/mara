"""
Database Models for MARA

Uses Pydantic for data validation and SQLAlchemy for ORM (optional).
For simplicity, starting with Pydantic models and raw SQL.
"""

from datetime import date, datetime
from typing import Optional, Dict, List, Any
from decimal import Decimal
from pydantic import BaseModel, Field
from enum import Enum


class FlowType(str, Enum):
    GROWTH = "growth"
    INCOME = "income"


class PortfolioType(str, Enum):
    CURRENT = "current"
    RECOMMENDED = "recommended"


class MarketRegime(str, Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    VOLATILE = "volatile"


class ExecutionStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================================================
# Models
# ============================================================================


class User(BaseModel):
    """사용자 정보"""

    user_id: str  # 'marv', 'parents'
    name: str
    profile: str  # 'growth', 'income'
    flow: FlowType
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class Portfolio(BaseModel):
    """포트폴리오 스냅샷"""

    portfolio_id: str  # UUID
    user_id: str
    snapshot_date: date
    portfolio_type: PortfolioType
    total_value: Decimal
    holdings: Dict[str, Any]  # {"SPY": {"shares": 100, "value": 45000}, ...}
    allocation: Dict[str, float]  # {"cash": 0.30, "XLK": 0.25, ...}
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        json_encoders = {Decimal: float}


class Prediction(BaseModel):
    """예측 결과"""

    prediction_id: str  # 'marv_2025-01-17'
    user_id: str
    flow: FlowType
    prediction_date: date

    # Input
    input_portfolio_id: str

    # Macro Analysis
    market_regime: Optional[MarketRegime] = None
    macro_insights: Optional[Dict[str, Any]] = None

    # Strategy
    recommended_strategy: Optional[str] = None
    target_allocation: Optional[Dict[str, float]] = None
    expected_return: Optional[Decimal] = None
    expected_volatility: Optional[Decimal] = None
    expected_sharpe: Optional[Decimal] = None
    expected_max_dd: Optional[Decimal] = None

    # Rebalancing
    rebalancing_method: Optional[str] = None
    rebalancing_actions: Optional[List[Dict[str, Any]]] = None

    # Report
    report_markdown: Optional[str] = None
    report_path: Optional[str] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_encoders = {Decimal: float}


class PerformanceResult(BaseModel):
    """실제 성과 분석 결과 (Retrospection)"""

    result_id: str
    prediction_id: str
    user_id: str

    # 분석 기간
    start_date: date
    end_date: date

    # 실제 성과
    actual_return: Decimal
    actual_volatility: Optional[Decimal] = None
    actual_sharpe: Optional[Decimal] = None
    actual_max_dd: Optional[Decimal] = None

    # 예측 vs 실제
    return_error: Decimal  # actual - expected
    prediction_accuracy: Decimal  # 0.0 to 1.0

    # 세부 분석
    sector_performance: Optional[Dict[str, float]] = None
    agent_attribution: Optional[Dict[str, Any]] = None

    # Metadata
    analyzed_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_encoders = {Decimal: float}


class AgentPerformance(BaseModel):
    """Agent별 누적 성과"""

    record_id: str
    user_id: str
    agent_name: str

    # 누적 통계
    total_predictions: int = 0
    accurate_predictions: int = 0
    accuracy_rate: Decimal = Decimal("0.0")

    # 최근 성과
    recent_accuracy: Optional[Decimal] = None

    # 가중치
    current_weight: Decimal
    recommended_weight: Optional[Decimal] = None

    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_encoders = {Decimal: float}


class ExecutionLog(BaseModel):
    """실행 로그"""

    log_id: str
    user_id: str
    flow: FlowType
    execution_date: datetime = Field(default_factory=datetime.now)

    status: ExecutionStatus
    layers_completed: List[str] = []

    error_message: Optional[str] = None
    execution_time_seconds: Optional[int] = None

    created_at: datetime = Field(default_factory=datetime.now)
