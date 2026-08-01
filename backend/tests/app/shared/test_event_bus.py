from dataclasses import dataclass

from app.kernel.primitives import DomainEvent
from app.shared.event_bus import EventBus


@dataclass(frozen=True)
class _OrderPlacedEvent(DomainEvent):
    order_id: str = ""


@dataclass(frozen=True)
class _OrderCancelledEvent(DomainEvent):
    order_id: str = ""


class TestEventBus:
    async def test_publish_with_no_subscribers_does_not_raise(self) -> None:
        bus = EventBus()
        await bus.publish(_OrderPlacedEvent(order_id="ord_1"))

    async def test_publish_with_no_subscribers_returns_true(self) -> None:
        bus = EventBus()
        assert await bus.publish(_OrderPlacedEvent(order_id="ord_1")) is True

    async def test_publish_returns_true_when_all_subscribers_succeed(self) -> None:
        bus = EventBus()

        async def handler(event: _OrderPlacedEvent) -> None:
            return None

        bus.subscribe(_OrderPlacedEvent, handler)
        assert await bus.publish(_OrderPlacedEvent(order_id="ord_1")) is True

    async def test_publish_returns_false_when_any_subscriber_raises(self) -> None:
        bus = EventBus()

        async def failing_handler(event: _OrderPlacedEvent) -> None:
            raise RuntimeError("boom")

        bus.subscribe(_OrderPlacedEvent, failing_handler)
        assert await bus.publish(_OrderPlacedEvent(order_id="ord_1")) is False

    async def test_single_subscriber_receives_event(self) -> None:
        bus = EventBus()
        received: list[str] = []

        async def handler(event: _OrderPlacedEvent) -> None:
            received.append(event.order_id)

        bus.subscribe(_OrderPlacedEvent, handler)
        await bus.publish(_OrderPlacedEvent(order_id="ord_1"))

        assert received == ["ord_1"]

    async def test_multiple_subscribers_all_receive_the_event(self) -> None:
        """Unlike CommandBus (single handler), EventBus is pub/sub — many
        independent consumers (Charts, Replay, Strategies, Streaming
        Gateway per the frozen market data flow) can react to one event."""
        bus = EventBus()
        received: list[str] = []

        async def subscriber_one(event: _OrderPlacedEvent) -> None:
            received.append(f"one:{event.order_id}")

        async def subscriber_two(event: _OrderPlacedEvent) -> None:
            received.append(f"two:{event.order_id}")

        bus.subscribe(_OrderPlacedEvent, subscriber_one)
        bus.subscribe(_OrderPlacedEvent, subscriber_two)
        await bus.publish(_OrderPlacedEvent(order_id="ord_1"))

        assert set(received) == {"one:ord_1", "two:ord_1"}

    async def test_subscribers_only_receive_their_own_event_type(self) -> None:
        bus = EventBus()
        placed_received: list[str] = []
        cancelled_received: list[str] = []

        async def on_placed(event: _OrderPlacedEvent) -> None:
            placed_received.append(event.order_id)

        async def on_cancelled(event: _OrderCancelledEvent) -> None:
            cancelled_received.append(event.order_id)

        bus.subscribe(_OrderPlacedEvent, on_placed)
        bus.subscribe(_OrderCancelledEvent, on_cancelled)
        await bus.publish(_OrderPlacedEvent(order_id="ord_1"))

        assert placed_received == ["ord_1"]
        assert cancelled_received == []

    async def test_one_failing_subscriber_does_not_prevent_others_from_running(self) -> None:
        """publish() uses asyncio.gather(..., return_exceptions=True) so a
        broken consumer (e.g. Streaming Gateway) can't block delivery to
        healthy ones (e.g. Portfolio recalculation)."""
        bus = EventBus()
        received: list[str] = []

        async def failing_handler(event: _OrderPlacedEvent) -> None:
            raise RuntimeError("streaming gateway down")

        async def healthy_handler(event: _OrderPlacedEvent) -> None:
            received.append(event.order_id)

        bus.subscribe(_OrderPlacedEvent, failing_handler)
        bus.subscribe(_OrderPlacedEvent, healthy_handler)

        await bus.publish(_OrderPlacedEvent(order_id="ord_1"))

        assert received == ["ord_1"]
