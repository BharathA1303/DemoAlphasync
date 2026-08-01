import pytest

from app.shared.dependency_injection import Container, DependencyNotRegisteredError


class _Greeter:
    def greet(self) -> str:
        return "hello"


class _CountingFactory:
    """Test double that records how many times it was invoked, to verify
    factory-vs-instance lifetime semantics."""

    def __init__(self) -> None:
        self.call_count = 0

    def __call__(self) -> _Greeter:
        self.call_count += 1
        return _Greeter()


class TestContainer:
    def test_register_instance_then_resolve_returns_same_object(self) -> None:
        container = Container()
        instance = _Greeter()

        container.register_instance(_Greeter, instance)

        assert container.resolve(_Greeter) is instance

    def test_register_factory_invokes_factory_on_each_resolve(self) -> None:
        container = Container()
        factory = _CountingFactory()
        container.register_factory(_Greeter, factory)

        first = container.resolve(_Greeter)
        second = container.resolve(_Greeter)

        assert factory.call_count == 2
        assert first is not second

    def test_resolve_unregistered_type_raises(self) -> None:
        container = Container()
        with pytest.raises(DependencyNotRegisteredError):
            container.resolve(_Greeter)

    def test_is_registered_reflects_instance_registration(self) -> None:
        container = Container()
        assert not container.is_registered(_Greeter)
        container.register_instance(_Greeter, _Greeter())
        assert container.is_registered(_Greeter)

    def test_is_registered_reflects_factory_registration(self) -> None:
        container = Container()
        container.register_factory(_Greeter, _Greeter)
        assert container.is_registered(_Greeter)

    def test_instance_registration_takes_priority_over_factory(self) -> None:
        """If both an instance and a factory are registered for the same
        key, resolve() must be deterministic — instance wins, since it's
        the more specific/explicit registration."""
        container = Container()
        instance = _Greeter()
        container.register_instance(_Greeter, instance)
        container.register_factory(_Greeter, _Greeter)

        assert container.resolve(_Greeter) is instance

    def test_no_module_level_global_container_exists(self) -> None:
        """Enforces 'no global state, no service locator, no hidden
        singleton': the container module must not export a pre-built
        Container instance — only the class."""
        import app.shared.dependency_injection.container as container_module

        for name in dir(container_module):
            value = getattr(container_module, name)
            assert not isinstance(value, Container), (
                f"Found a module-level Container instance '{name}' — "
                "the container must always be constructed explicitly by the caller."
            )
