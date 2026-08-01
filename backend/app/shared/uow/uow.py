import logging
from typing import List, Protocol
from app.kernel.primitives.aggregate import BaseAggregateRoot
from app.shared.event_bus.event_bus import EventBus

logger = logging.getLogger(__name__)


class IUnitOfWork(Protocol):
    async def __aenter__(self) -> "IUnitOfWork":
        ...

    async def __aexit__(self, exc_type: type, exc_val: Exception, traceback: object) -> None:
        ...

    def register_aggregate(self, aggregate: BaseAggregateRoot) -> None:
        ...

    async def commit(self) -> None:
        ...

    async def rollback(self) -> None:
        ...


class InMemoryUnitOfWork:
    """In-Memory Unit of Work coordinating Aggregate state commit and EventBus outbox dispatching."""

    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self._tracked_aggregates: List[BaseAggregateRoot] = []
        self._committed = False

    async def __aenter__(self) -> "InMemoryUnitOfWork":
        self._tracked_aggregates.clear()
        self._committed = False
        return self

    async def __aexit__(self, exc_type: type, exc_val: Exception, traceback: object) -> None:
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
        logger.debug(f"UnitOfWork committed. Publishing {len(events_to_publish)} outbox events...")

        for event in events_to_publish:
            await self.event_bus.publish(event)

    async def rollback(self) -> None:
        logger.warning("UnitOfWork transaction rolled back. Clearing tracked aggregates.")
        self._tracked_aggregates.clear()
        self._committed = False
