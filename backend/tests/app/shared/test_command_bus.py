from dataclasses import dataclass

import pytest

from app.kernel.primitives import Command
from app.shared.command_bus import CommandBus


@dataclass(frozen=True)
class _PlaceOrderCommand(Command):
    order_id: str = ""


@dataclass(frozen=True)
class _CancelOrderCommand(Command):
    order_id: str = ""


class TestCommandBus:
    async def test_register_then_dispatch_invokes_handler(self) -> None:
        bus = CommandBus()
        received: list[str] = []

        async def handler(command: _PlaceOrderCommand) -> str:
            received.append(command.order_id)
            return "handled"

        bus.register(_PlaceOrderCommand, handler)
        result = await bus.dispatch(_PlaceOrderCommand(order_id="ord_1"))

        assert result == "handled"
        assert received == ["ord_1"]

    async def test_dispatch_without_registered_handler_raises(self) -> None:
        bus = CommandBus()
        with pytest.raises(KeyError):
            await bus.dispatch(_PlaceOrderCommand(order_id="ord_1"))

    def test_registering_same_command_type_twice_raises(self) -> None:
        bus = CommandBus()

        async def handler_one(command: _PlaceOrderCommand) -> None:
            return None

        async def handler_two(command: _PlaceOrderCommand) -> None:
            return None

        bus.register(_PlaceOrderCommand, handler_one)
        with pytest.raises(ValueError):
            bus.register(_PlaceOrderCommand, handler_two)

    async def test_different_command_types_route_to_different_handlers(self) -> None:
        bus = CommandBus()
        calls: list[str] = []

        async def place_handler(command: _PlaceOrderCommand) -> None:
            calls.append(f"place:{command.order_id}")

        async def cancel_handler(command: _CancelOrderCommand) -> None:
            calls.append(f"cancel:{command.order_id}")

        bus.register(_PlaceOrderCommand, place_handler)
        bus.register(_CancelOrderCommand, cancel_handler)

        await bus.dispatch(_PlaceOrderCommand(order_id="ord_1"))
        await bus.dispatch(_CancelOrderCommand(order_id="ord_1"))

        assert calls == ["place:ord_1", "cancel:ord_1"]

    async def test_handler_exception_propagates_to_caller(self) -> None:
        """The CommandBus must not swallow handler errors — the caller
        (e.g. a REST endpoint) needs to see them to return the right
        response, per the frozen order flow (REST -> CommandBus -> Risk ->
        OrderAggregate -> ...)."""
        bus = CommandBus()

        async def failing_handler(command: _PlaceOrderCommand) -> None:
            raise ValueError("risk check failed")

        bus.register(_PlaceOrderCommand, failing_handler)

        with pytest.raises(ValueError, match="risk check failed"):
            await bus.dispatch(_PlaceOrderCommand(order_id="ord_1"))
