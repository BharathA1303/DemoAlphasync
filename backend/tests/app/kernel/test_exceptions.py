import pytest

from app.kernel.exceptions import (
    DomainException,
    InsufficientMarginException,
    InvalidStateTransitionException,
    RiskViolationException,
)


class TestDomainExceptionHierarchy:
    @pytest.mark.parametrize(
        "exception_type",
        [InvalidStateTransitionException, RiskViolationException, InsufficientMarginException],
    )
    def test_all_domain_exceptions_derive_from_domain_exception(self, exception_type: type) -> None:
        assert issubclass(exception_type, DomainException)

    def test_domain_exception_derives_from_exception(self) -> None:
        assert issubclass(DomainException, Exception)

    def test_can_be_raised_and_caught_by_base_type(self) -> None:
        with pytest.raises(DomainException):
            raise RiskViolationException("order exceeds risk limit")

    def test_carries_message(self) -> None:
        try:
            raise InsufficientMarginException("not enough margin")
        except DomainException as exc:
            assert str(exc) == "not enough margin"
