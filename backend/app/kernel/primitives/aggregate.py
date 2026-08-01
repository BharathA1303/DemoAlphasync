
from app.kernel.primitives.event import DomainEvent


class BaseAggregateRoot:
    """Base Aggregate Root enforcing invariant collection and transactional outbox event accumulation."""

    def __init__(self) -> None:
        self._uncommitted_events: list[DomainEvent] = []

    def _record_event(self, event: DomainEvent) -> None:
        """Record an immutable DomainEvent object."""
        self._uncommitted_events.append(event)

    def collect_uncommitted_events(self) -> list[DomainEvent]:
        """Extract and clear accumulated domain events for UnitOfWork publication."""
        events = list(self._uncommitted_events)
        self._uncommitted_events.clear()
        return events
