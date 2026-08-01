class DomainException(Exception):
    """Base exception for all domain business rule violations."""

    pass


class InvalidStateTransitionException(DomainException):
    """Raised when an aggregate state transition violates state machine rules."""

    pass


class RiskViolationException(DomainException):
    """Raised when a command violates pre-trade or post-trade risk rules."""

    pass


class InsufficientMarginException(DomainException):
    """Raised when a portfolio lacks available capital to cover margin requirements."""

    pass
