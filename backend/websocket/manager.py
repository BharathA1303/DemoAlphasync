import asyncio
import json
import logging
from typing import Dict, Set, Optional
from fastapi import WebSocket
from services import market_data

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections, subscriptions, and event routing."""

    MAX_CONNECTIONS_PER_USER = 3

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}  # connection_id -> websocket
        self.subscriptions: Dict[str, Set[str]] = {}  # symbol -> set of connection_ids
        self.futures_subscriptions: Dict[str, Set[str]] = {}  # contract_symbol -> set of connection_ids
        self.user_connections: Dict[str, Set[str]] = (
            {}
        )  # user_id -> set of connection_ids
        self.connection_users: Dict[str, str] = {}  # connection_id -> user_id
        self.connection_opened_at: Dict[str, float] = (
            {}
        )  # connection_id -> loop timestamp

    async def connect(
        self, websocket: WebSocket, connection_id: str, user_id: Optional[str] = None
    ):
        await websocket.accept()

        # Server-side guardrail: cap simultaneous sockets per user to prevent
        # reconnect storms from spawning unbounded stale connections.
        if user_id:
            existing = list(self.user_connections.get(user_id, set()))
            if len(existing) >= self.MAX_CONNECTIONS_PER_USER:
                existing_sorted = sorted(
                    existing,
                    key=lambda cid: self.connection_opened_at.get(cid, 0.0),
                )
                to_drop = len(existing_sorted) - self.MAX_CONNECTIONS_PER_USER + 1
                for stale_conn_id in existing_sorted[:to_drop]:
                    stale_ws = self.active_connections.get(stale_conn_id)
                    if stale_ws:
                        try:
                            await stale_ws.close(code=1001)
                        except Exception:
                            pass
                    self.disconnect(stale_conn_id)

        self.active_connections[connection_id] = websocket
        try:
            self.connection_opened_at[connection_id] = asyncio.get_running_loop().time()
        except RuntimeError:
            self.connection_opened_at[connection_id] = 0.0

        if user_id:
            self.connection_users[connection_id] = user_id
            self.user_connections.setdefault(user_id, set()).add(connection_id)
        logger.info(
            f"WebSocket connected: {connection_id}"
            + (f" (user: {str(user_id)[:8]}...)" if user_id else "")
        )

    def disconnect(self, connection_id: str):
        self.active_connections.pop(connection_id, None)
        self.connection_opened_at.pop(connection_id, None)
        try:
            from workers.market_worker import market_data_worker
        except Exception:
            market_data_worker = None
        # Remove user mapping
        user_id = self.connection_users.pop(connection_id, None)
        if user_id and user_id in self.user_connections:
            self.user_connections[user_id].discard(connection_id)
            if not self.user_connections[user_id]:
                del self.user_connections[user_id]
        # Remove from all subscriptions
        for symbol in list(self.subscriptions.keys()):
            self.subscriptions[symbol].discard(connection_id)
            if not self.subscriptions[symbol]:
                del self.subscriptions[symbol]
                if market_data_worker is not None:
                    market_data_worker.remove_symbol(symbol)
        # Remove from all futures subscriptions
        for contract in list(self.futures_subscriptions.keys()):
            self.futures_subscriptions[contract].discard(connection_id)
            if not self.futures_subscriptions[contract]:
                del self.futures_subscriptions[contract]
        logger.info(f"WebSocket disconnected: {connection_id}")

    def subscribe(self, connection_id: str, symbols: list[str]):
        try:
            from workers.market_worker import market_data_worker
        except Exception:
            market_data_worker = None

        newly_subscribed: list[str] = []
        for symbol in symbols:
            formatted = market_data._format_symbol(symbol)
            is_new = formatted not in self.subscriptions
            if is_new:
                self.subscriptions[formatted] = set()
            self.subscriptions[formatted].add(connection_id)
            if market_data_worker is not None:
                market_data_worker.add_symbol(formatted)
            if is_new:
                newly_subscribed.append(formatted)

            # For renamed tickers (e.g. TATAMOTORS.NS ↔ TMPV.NS), register
            # the client under both canonical names so incoming ticks for the
            # live Zebu symbol also find subscribers on the legacy name.
            try:
                from providers.symbol_mapper import mirror_canonicals_for_quote
                for alias in mirror_canonicals_for_quote(formatted):
                    if alias != formatted:
                        if alias not in self.subscriptions:
                            self.subscriptions[alias] = set()
                            newly_subscribed.append(alias)
                        self.subscriptions[alias].add(connection_id)
                        if market_data_worker is not None:
                            market_data_worker.add_symbol(alias)
            except Exception:
                pass

        # Trigger Zebu WS subscription immediately for newly tracked symbols
        # so ticks start arriving without waiting for the worker sweep cycle.
        if newly_subscribed:
            try:
                from market.quote_coordinator import quote_coordinator
                from market.symbol_priority_engine import PriorityTier, symbol_priority_engine

                for sym in newly_subscribed:
                    if symbol_priority_engine.get_tier(sym) == PriorityTier.COLD:
                        symbol_priority_engine.register(sym, PriorityTier.WARM)
                    quote_coordinator.register_warm(sym)
            except Exception:
                pass
            asyncio.ensure_future(self._provider_subscribe(newly_subscribed))

    async def _provider_subscribe(self, symbols: list[str]) -> None:
        """Forward subscribe to Zebu provider for immediate WS tick delivery."""
        try:
            from services.broker_session import broker_session_manager
            from providers.symbol_mapper import is_commodity_symbol
            commodity_syms = [s for s in symbols if is_commodity_symbol(s)]
            if commodity_syms:
                logger.info(
                    f"[MCX MANAGER SUBSCRIBE] forwarding {len(commodity_syms)} "
                    f"commodity symbols to provider: {commodity_syms[:10]}"
                )
            provider = broker_session_manager.get_any_session()
            if provider is not None:
                await provider.subscribe(symbols)
                logger.info(f"Provider subscribe forwarded: {symbols[:8]}")
            else:
                logger.warning(
                    f"[MCX SUBSCRIBE BLOCKED] No provider session available. "
                    f"Symbols not subscribed: {commodity_syms[:5]}"
                )
        except Exception as e:
            logger.warning(f"Provider subscribe forward failed: {e}")

    def unsubscribe(self, connection_id: str, symbols: list[str]):
        try:
            from workers.market_worker import market_data_worker
        except Exception:
            market_data_worker = None

        for symbol in symbols:
            formatted = market_data._format_symbol(symbol)
            if formatted in self.subscriptions:
                self.subscriptions[formatted].discard(connection_id)
                if not self.subscriptions[formatted]:
                    del self.subscriptions[formatted]
                    if market_data_worker is not None:
                        market_data_worker.remove_symbol(formatted)

    async def subscribe_futures(self, connection_id: str, contract_symbol: str):
        """Subscribe to a futures contract and trigger Zebu WS subscription."""
        is_new = contract_symbol not in self.futures_subscriptions
        if is_new:
            self.futures_subscriptions[contract_symbol] = set()
        self.futures_subscriptions[contract_symbol].add(connection_id)

        if is_new:
            sym = str(contract_symbol or "").strip().upper()
            if sym:
                try:
                    from market.quote_coordinator import quote_coordinator
                    from market.symbol_priority_engine import PriorityTier, symbol_priority_engine

                    symbol_priority_engine.register(sym, PriorityTier.HOT)
                    quote_coordinator.register_hot(sym)
                except Exception:
                    pass
            asyncio.ensure_future(self._provider_subscribe_futures([contract_symbol]))

    async def _provider_subscribe_futures(self, contract_symbols: list[str]) -> None:
        """Forward futures contract subscribe to Zebu provider for live ticks."""
        try:
            from services.broker_session import broker_session_manager

            provider = broker_session_manager.get_any_session()
            if provider is None:
                try:
                    from services.master_session import master_session_service
                    if await master_session_service.initialize():
                        provider = broker_session_manager.get_any_session()
                except Exception:
                    pass
            if provider is not None:
                await provider.subscribe(contract_symbols)
                logger.info(
                    f"Futures provider subscribe forwarded: {contract_symbols[:8]}"
                )
            else:
                logger.warning(
                    f"No provider session for futures subscribe: {contract_symbols[:5]}"
                )
        except Exception as e:
            logger.warning(f"Futures provider subscribe failed: {e}")

    def unsubscribe_futures(self, connection_id: str, contract_symbol: str):
        """Unsubscribe from a futures contract."""
        if contract_symbol in self.futures_subscriptions:
            self.futures_subscriptions[contract_symbol].discard(connection_id)
            if not self.futures_subscriptions[contract_symbol]:
                del self.futures_subscriptions[contract_symbol]

    async def send_personal(self, connection_id: str, data: dict):
        ws = self.active_connections.get(connection_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(connection_id)

    async def send_to_user(self, user_id: str, data: dict):
        """Send a message to all WebSocket connections for a specific user."""
        conn_ids = list(self.user_connections.get(user_id, set()))
        dead = []
        for conn_id in conn_ids:
            ws = self.active_connections.get(conn_id)
            if ws:
                try:
                    await ws.send_json(data)
                except Exception:
                    dead.append(conn_id)
        for d in dead:
            self.disconnect(d)

    async def broadcast_price(self, symbol: str, price_data: dict):
        """Broadcast price update to all subscribers of a symbol."""
        subscribers = self.subscriptions.get(symbol, set())
        dead = []
        # Send as "quote" type with symbol at top level for frontend compat
        msg = {
            "type": "quote",
            "channel": "prices",
            "symbol": symbol,
            **price_data,
        }
        if not subscribers:
            logger.debug(f"Price update for {symbol} ignored — no subscribers")

        for conn_id in list(subscribers):
            ws = self.active_connections.get(conn_id)
            if ws:
                try:
                    await ws.send_json(msg)
                except Exception:
                    dead.append(conn_id)
        for d in dead:
            self.disconnect(d)
        logger.debug(
            f"Broadcasted price for {symbol} to {len(subscribers) - len(dead)} connections (dead={len(dead)})"
        )

    async def broadcast_futures_quote(self, contract_symbol: str, quote_data: dict):
        """Broadcast futures quote to all subscribers of a contract."""
        subscribers = self.futures_subscriptions.get(contract_symbol, set())
        dead = []
        msg = {
            "type": "futures_quote",
            "contract_symbol": contract_symbol,
            "data": quote_data,
        }
        for conn_id in subscribers:
            ws = self.active_connections.get(conn_id)
            if ws:
                try:
                    await ws.send_json(msg)
                except Exception:
                    dead.append(conn_id)
        for d in dead:
            self.disconnect(d)

    async def broadcast_all(self, data: dict):
        """Broadcast a message to ALL connected clients."""
        dead = []
        for conn_id, ws in list(self.active_connections.items()):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(conn_id)
        for d in dead:
            self.disconnect(d)

    # ── Event Bus Handlers ──────────────────────────────────────────
    # These methods are subscribed to EventBus events in main.py lifespan

    async def on_price_event(self, event):
        """Handle PRICE_UPDATED events — broadcast to subscribers of the symbol."""
        symbol = event.data.get("symbol")
        quote = event.data.get("quote")
        if symbol and quote:
            from providers.symbol_mapper import is_commodity_symbol, mirror_canonicals_for_quote
            subscribers = self.subscriptions.get(symbol, set())
            if is_commodity_symbol(symbol):
                logger.info(
                    f"[MCX WS BROADCAST] {symbol} "
                    f"ltp={quote.get('price')} source={event.source} "
                    f"subscribers={len(subscribers)} "
                    f"all_tracked={sorted(k for k in self.subscriptions if is_commodity_symbol(k))[:10]}"
                )
            await self.broadcast_price(symbol, quote)

            # Also broadcast under alias canonicals (e.g. TMPV.NS → TATAMOTORS.NS)
            # so clients subscribed to the legacy ticker receive live updates.
            for alias in mirror_canonicals_for_quote(symbol):
                if alias != symbol and alias in self.subscriptions:
                    alias_quote = {**quote, "symbol": alias}
                    await self.broadcast_price(alias, alias_quote)

    async def on_order_event(self, event):
        """Handle ORDER_* events — send to the specific user."""
        user_id = event.user_id
        if user_id:
            await self.send_to_user(
                user_id,
                {
                    "type": event.type.value,
                    "channel": "orders",
                    "data": event.data,
                },
            )

    async def on_portfolio_event(self, event):
        """Handle PORTFOLIO_UPDATED events — send to the specific user."""
        user_id = event.user_id
        if user_id:
            await self.send_to_user(
                user_id,
                {
                    "type": "portfolio_update",
                    "channel": "portfolio",
                    "data": event.data,
                },
            )

    async def on_algo_event(self, event):
        """Handle ALGO_TRADE / ALGO_SIGNAL events.
        ZeroLoss events are user-scoped; send only to the event user.
        Other algo events are also user-scoped.
        """
        user_id = event.user_id
        if user_id:
            channel = (event.data or {}).get("channel", "algo")
            payload_channel = "zeroloss" if channel == "zeroloss" else "algo"
            await self.send_to_user(
                user_id,
                {
                    "type": event.type.value,
                    "channel": payload_channel,
                    "data": event.data,
                },
            )

    async def on_futures_quote_event(self, event):
        """Handle FUTURES_QUOTE events from market data service.
        Broadcasts real-time quotes to all subscribers of the contract.
        Also feeds FuturesStreamManager for freshness tracking.
        """
        contract_symbol = event.data.get("contract_symbol")
        quote = event.data.get("quote")
        if contract_symbol and quote:
            try:
                from websocket.futures_stream import futures_stream_manager
                futures_stream_manager.on_tick(contract_symbol, quote)
            except Exception:
                pass
            try:
                from services import futures_service

                asyncio.ensure_future(
                    futures_service.set_cache_quote(contract_symbol, quote)
                )
            except Exception:
                pass
            await self.broadcast_futures_quote(contract_symbol, quote)

    async def on_futures_order_event(self, event):
        """Handle FUTURES_ORDER_* events — send to the specific user."""
        user_id = event.user_id
        if user_id:
            await self.send_to_user(
                user_id,
                {
                    "type": event.type.value,
                    "channel": "futures_orders",
                    "data": event.data,
                },
            )

    # ── Message Handling ───────────────────────────────────────────

    async def handle_message(self, connection_id: str, message: str):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(message)
            # Support both 'action' and 'type' fields for backward compat
            action = data.get("action") or data.get("type")

            if action == "subscribe":
                symbols = data.get("symbols", [])
                self.subscribe(connection_id, symbols)
                await self.send_personal(
                    connection_id,
                    {
                        "type": "subscribed",
                        "symbols": symbols,
                    },
                )
            elif action == "unsubscribe":
                symbols = data.get("symbols", [])
                self.unsubscribe(connection_id, symbols)
                await self.send_personal(
                    connection_id,
                    {
                        "type": "unsubscribed",
                        "symbols": symbols,
                    },
                )
            elif action == "subscribe_futures":
                contract = data.get("contract")
                if contract:
                    await self.subscribe_futures(connection_id, contract)
                    await self.send_personal(
                        connection_id,
                        {
                            "type": "subscribed_futures",
                            "contract": contract,
                        },
                    )
            elif action == "unsubscribe_futures":
                contract = data.get("contract")
                if contract:
                    self.unsubscribe_futures(connection_id, contract)
                    await self.send_personal(
                        connection_id,
                        {
                            "type": "unsubscribed_futures",
                            "contract": contract,
                        },
                    )
            elif action == "ping":
                await self.send_personal(
                    connection_id,
                    {
                        "type": "pong",
                    },
                )
        except json.JSONDecodeError:
            pass


manager = ConnectionManager()
