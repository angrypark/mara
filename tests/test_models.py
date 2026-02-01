"""Test database models."""

from datetime import date
from decimal import Decimal

from src.db.models import FlowType, Portfolio, PortfolioType, User


class TestUser:
    def test_create_user(self):
        user = User(
            user_id="marv",
            name="Marv",
            profile="growth",
            flow=FlowType.GROWTH,
        )
        assert user.user_id == "marv"
        assert user.flow == FlowType.GROWTH


class TestPortfolio:
    def test_create_portfolio(self):
        portfolio = Portfolio(
            portfolio_id="test-001",
            user_id="marv",
            snapshot_date=date(2025, 1, 17),
            portfolio_type=PortfolioType.CURRENT,
            total_value=Decimal("100000"),
            holdings={"SPY": {"shares": 100, "value": 45000}},
            allocation={"SPY": 0.45, "cash": 0.55},
        )
        assert portfolio.total_value == Decimal("100000")
        assert portfolio.allocation["SPY"] == 0.45
