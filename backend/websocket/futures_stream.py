"""
FuturesStreamManager — Manages futures-specific WebSocket streaming state.

Tracks active contracts, tokens, clients, and handles dynamic subscriptions,
auto-unsubscribe, reconnect handling, heartbeat monitoring, stream freshness,
and contract lifecycle.

Completely separate from equity stream registry.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Stale threshold: if no tick received for a contract in this many seconds,
# consider the stream stale (may be illiquid — that's OK, just track it).
_STALE_STREAM_SECONDS = 120
_HEARTBEAT_INTERVAL = 30
_CLEANUP_INTERVAL = 60


class FuturesStreamManager:
    """Dedicated manager for futures contract streaming lifecycle."""

    def __init__(self):
        # contract_symbol -> set of connection_ids
        self._subscribers: dict[str, set[str]] = {}
        # contract_symbol -> token (for Zebu subscription)
        self._contract_tokens: dict[str, str] = {}
        # contract_symbol -> exchange
        self._contract_exchanges: dict[str, str] = {}
        # contract_symbol -> last tick timestamp (monotonic)
        self._last_tick_at: dict[str, float] = {}
        # contract_symbol -> last quote data
        self._last_quotes: dict[str, dict] = {}
        # contract_symbol -> expiry_date str (YYYY-MM-DD)
        self._contract_expiry: dict[str, str] = {}
        # Tracks provider-subscribed contracts to avoid duplicate subscribes
        self._provider_subscribed: set[str] = set()
        self._running = False
        self._cleanup_task: Optional[asyncio.Task] = None

    def start(self):
        """Start background cleanup loop."""
        if not self._running:
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("FuturesStreamManager started")

    def stop(self):
        """Stop background tasks."""
        self._running = False
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
        logger.info("FuturesStreamManager stopped")

    def register_contract(
        self,
        contract_symbol: str,
        token: str,
        exchange: str = "NFO",
        expiry_date: Optional[str] = None,
    ):
        """Register a contract for streaming readiness."""
        self._contract_tokens[contract_symbol] = token
        self._contract_exchanges[contract_symbol] = exchange
        if expiry_date:
            self._contract_expiry[contract_symbol] = expiry_date

    def subscribe(self, connection_id: str, contract_symbol: str) -> bool:
        """Subscribe a client to a futures contract. Returns True if new subscription."""
        is_new_contract = contract_symbol not in self._subscribers
        if is_new_contract:
            self._subscribers[contract_symbol] = set()
        self._subscribers[contract_symbol].add(connection_id)
        return is_new_contract

    def unsubscribe(self, connection_id: str, contract_symbol: str):
        """Unsubscribe a client from a futures contract."""
        if contract_symbol in self._subscribers:
            self._subscribers[contract_symbol].discard(connection_id)

    def disconnect_client(self, connection_id: str):
        """Remove a client from all futures subscriptions."""
        for contract in list(self._subscribers.keys()):
            self._subscribers[contract].discard(connection_id)
            if not self._subscribers[contract]:
                del self._subscribers[contract]

    def get_subscribers(self, contract_symbol: str) -> set[str]:
        """Get all connection IDs subscribed to a contract."""
        return self._subscribers.get(contract_symbol, set())

    def get_active_contracts(self) -> list[str]:
        """Get all contracts with at least one subscriber."""
        return [c for c, subs in self._subscribers.items() if subs]

    def get_unsubscribed_contracts(self) -> list[str]:
        """Get contracts with no subscribers (candidates for provider unsubscribe)."""
        return [c for c, subs in self._subscribers.items() if not subs]

    def on_tick(self, contract_symbol: str, quote: dict):
        """Record a tick arrival for freshness tracking."""
        self._last_tick_at[contract_symbol] = time.monotonic()
        self._last_quotes[contract_symbol] = quote

    def get_last_quote(self, contract_symbol: str) -> Optional[dict]:
        """Get the most recent quote for a contract."""
        return self._last_quotes.get(contract_symbol)

    def get_token(self, contract_symbol: str) -> Optional[str]:
        """Get the Zebu token for a contract."""
        return self._contract_tokens.get(contract_symbol)

    def get_exchange(self, contract_symbol: str) -> str:
        """Get the exchange for a contract."""
        return self._contract_exchanges.get(contract_symbol, "NFO")

    def is_stale(self, contract_symbol: str) -> bool:
        """Check if a contract's stream is stale (no ticks for a while)."""
        last = self._last_tick_at.get(contract_symbol)
        if last is None:
            return True
        return (time.monotonic() - last) > _STALE_STREAM_SECONDS

    def is_expired(self, contract_symbol: str) -> bool:
        """Check if a contract has expired based on its expiry date."""
        expiry = self._contract_expiry.get(contract_symbol)
        if not expiry:
            return False
        try:
            expiry_dt = datetime.strptime(expiry, "%Y-%m-%d").date()
            return datetime.now().date() > expiry_dt
        except (ValueError, TypeError):
            return False

    def mark_provider_subscribed(self, contract_symbol: str):
        """Mark a contract as subscribed at the provider level."""
        self._provider_subscribed.add(contract_symbol)

    def is_provider_subscribed(self, contract_symbol: str) -> bool:
        """Check if a contract is already subscribed at the provider level."""
        return contract_symbol in self._provider_subscribed

    def get_stream_status(self) -> dict:
        """Get a snapshot of stream health for diagnostics."""
        now = time.monotonic()
        active = self.get_active_contracts()
        return {
            "active_contracts": len(active),
            "total_registered": len(self._contract_tokens),
            "provider_subscribed": len(self._provider_subscribed),
            "stale_streams": sum(1 for c in active if self.is_stale(c)),
            "expired_contracts": sum(
                1 for c in self._contract_expiry if self.is_expired(c)
            ),
        }

    async def _cleanup_loop(self):
        """Periodic cleanup of expired contracts and empty subscriptions."""
        while self._running:
            try:
                await asyncio.sleep(_CLEANUP_INTERVAL)

                # Clean up expired contracts
                expired = [c for c in list(self._contract_expiry) if self.is_expired(c)]
                for contract in expired:
                    self._subscribers.pop(contract, None)
                    self._contract_tokens.pop(contract, None)
                    self._contract_exchanges.pop(contract, None)
                    self._contract_expiry.pop(contract, None)
                    self._last_tick_at.pop(contract, None)
                    self._last_quotes.pop(contract, None)
                    self._provider_subscribed.discard(contract)
                    logger.info(f"Expired futures contract cleaned up: {contract}")

                # Clean up empty subscription sets
                empty = [c for c, s in self._subscribers.items() if not s]
                for contract in empty:
                    del self._subscribers[contract]

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"FuturesStreamManager cleanup error: {e}")


# Singleton instance
futures_stream_manager = FuturesStreamManager()
