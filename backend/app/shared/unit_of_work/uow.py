"""Unit of Work.

Per the frozen architecture: "UnitOfWork publishes events after commit" and
"Aggregates never publish events" — an aggregate only records events on
itself (`BaseAggregateRoot._record_event`); the UnitOfWork is the sole
place that turns those recorded-but-uncommitted events into durable outbox
rows and, after the surrounding transaction is durable, relays them onto
the EventBus.

Two implementations are provided:
  - `InMemoryUnitOfWork`: no real transaction/outbox — publishes directly
    to the EventBus on commit. Intended ONLY for fast unit tests of
    handlers/aggregates in isolation; never for production or integration
    tests that need durability guarantees.
  - `SqlAlchemyUnitOfWork`: backed by a real AsyncSession. Aggregate
    events are written to `outbox_messages` inside `commit()`'s database
    transaction, then relayed to the EventBus only after that transaction
    is durably committed — satisfying atomicity between "state changed"
    and "event will eventually be delivered".
"""
import logging
from collections.abc import Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.primitives.aggregate import BaseAggregateRoot
from app.kernel.primitives.event import DomainEvent
from app.shared.event_bus.event_bus import EventBus
from app.shared.transactional_outbox.outbox import build_outbox_message
from app.shared.transactional_outbox.sqlalchemy_outbox import SqlAlchemyOutboxRepository

logger = logging.getLogger(__name__)


class IUnitOfWork(Protocol):
    async def __aenter__(self) -> "IUnitOfWork": ...

    async def __aexit__(
        self, exc_type: type | None, exc_val: BaseException | None, traceback: object
    ) -> None: ...

    def register_aggregate(self, aggregate: BaseAggregateRoot) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class InMemoryUnitOfWork:
    """In-memory UnitOfWork for isolated unit tests. See module docstring —
    NOT durable, publishes directly to the EventBus with no outbox."""

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self._tracked_aggregates: list[BaseAggregateRoot] = []
        self._committed = False

    async def __aenter__(self) -> "InMemoryUnitOfWork":
        self._tracked_aggregates.clear()
        self._committed = False
        return self

    async def __aexit__(
        self, exc_type: type | None, exc_val: BaseException | None, traceback: object
    ) -> None:
        if exc_type is not None and not self._committed:
            await self.rollback()

    def register_aggregate(self, aggregate: BaseAggregateRoot) -> None:
        if aggregate not in self._tracked_aggregates:
            self._tracked_aggregates.append(aggregate)

    async def commit(self) -> None:
        """Commit aggregate state changes and publish accumulated outbox events."""
        events_to_publish = []
        for aggregate in self._tracked_aggregates:
            events_to_publish.extend(aggregate.collect_uncommitted_events())

        self._committed = True
        logger.debug(
            f"InMemoryUnitOfWork committed. Publishing {len(events_to_publish)} events directly (no outbox)."
        )

        for event in events_to_publish:
            await self.event_bus.publish(event)

    async def rollback(self) -> None:
        logger.warning("InMemoryUnitOfWork rolled back. Discarding tracked aggregates and their events.")
        self._tracked_aggregates.clear()
        self._committed = False


class SqlAlchemyUnitOfWork:
    """Database-transaction-backed UnitOfWork.

    Usage:
        async with SqlAlchemyUnitOfWork(session_factory, event_bus) as uow:
            order = OrderAggregate.place(...)                # records events on itself
            await order_repository(uow.session).add(order)   # persists using uow.session
            uow.register_aggregate(order)                    # marks it for event collection
            await uow.commit()                                # persists outbox rows + DB commit,
                                                                # THEN relays to EventBus

    `session` is exposed so repositories can share this UnitOfWork's
    transaction — repositories must never open their own session.
    """

    def __init__(self, session_factory: Callable[[], AsyncSession], event_bus: EventBus) -> None:
        self._session_factory = session_factory
        self.event_bus = event_bus
        self.session: AsyncSession | None = None
        self._tracked_aggregates: list[BaseAggregateRoot] = []
        self._committed = False

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        self.session = self._session_factory()
        self._tracked_aggregates = []
        self._committed = False
        return self

    async def __aexit__(
        self, exc_type: type | None, exc_val: BaseException | None, traceback: object
    ) -> None:
        assert self.session is not None
        try:
            if exc_type is not None and not self._committed:
                await self.rollback()
        finally:
            await self.session.close()

    def register_aggregate(self, aggregate: BaseAggregateRoot) -> None:
        if aggregate not in self._tracked_aggregates:
            self._tracked_aggregates.append(aggregate)

    async def commit(self) -> None:
        """Write outbox rows for every registered aggregate's uncommitted
        events INSIDE the same DB transaction as their own persisted state,
        commit that transaction, then relay the newly-committed outbox rows
        to the EventBus. If the DB commit fails, no event is ever
        published — atomicity is preserved.

        This is the sole delivery path for events written by this
        UnitOfWork — there is deliberately no separate always-on
        `OutboxRelay` racing it. Each row is marked PUBLISHED once every
        subscriber for its event type has run without raising (per
        `EventBus.publish`'s return value), or FAILED if any subscriber
        raised, so `outbox_messages` never accumulates rows that were
        already delivered. A row is only left PENDING if the process
        crashes between the DB commit above and the mark-published call
        below — a separate `OutboxRelay` may be run periodically purely as
        crash recovery for that narrow window, not as the primary path.
        """
        assert self.session is not None

        outbox_repo = SqlAlchemyOutboxRepository(self.session)
        pending: list[tuple[str, DomainEvent]] = []
        for aggregate in self._tracked_aggregates:
            for event in aggregate.collect_uncommitted_events():
                message = build_outbox_message(event)
                await outbox_repo.add(message)
                pending.append((message.outbox_id, event))

        await self.session.commit()
        self._committed = True

        logger.debug(f"SqlAlchemyUnitOfWork committed. Relaying {len(pending)} events to EventBus.")
        for outbox_id, event in pending:
            all_subscribers_succeeded = await self.event_bus.publish(event)
            if all_subscribers_succeeded:
                await outbox_repo.mark_published(outbox_id)
            else:
                await outbox_repo.mark_failed(
                    outbox_id, "One or more EventBus subscribers raised — see logs for detail."
                )

    async def rollback(self) -> None:
        assert self.session is not None
        logger.warning("SqlAlchemyUnitOfWork rolled back. No outbox rows or events were committed.")
        await self.session.rollback()
        self._tracked_aggregates.clear()
        self._committed = False
