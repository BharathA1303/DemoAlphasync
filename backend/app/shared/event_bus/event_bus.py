import asyncio
import logging
from collections.abc import Callable
from typing import Any

from app.kernel.primitives.event import DomainEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[Any], Any]


class EventBus:
    """In-Process Pub/Sub Event Bus Router supporting multiple subscribers per event type."""

    def __init__(self) -> None:
        self._subscribers: dict[type[DomainEvent], list[EventHandler]] = {}

    def subscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)
        logger.info(f"Subscribed handler '{handler.__name__}' to Event: {event_type.__name__}")

    async def publish(self, event: DomainEvent) -> bool:
        """Publish `event` to every subscriber of its type.

        Every subscriber always runs regardless of whether an earlier one
        raised (via `asyncio.gather(..., return_exceptions=True)`) — one
        broken consumer must never block delivery to healthy ones. Returns
        `True` only if every subscriber completed without raising, so a
        caller with its own delivery-tracking concern (e.g.
        `SqlAlchemyUnitOfWork.commit()` marking an outbox row
        PUBLISHED/FAILED) can tell success from partial failure without
        this method itself raising.
        """
        event_type = type(event)
        handlers = self._subscribers.get(event_type, [])
        if not handlers:
            logger.debug(f"Event {event_type.__name__} published with no active subscribers")
            return True

        logger.debug(
            f"Publishing Event {event_type.__name__} to {len(handlers)} subscribers "
            f"[evt_id={event.event_id}, corr_id={event.correlation_id}]"
        )
        tasks = [asyncio.create_task(handler(event)) for handler in handlers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_succeeded = True
        for handler, result in zip(handlers, results, strict=True):
            if isinstance(result, BaseException):
                all_succeeded = False
                logger.error(
                    f"Subscriber '{handler.__name__}' failed handling {event_type.__name__} "
                    f"[evt_id={event.event_id}]: {result}",
                    exc_info=result,
                )
        return all_succeeded
