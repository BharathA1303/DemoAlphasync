import pytest
from dataclasses import dataclass
from app.kernel.primitives import Command, DomainEvent, BaseAggregateRoot
from app.shared.command_bus import CommandBus
from app.shared.event_bus import EventBus
from app.shared.uow import InMemoryUnitOfWork


@dataclass(frozen=True)
class DummyCommand(Command):
    payload: str = ""


@dataclass(frozen=True)
class DummyEvent(DomainEvent):
    info: str = ""


class DummyAggregate(BaseAggregateRoot):
    def do_action(self, info: str):
        self._record_event(DummyEvent(info=info))


@pytest.mark.asyncio
async def test_command_bus_dispatch():
    bus = CommandBus()
    handled_payload = []

    async def handle_dummy(cmd: DummyCommand):
        handled_payload.append(cmd.payload)
        return "SUCCESS"

    bus.register(DummyCommand, handle_dummy)
    res = await bus.dispatch(DummyCommand(payload="test_payload"))

    assert res == "SUCCESS"
    assert handled_payload == ["test_payload"]


@pytest.mark.asyncio
async def test_command_bus_duplicate_register_fails():
    bus = CommandBus()

    async def h1(cmd): pass
    async def h2(cmd): pass

    bus.register(DummyCommand, h1)
    with pytest.raises(ValueError):
        bus.register(DummyCommand, h2)


@pytest.mark.asyncio
async def test_event_bus_pub_sub():
    bus = EventBus()
    received_events = []

    async def subscriber1(evt: DummyEvent):
        received_events.append(f"sub1:{evt.info}")

    async def subscriber2(evt: DummyEvent):
        received_events.append(f"sub2:{evt.info}")

    bus.subscribe(DummyEvent, subscriber1)
    bus.subscribe(DummyEvent, subscriber2)

    await bus.publish(DummyEvent(info="event_data"))
    assert len(received_events) == 2
    assert "sub1:event_data" in received_events
    assert "sub2:event_data" in received_events


@pytest.mark.asyncio
async def test_unit_of_work_commit():
    event_bus = EventBus()
    published_events = []

    async def subscriber(evt: DummyEvent):
        published_events.append(evt.info)

    event_bus.subscribe(DummyEvent, subscriber)
    uow = InMemoryUnitOfWork(event_bus)

    agg = DummyAggregate()
    agg.do_action("action_1")
    agg.do_action("action_2")

    async with uow:
        uow.register_aggregate(agg)
        await uow.commit()

    assert published_events == ["action_1", "action_2"]
    # Aggregates should have no remaining uncommitted events after UoW commit
    assert len(agg.collect_uncommitted_events()) == 0
