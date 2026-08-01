"""Transactional Outbox domain model.

The transactional outbox pattern guarantees that a DomainEvent is never lost
between "the aggregate's state change committed" and "the EventBus published
it" — the two must be atomic. This is achieved by writing outbox rows in the
SAME database transaction as the aggregate's own state change (both commit
or both roll back together), then relaying rows to the EventBus in a
separate step after the transaction is durable.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class OutboxMessage:
    """A single durable record of a DomainEvent awaiting relay to the EventBus.

    `payload` is the event's serialized (JSON string) form — the outbox
    only needs to transport bytes; it does not need to understand the
    concrete DomainEvent subclass to persist or relay it.
    """

    outbox_id: str
    event_type: str
    event_id: str
    correlation_id: str
    payload: str
    status: OutboxStatus
    created_at_utc: datetime
    published_at_utc: datetime | None = None
    attempts: int = 0
    last_error: str | None = None

    @classmethod
    def pending(
        cls,
        *,
        outbox_id: str,
        event_type: str,
        event_id: str,
        correlation_id: str,
        payload: str,
    ) -> "OutboxMessage":
        return cls(
            outbox_id=outbox_id,
            event_type=event_type,
            event_id=event_id,
            correlation_id=correlation_id,
            payload=payload,
            status=OutboxStatus.PENDING,
            created_at_utc=datetime.now(timezone.utc),
        )

    def mark_published(self) -> "OutboxMessage":
        return OutboxMessage(
            outbox_id=self.outbox_id,
            event_type=self.event_type,
            event_id=self.event_id,
            correlation_id=self.correlation_id,
            payload=self.payload,
            status=OutboxStatus.PUBLISHED,
            created_at_utc=self.created_at_utc,
            published_at_utc=datetime.now(timezone.utc),
            attempts=self.attempts + 1,
            last_error=None,
        )

    def mark_failed(self, error: str) -> "OutboxMessage":
        return OutboxMessage(
            outbox_id=self.outbox_id,
            event_type=self.event_type,
            event_id=self.event_id,
            correlation_id=self.correlation_id,
            payload=self.payload,
            status=OutboxStatus.FAILED,
            created_at_utc=self.created_at_utc,
            published_at_utc=self.published_at_utc,
            attempts=self.attempts + 1,
            last_error=error[:2000],
        )
