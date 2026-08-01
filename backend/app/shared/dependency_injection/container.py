"""Explicit dependency injection container.

Deliberately NOT a service locator: callers must ask for a specific typed
key (a `Type[T]`), and every registration is explicit — nothing is
auto-wired or resolved by convention/reflection. There is no global
container instance in this module; the application composition root (see
Milestone 1C's app factory) constructs exactly one `Container`, registers
every dependency in it explicitly, and passes it (or values resolved from
it) down through function parameters / FastAPI `Depends`. Nothing here
reaches into a global to fetch a dependency implicitly — that is what
distinguishes an explicit container from a service locator anti-pattern.
"""
from collections.abc import Callable
from typing import TypeVar, cast

T = TypeVar("T")

_Factory = Callable[[], T]


class DependencyNotRegisteredError(KeyError):
    """Raised when resolving a type that was never registered."""


class Container:
    """A small, explicit, typed dependency registry.

    Two registration modes:
      - `register_instance(Type, value)`: the exact same object is
        returned on every `resolve()` call (use for stateless, thread-safe
        singletons constructed once at startup — e.g. an `EventBus`).
      - `register_factory(Type, factory)`: `factory()` is invoked fresh on
        every `resolve()` call (use for anything with per-request or
        per-transaction lifetime — e.g. a database session).
    """

    def __init__(self) -> None:
        self._instances: dict[type, object] = {}
        self._factories: dict[type, _Factory[object]] = {}

    def register_instance(self, key: type[T], instance: T) -> None:
        self._instances[key] = instance

    def register_factory(self, key: type[T], factory: Callable[[], T]) -> None:
        self._factories[key] = cast(_Factory[object], factory)

    def resolve(self, key: type[T]) -> T:
        if key in self._instances:
            return cast(T, self._instances[key])
        if key in self._factories:
            return cast(T, self._factories[key]())
        raise DependencyNotRegisteredError(
            f"No instance or factory registered for '{key.__module__}.{key.__qualname__}'"
        )

    def is_registered(self, key: type[object]) -> bool:
        return key in self._instances or key in self._factories
