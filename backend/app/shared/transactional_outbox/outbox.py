"""Outbox repository protocol and relay.

`IOutboxRepository` is implemented once per persistence technology (see
`sqlalchemy_outbox.py` for the SQLAlchemy-backed implementation used in
production). `OutboxRelay` is persistence-agnostic: it only needs a
repository and an EventBus to drain pending messages after a UnitOfWork
commit is durable.
"""
import dataclasses
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from app.kernel.ids.generator import default_id_generator
from app.kernel.primitives.event import DomainEvent
from app.shared.event_bus.event_bus import EventBus
from app.shared.transactional_outbox.models import OutboxMessage

logger = logging.getLogger(__name__)


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def serialize_event(event: DomainEvent) -> str:
    """Serialize a DomainEvent to a JSON string for outbox storage."""
    return json.dumps(dataclasses.asdict(event), default=_json_default)


class IOutboxRepository(Protocol):
    """Persistence boundary for outbox messages.

    Implementations MUST participate in the same database transaction as
    the UnitOfWork that calls `add` — that is the entire point of the
    pattern. `fetch_pending` / `mark_published` / `mark_failed` are used by
    the relay and may run in their own transaction.
    """

    async def add(self, message: OutboxMessage) -> None: ...

    async def fetch_pending(self, limit: int = 100) -> list[OutboxMessage]: ...

    async def mark_published(self, outbox_id: str) -> None: ...

    async def mark_failed(self, outbox_id: str, error: str) -> None: ...


def build_outbox_message(event: DomainEvent) -> OutboxMessage:
    """Construct the durable OutboxMessage for a DomainEvent, ready to add
    to an IOutboxRepository inside the same transaction as the aggregate
    state change that raised it."""
    event_type = type(event)
    return OutboxMessage.pending(
        outbox_id=default_id_generator.generate("obx"),
        event_type=event_type.__name__,
        event_id=event.event_id,
        correlation_id=event.correlation_id,
        payload=serialize_event(event),
    )


class OutboxRelay:
    """Drains PENDING outbox messages and publishes them on the EventBus.

    Deserialization of the JSON payload back into a concrete DomainEvent
    subclass requires a type registry (event_type name -> dataclass), since
    the outbox itself stores only the class name and JSON body.
    """

    def __init__(self, repository: IOutboxRepository, event_bus: EventBus) -> None:
        self._repository = repository
        self._event_bus = event_bus
        self._event_type_registry: dict[str, type[DomainEvent]] = {}

    def register_event_type(self, event_type: type[DomainEvent]) -> None:
        self._event_type_registry[event_type.__name__] = event_type

    async def relay_once(self, limit: int = 100) -> int:
        """Publish up to `limit` pending messages. Returns the count relayed."""
        pending = await self._repository.fetch_pending(limit=limit)
        relayed = 0
        for message in pending:
            event_type = self._event_type_registry.get(message.event_type)
            if event_type is None:
                error = f"No event type registered for outbox message type '{message.event_type}'"
                logger.error(error)
                await self._repository.mark_failed(message.outbox_id, error)
                continue

            try:
                payload = json.loads(message.payload)
                event = event_type(**payload)
                await self._event_bus.publish(event)
                await self._repository.mark_published(message.outbox_id)
                relayed += 1
            except Exception as exc:
                logger.error(f"Outbox relay failed for message {message.outbox_id}: {exc}", exc_info=True)
                await self._repository.mark_failed(message.outbox_id, str(exc))

        return relayed
