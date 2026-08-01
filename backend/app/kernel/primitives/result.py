from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")
E = TypeVar("E", bound=Exception)


@dataclass(frozen=True)
class Result(Generic[T, E]):
    """Result primitive for explicit success/failure handling without raw exception throwing."""

    _value: T | None = None
    _error: E | None = None
    _is_success: bool = True

    @classmethod
    def ok(cls, value: T) -> "Result[T, E]":
        return cls(_value=value, _error=None, _is_success=True)

    @classmethod
    def fail(cls, error: E) -> "Result[T, E]":
        return cls(_value=None, _error=error, _is_success=False)

    @property
    def is_success(self) -> bool:
        return self._is_success

    @property
    def is_failure(self) -> bool:
        return not self._is_success

    def value(self) -> T:
        if not self._is_success or self._value is None:
            raise ValueError(f"Cannot retrieve value from failed Result: {self._error}")
        return self._value

    def error(self) -> E:
        if self._is_success or self._error is None:
            raise ValueError("Cannot retrieve error from successful Result")
        return self._error
