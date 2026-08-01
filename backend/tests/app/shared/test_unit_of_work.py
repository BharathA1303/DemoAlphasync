from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.kernel.primitives import BaseAggregateRoot, DomainEvent
from app.shared.event_bus import EventBus
from app.shared.transactional_outbox import (
    OutboxStatus,
    SqlAlchemyOutboxRepository,
    outbox_table,
)
from app.shared.unit_of_work import InMemoryUnitOfWork, SqlAlchemyUnitOfWork

SessionFactory = Callable[[], AsyncSession]


@dataclass(frozen=True)
class _OrderPlacedEvent(DomainEvent):
    order_id: str = ""


class _OrderAggregate(BaseAggregateRoot):
    def __init__(self) -> None:
        super().__init__()
        self.order_id = ""

    def place(self, order_id: str) -> None:
        self.order_id = order_id
        self._record_event(_OrderPlacedEvent(order_id=order_id))


def _recording_handler(sink: list[str]) -> Callable[[_OrderPlacedEvent], Awaitable[None]]:
    """Build an async EventBus handler that appends each event's order_id
    to `sink` — EventBus.publish requires an awaitable handler."""

    async def handler(event: _OrderPlacedEvent) -> None:
        sink.append(event.order_id)

    return handler


@pytest.fixture
async def session_factory() -> AsyncGenerator[SessionFactory, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(outbox_table.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


class TestInMemoryUnitOfWork:
    async def test_commit_publishes_events_from_registered_aggregates(self) -> None:
        bus = EventBus()
        received: list[str] = []

        async def handler(event: _OrderPlacedEvent) -> None:
            received.append(event.order_id)

        bus.subscribe(_OrderPlacedEvent, handler)

        async with InMemoryUnitOfWork(bus) as uow:
            order = _OrderAggregate()
            order.place("ord_1")
            uow.register_aggregate(order)
            await uow.commit()

        assert received == ["ord_1"]

    async def test_events_are_cleared_from_aggregate_after_commit(self) -> None:
        bus = EventBus()
        order = _OrderAggregate()
        order.place("ord_1")

        async with InMemoryUnitOfWork(bus) as uow:
            uow.register_aggregate(order)
            await uow.commit()

        assert order.collect_uncommitted_events() == []

    async def test_exception_inside_context_triggers_rollback_and_no_events_published(self) -> None:
        bus = EventBus()
        received: list[str] = []
        bus.subscribe(_OrderPlacedEvent, _recording_handler(received))

        with pytest.raises(ValueError):
            async with InMemoryUnitOfWork(bus) as uow:
                order = _OrderAggregate()
                order.place("ord_1")
                uow.register_aggregate(order)
                raise ValueError("simulated failure before commit")

        assert received == []

    def test_registering_the_same_aggregate_twice_only_tracks_it_once(self) -> None:
        uow = InMemoryUnitOfWork(EventBus())
        order = _OrderAggregate()
        uow.register_aggregate(order)
        uow.register_aggregate(order)
        assert uow._tracked_aggregates == [order]


class TestSqlAlchemyUnitOfWork:
    async def test_commit_writes_outbox_row_in_same_transaction_and_relays_to_event_bus(
        self, session_factory: SessionFactory
    ) -> None:
        bus = EventBus()
        received: list[str] = []
        bus.subscribe(_OrderPlacedEvent, _recording_handler(received))

        async with SqlAlchemyUnitOfWork(session_factory, bus) as uow:
            order = _OrderAggregate()
            order.place("ord_1")
            uow.register_aggregate(order)
            await uow.commit()

        assert received == ["ord_1"]

        # The outbox row itself is durable in the database (not just an
        # in-memory list) — reading it back with a fresh session proves it,
        # and confirms it was explicitly marked PUBLISHED (not just absent
        # from the pending query for some other reason).
        async with session_factory() as verify_session:
            repo = SqlAlchemyOutboxRepository(verify_session)
            assert await repo.fetch_pending() == []

            row = (await verify_session.execute(select(outbox_table))).fetchone()
            assert row is not None
            assert row.status == OutboxStatus.PUBLISHED.value

    async def test_commit_marks_outbox_row_failed_when_a_subscriber_raises(
        self, session_factory: SessionFactory
    ) -> None:
        bus = EventBus()

        async def failing_subscriber(event: _OrderPlacedEvent) -> None:
            raise RuntimeError("streaming gateway unreachable")

        bus.subscribe(_OrderPlacedEvent, failing_subscriber)

        async with SqlAlchemyUnitOfWork(session_factory, bus) as uow:
            order = _OrderAggregate()
            order.place("ord_1")
            uow.register_aggregate(order)
            await uow.commit()  # must not raise even though the subscriber did

        async with session_factory() as verify_session:
            row = (await verify_session.execute(select(outbox_table))).fetchone()
            assert row is not None
            assert row.status == OutboxStatus.FAILED.value
            assert row.last_error is not None

    async def test_rollback_on_exception_leaves_no_outbox_row_and_publishes_nothing(
        self, session_factory: SessionFactory
    ) -> None:
        bus = EventBus()
        received: list[str] = []
        bus.subscribe(_OrderPlacedEvent, _recording_handler(received))

        with pytest.raises(RuntimeError):
            async with SqlAlchemyUnitOfWork(session_factory, bus) as uow:
                order = _OrderAggregate()
                order.place("ord_1")
                uow.register_aggregate(order)
                # Simulate a failure AFTER recording the event but BEFORE
                # commit() is called — proving atomicity: nothing must leak.
                raise RuntimeError("simulated failure before commit")

        assert received == [], "No event should ever reach the EventBus if commit() never ran"

        async with session_factory() as verify_session:
            repo = SqlAlchemyOutboxRepository(verify_session)
            assert await repo.fetch_pending() == []

    async def test_multiple_aggregates_each_contribute_their_events_on_commit(
        self, session_factory: SessionFactory
    ) -> None:
        bus = EventBus()
        received: list[str] = []
        bus.subscribe(_OrderPlacedEvent, _recording_handler(received))

        async with SqlAlchemyUnitOfWork(session_factory, bus) as uow:
            order_one = _OrderAggregate()
            order_one.place("ord_1")
            order_two = _OrderAggregate()
            order_two.place("ord_2")

            uow.register_aggregate(order_one)
            uow.register_aggregate(order_two)
            await uow.commit()

        assert sorted(received) == ["ord_1", "ord_2"]

    async def test_session_is_none_before_context_entry(self, session_factory: SessionFactory) -> None:
        uow = SqlAlchemyUnitOfWork(session_factory, EventBus())
        assert uow.session is None

    async def test_registering_the_same_aggregate_twice_only_tracks_it_once(
        self, session_factory: SessionFactory
    ) -> None:
        async with SqlAlchemyUnitOfWork(session_factory, EventBus()) as uow:
            order = _OrderAggregate()
            uow.register_aggregate(order)
            uow.register_aggregate(order)
            assert uow._tracked_aggregates == [order]
            await uow.commit()

    async def test_commit_with_no_registered_aggregates_is_a_no_op(
        self, session_factory: SessionFactory
    ) -> None:
        async with SqlAlchemyUnitOfWork(session_factory, EventBus()) as uow:
            await uow.commit()  # must not raise with nothing registered

        async with session_factory() as verify_session:
            repo = SqlAlchemyOutboxRepository(verify_session)
            assert await repo.fetch_pending() == []

    async def test_commit_with_an_aggregate_that_recorded_no_events_writes_no_outbox_rows(
        self, session_factory: SessionFactory
    ) -> None:
        async with SqlAlchemyUnitOfWork(session_factory, EventBus()) as uow:
            order = _OrderAggregate()  # never calls .place(), so no events recorded
            uow.register_aggregate(order)
            await uow.commit()

        async with session_factory() as verify_session:
            repo = SqlAlchemyOutboxRepository(verify_session)
            assert await repo.fetch_pending() == []
