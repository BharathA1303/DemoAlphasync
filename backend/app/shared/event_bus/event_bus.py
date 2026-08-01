import asyncio
import logging
from typing import Any, Callable, Dict, List, Type
from app.kernel.primitives.event import DomainEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[Any], Any]


class EventBus:
    """In-Process Pub/Sub Event Bus Router supporting multiple subscribers per event type."""

    def __init__(self) -> None:
        self._subscribers: Dict[Type[DomainEvent], List[EventHandler]] = {}

    def subscribe(self, event_type: Type[DomainEvent], handler: EventHandler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)
        logger.info(f"Subscribed handler '{handler.__name__}' to Event: {event_type.__name__}")

    async def publish(self, event: DomainEvent) -> None:
        event_type = type(event)
        handlers = self._subscribers.get(event_type, [])
        if not handlers:
            logger.debug(f"Event {event_type.__name__} published with no active subscribers")
            return

        logger.debug(
            f"Publishing Event {event_type.__name__} to {len(handlers)} subscribers "
            f"[evt_id={event.event_id}, corr_id={event.correlation_id}]"
        )
        tasks = [asyncio.create_task(handler(event)) for handler in handlers]
        await asyncio.gather(*tasks, return_exceptions=True)
