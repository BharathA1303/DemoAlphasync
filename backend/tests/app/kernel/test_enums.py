from app.kernel.enums import OrderSide, OrderStatus, OrderType, SessionEnvironment


class TestOrderSide:
    def test_members(self) -> None:
        assert {member.value for member in OrderSide} == {"BUY", "SELL"}

    def test_is_str_enum(self) -> None:
        assert OrderSide.BUY == "BUY"
        assert isinstance(OrderSide.BUY, str)


class TestOrderType:
    def test_members(self) -> None:
        assert {member.value for member in OrderType} == {
            "MARKET",
            "LIMIT",
            "STOP_LOSS",
            "STOP_LOSS_LIMIT",
        }


class TestOrderStatus:
    def test_members(self) -> None:
        assert {member.value for member in OrderStatus} == {
            "PENDING_SUBMISSION",
            "SUBMITTED",
            "OPEN",
            "PARTIAL_FILL",
            "FILLED",
            "CANCELLED",
            "REJECTED",
            "RISK_REJECTED",
            "EXPIRED",
        }


class TestSessionEnvironment:
    def test_members(self) -> None:
        assert {member.value for member in SessionEnvironment} == {
            "LIVE",
            "PAPER",
            "REPLAY",
            "BACKTEST",
        }
