from dataclasses import dataclass

import pytest

from app.kernel.primitives import BaseAggregateRoot, Command, DomainEvent, Result


@dataclass(frozen=True)
class _SamplePlaceOrderCommand(Command):
    order_id: str = ""


@dataclass(frozen=True)
class _SampleOrderPlacedEvent(DomainEvent):
    order_id: str = ""


class TestCommand:
    def test_auto_generates_command_id_with_prefix(self) -> None:
        command = _SamplePlaceOrderCommand(order_id="ord_1")
        assert command.command_id.startswith("cmd_")

    def test_auto_generates_correlation_id(self) -> None:
        command = _SamplePlaceOrderCommand(order_id="ord_1")
        assert command.correlation_id.startswith("corr_")

    def test_auto_generates_idempotency_key(self) -> None:
        command = _SamplePlaceOrderCommand(order_id="ord_1")
        assert command.idempotency_key.startswith("idem_")

    def test_default_version_is_1(self) -> None:
        assert _SamplePlaceOrderCommand(order_id="ord_1").version == 1

    def test_two_instances_get_distinct_ids(self) -> None:
        first = _SamplePlaceOrderCommand(order_id="ord_1")
        second = _SamplePlaceOrderCommand(order_id="ord_1")
        assert first.command_id != second.command_id
        assert first.correlation_id != second.correlation_id

    def test_is_immutable(self) -> None:
        command = _SamplePlaceOrderCommand(order_id="ord_1")
        with pytest.raises(AttributeError):
            command.order_id = "mutated"  # type: ignore[misc]

    def test_explicit_correlation_id_is_preserved(self) -> None:
        """A caller that already has a correlation id (e.g. propagated from
        an inbound HTTP request) must be able to set it explicitly rather
        than always getting a freshly minted one."""
        command = _SamplePlaceOrderCommand(order_id="ord_1", correlation_id="corr_from_http")
        assert command.correlation_id == "corr_from_http"


class TestDomainEvent:
    def test_auto_generates_event_id_with_prefix(self) -> None:
        event = _SampleOrderPlacedEvent(order_id="ord_1")
        assert event.event_id.startswith("evt_")

    def test_is_immutable(self) -> None:
        event = _SampleOrderPlacedEvent(order_id="ord_1")
        with pytest.raises(AttributeError):
            event.order_id = "mutated"  # type: ignore[misc]

    def test_correlation_id_can_be_propagated_from_command(self) -> None:
        command = _SamplePlaceOrderCommand(order_id="ord_1")
        event = _SampleOrderPlacedEvent(order_id="ord_1", correlation_id=command.correlation_id)
        assert event.correlation_id == command.correlation_id


class _SampleAggregate(BaseAggregateRoot):
    def __init__(self) -> None:
        super().__init__()
        self.order_id = ""

    def place(self, order_id: str) -> None:
        self.order_id = order_id
        self._record_event(_SampleOrderPlacedEvent(order_id=order_id))


class TestBaseAggregateRoot:
    def test_new_aggregate_has_no_uncommitted_events(self) -> None:
        aggregate = _SampleAggregate()
        assert aggregate.collect_uncommitted_events() == []

    def test_recording_an_event_makes_it_collectible(self) -> None:
        aggregate = _SampleAggregate()
        aggregate.place("ord_1")
        events = aggregate.collect_uncommitted_events()
        assert len(events) == 1
        assert isinstance(events[0], _SampleOrderPlacedEvent)
        assert events[0].order_id == "ord_1"

    def test_collect_clears_the_buffer(self) -> None:
        aggregate = _SampleAggregate()
        aggregate.place("ord_1")
        aggregate.collect_uncommitted_events()
        assert aggregate.collect_uncommitted_events() == []

    def test_multiple_events_are_collected_in_order(self) -> None:
        aggregate = _SampleAggregate()
        aggregate.place("ord_1")
        aggregate.place("ord_2")
        events = aggregate.collect_uncommitted_events()
        order_ids = [event.order_id for event in events if isinstance(event, _SampleOrderPlacedEvent)]
        assert order_ids == ["ord_1", "ord_2"]

    def test_aggregate_never_publishes_events_itself(self) -> None:
        """Per the frozen spec: 'Aggregates never publish events.' The
        aggregate has no reference to an EventBus at all, and
        `_record_event` only appends to a local list — there is no method
        on BaseAggregateRoot capable of publishing."""
        aggregate = _SampleAggregate()
        assert not hasattr(aggregate, "publish")
        assert not hasattr(aggregate, "event_bus")


class TestResult:
    def test_ok_is_success(self) -> None:
        result: Result[int, ValueError] = Result.ok(42)
        assert result.is_success
        assert not result.is_failure
        assert result.value() == 42

    def test_fail_is_failure(self) -> None:
        error = ValueError("boom")
        result: Result[int, ValueError] = Result.fail(error)
        assert result.is_failure
        assert not result.is_success
        assert result.error() is error

    def test_value_on_failed_result_raises(self) -> None:
        result: Result[int, ValueError] = Result.fail(ValueError("boom"))
        with pytest.raises(ValueError):
            result.value()

    def test_error_on_successful_result_raises(self) -> None:
        result: Result[int, ValueError] = Result.ok(42)
        with pytest.raises(ValueError):
            result.error()
