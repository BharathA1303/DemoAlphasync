from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_LIMIT = "STOP_LOSS_LIMIT"


class OrderStatus(str, Enum):
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    OPEN = "OPEN"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    RISK_REJECTED = "RISK_REJECTED"
    EXPIRED = "EXPIRED"


class SessionEnvironment(str, Enum):
    LIVE = "LIVE"
    PAPER = "PAPER"
    REPLAY = "REPLAY"
    BACKTEST = "BACKTEST"
