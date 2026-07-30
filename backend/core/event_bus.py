"""
AlphaSync Event Bus — In-process async event dispatcher.

Provides a singleton EventBus that workers, engines, and the WebSocket layer
use to communicate without direct coupling. All handlers run in the same
asyncio event loop as FastAPI (Phase 1 architecture).

Usage:
    from core.event_bus import event_bus, Event, EventType

    # Subscribe
    event_bus.subscribe(EventType.ORDER_FILLED, my_handler)

    # Emit
    await event_bus.emit(Event(
        type=EventType.ORDER_FILLED,
        data={"order_id": "abc", "user_id": "123"},
        user_id="123",
    ))
"""

import asyncio
import uuid
import logging
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Any, Optional

logger = logging.getLogger(__name__)


class EventType(Enum):
    """All system-wide event types."""

    # Market data
    PRICE_UPDATED = "price_updated"
    MARKET_STATE_CHANGE = "market_state_change"
    FUTURES_QUOTE = "futures_quote"

    # Orders (stocks)
    ORDER_PLACED = "order_placed"
    ORDER_FILLED = "order_filled"
    ORDER_PARTIALLY_FILLED = "order_partially_filled"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_REJECTED = "order_rejected"
    ORDER_EXPIRED = "order_expired"

    # Orders (futures — simulated, local DB only)
    FUTURES_ORDER_PLACED = "futures_order_placed"
    FUTURES_ORDER_FILLED = "futures_order_filled"
    FUTURES_ORDER_CANCELLED = "futures_order_cancelled"
    FUTURES_ORDER_REJECTED = "futures_order_rejected"
    FUTURES_ORDER_EXPIRED = "futures_order_expired"

    # Portfolio
    PORTFOLIO_UPDATED = "portfolio_updated"

    # Algo trading
    ALGO_SIGNAL = "algo_signal"
    ALGO_TRADE = "algo_trade"
    ALGO_ERROR = "algo_error"
    ALGO_STATE_CHANGE = "algo_state_change"

    # Risk
    RISK_BREACH = "risk_breach"
    RISK_KILL_SWITCH = "risk_kill_switch"

    # Auth / user
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    USER_APPROVED = "user_approved"
    USER_DEACTIVATED = "user_deactivated"
    ACCESS_EXPIRING = "access_expiring"
    ACCESS_EXPIRED = "access_expired"
    ADMIN_ACTION = "admin_action"

    # System
    SYSTEM_STARTUP = "system_startup"
    SYSTEM_SHUTDOWN = "system_shutdown"


@dataclass
class Event:
    """Immutable event record flowing through the bus."""

    type: EventType
    data: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: Optional[str] = None
    source: Optional[str] = None  # e.g. "order_worker", "algo_worker"


# Type alias for event handler functions
EventHandler = Callable[[Event], Any]


class EventBus:
    """
    Singleton in-process async event bus.

    Design decisions:
    - Uses an asyncio.Queue for decoupling emitters from handlers.
    - Handlers are invoked sequentially per event to avoid race conditions
      on shared DB sessions. If parallelism is needed later, switch to
      asyncio.TaskGroup per event.
    - Dead letter logging for handler errors — events are never lost.
    """

    def __init__(self):
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._running = False
        self._stats: dict[str, int] = {"emitted": 0, "handled": 0, "errors": 0}

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Register a handler for an event type."""
        self._handlers.setdefault(event_type, []).append(handler)
        logger.debug(f"Subscribed {handler.__name__} to {event_type.value}")

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Remove a handler for an event type."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def emit(self, event: Event) -> None:
        """Enqueue an event for async dispatch."""
        qs = self._queue.qsize()
        try:
            from market.quote_metrics import quote_metrics

            quote_metrics.record_queue_depth(qs)
        except Exception:
            pass

        # Load protection — shed cold equity ticks under extreme burst (HOT path uses coordinator too)
        if (
            qs >= 300
            and event.type == EventType.PRICE_UPDATED
            and event.data.get("quote", {}).get("priority_tier") == "cold"
        ):
            try:
                from market.quote_metrics import quote_metrics

                quote_metrics.record_shed(
                    str(event.data.get("symbol") or "?"),
                    "cold",
                )
            except Exception:
                pass
            return

        await self._queue.put(event)
        self._stats["emitted"] += 1
        qs = self._queue.qsize()
        if qs > 200:
            logger.warning(
                f"Event queue growing large: size={qs} after emit {event.type.value} [{event.id[:8]}]"
            )
        else:
            logger.debug(f"Event emitted: {event.type.value} [{event.id[:8]}] queue={qs}")

    def emit_nowait(self, event: Event) -> None:
        """Non-async emit for use in synchronous contexts."""
        self._queue.put_nowait(event)
        self._stats["emitted"] += 1

    async def run(self) -> None:
        """
        Main dispatcher loop — runs as a background task alongside FastAPI.
        Started in main.py lifespan, cancelled on shutdown.
        """
        self._running = True
        logger.info("EventBus dispatcher started")

        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            handlers = self._handlers.get(event.type, [])
            if not handlers:
                logger.debug(f"No handlers for {event.type.value}")
                continue

            for handler in handlers:
                try:
                    result = handler(event)
                    if asyncio.iscoroutine(result):
                        await result
                    self._stats["handled"] += 1
                except Exception as e:
                    self._stats["errors"] += 1
                    logger.error(
                        f"Event handler error: {handler.__name__} "
                        f"for {event.type.value} [{event.id[:8]}]: {e}",
                        exc_info=True,
                    )

        logger.info("EventBus dispatcher stopped")

    async def stop(self) -> None:
        """Gracefully stop the dispatcher."""
        self._running = False

    def get_stats(self) -> dict:
        """Return dispatcher statistics for health checks."""
        return {
            **self._stats,
            "queue_size": self._queue.qsize(),
            "registered_handlers": {
                evt.value: len(handlers) for evt, handlers in self._handlers.items()
            },
        }


# ── Singleton instance ──────────────────────────────────────────────
event_bus = EventBus()
