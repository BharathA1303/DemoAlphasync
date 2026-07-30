"""
AlphaSync ZeroLoss — Smart Controller v2 (Orchestrator).

Key improvements over v1:
    1. Market regime filter — EMA + ADX for stronger trend confirmation
    2. Time filter — skip opening 15min and late-day entries after 2:45 PM
    3. Trailing stop v2 — wider SL (2%), lower target (2.5%), smarter phases
    4. Momentum reversal exit — exit early if MACD flips against position
    5. Fewer positions (5 max) — concentrate capital on best setups
    6. Higher threshold (60%) — only take high-conviction trades
    7. VWAP alignment — must align with institutional flow
    8. Cooldown per symbol — no re-entry for 10 min after exit

Usage:
    from strategies.zeroloss.controller import zeroloss_controller
    asyncio.create_task(zeroloss_controller.run())
"""

import asyncio
import logging
from datetime import datetime, time, date, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text

from core.event_bus import event_bus, Event, EventType
from database.connection import async_session_factory
from engines.market_session import market_session, MarketState
from services import market_data
from services.trading_engine import place_order

from strategies.zeroloss.confidence_engine import ConfidenceEngine
from strategies.zeroloss.signal_generator import ZeroLossSignalGenerator, ZeroLossSignal
from strategies.zeroloss.breakeven_manager import BreakevenManager
from strategies.zeroloss.intelligence.market_regime_engine import (
    MarketRegimeEngine,
    MarketRegimeSnapshot,
)
from strategies.zeroloss.intelligence.session_filters import SessionTradeFilter

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# Force-close time: 3:20 PM IST (10 min before market close)
FORCE_CLOSE_TIME = time(15, 20)

# No new entries after 3:00 PM — gives more trading window vs previous 2:45 PM
NO_NEW_ENTRY_TIME = time(15, 0)

# Skip opening 5 min only — catch early momentum from 9:20 AM
MARKET_SETTLE_TIME = time(9, 20)

# Nifty 50 symbol for market regime detection
NIFTY_SYMBOL = "^NSEI"

# Symbol pool — expanded to top 22 Nifty liquid stocks
DEFAULT_SYMBOLS = [
    "RELIANCE.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "INFY.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "BHARTIARTL.NS",
    "LT.NS",
    "KOTAKBANK.NS",
    "ITC.NS",
    "TATAMOTORS.NS",
    "BAJFINANCE.NS",
    "AXISBANK.NS",
    "SUNPHARMA.NS",
    "HCLTECH.NS",
    "WIPRO.NS",
    "MARUTI.NS",
    "TITAN.NS",
    "ULTRACEMCO.NS",
    "ADANIENT.NS",
    "HINDUNILVR.NS",
    "NTPC.NS",
]

# Cooldown: don't re-enter a symbol for this many seconds after exit
SYMBOL_COOLDOWN_SECONDS = 300  # 5 minutes (was 10)


class ZeroLossController:
    """
    Smart background worker that runs the ZeroLoss strategy pipeline v2.

    Key principles:
        - Trade WITH the market, not against it (regime filter + VWAP)
        - Only take high-conviction setups (55% threshold + quality gates)
        - Let winners run (trailing stop with wider phases)
        - Cut losers early but not too early (2% SL)
        - Exit on momentum reversal (don't wait for SL if MACD flips)
        - Avoid dead zones (opening volatility, late afternoon)
        - Cooldown per symbol (no revenge trading)
    """

    SCAN_INTERVAL = 6  # faster entry discovery under live conditions
    MONITOR_INTERVAL = 2  # was 3 — tighter monitoring loop
    CANDLE_PERIOD = "5d"  # was "1mo" — 7x less data, much faster fetch
    CANDLE_INTERVAL = "5m"
    MAX_CONCURRENT_POSITIONS = 5
    MAX_NEW_ENTRIES_PER_SCAN = 3
    NEUTRAL_REGIME_THRESHOLD = 58.0  # neutral market no longer over-blocks valid setups
    SIMULATION_NEUTRAL_BUFFER = 0.0
    SIMULATION_FALLBACK_BUFFER = -12.0  # Fallback in sim uses threshold-12 (~42%)
    SIMULATION_MIN_VOLUME_RATIO = 0.45

    def __init__(
        self,
        symbols: Optional[list[str]] = None,
        confidence_threshold: float = 54.0,
        risk_reward_ratio: float = 1.6,  # Optimized for 2% SL / 3.2% target
        quantity: int = 1,
    ):
        self._running = False
        self._enabled = False
        self._symbols = symbols or DEFAULT_SYMBOLS.copy()
        self._threshold = confidence_threshold
        self._rr_ratio = risk_reward_ratio
        self._quantity = quantity

        self._confidence = ConfidenceEngine()
        self._signal_gen = ZeroLossSignalGenerator(
            confidence_threshold=confidence_threshold,
            risk_reward_ratio=risk_reward_ratio,
        )
        self._breakeven = BreakevenManager()

        # In-memory active positions: symbol → ZeroLossSignal
        self._active_positions: dict[str, ZeroLossSignal] = {}

        # Latest confidence snapshot per symbol (for API)
        self._latest_confidence: dict[str, dict] = {}

        # Market regime: "BULLISH", "BEARISH", or "NEUTRAL"
        self._market_regime: str = "NEUTRAL"
        self._regime_last_checked: Optional[datetime] = None
        self._regime_strength: float = 0.0  # 0-100 regime strength

        # Phase A — institutional regime layer (additive; legacy regime unchanged)
        self._regime_engine = MarketRegimeEngine()
        self._regime_snapshot: Optional[MarketRegimeSnapshot] = None
        self._use_regime_intelligence = True

        # User who enabled the strategy
        self._user_id: Optional[str] = None

        # Symbol cooldown: symbol → datetime when cooldown expires
        self._symbol_cooldowns: dict[str, datetime] = {}

        # Performance counters (reset daily)
        self._today: Optional[date] = None
        self._total_trades = 0
        self._profit_trades = 0
        self._breakeven_trades = 0
        self._loss_trades = 0
        self._net_pnl = 0.0

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_user(self, user_id: Optional[str]) -> None:
        self._user_id = user_id

    def _user_id_text(self) -> Optional[str]:
        return str(self._user_id) if self._user_id else None

    def enable(self, user_id: Optional[str] = None) -> None:
        self._enabled = True
        if user_id:
            self.set_user(user_id)
        logger.info(
            f"ZeroLoss strategy ENABLED for user {str(self._user_id)[:8] if self._user_id else 'system'}..."
        )

    def disable(self) -> None:
        self._enabled = False
        logger.info("ZeroLoss strategy DISABLED")

    async def close_all_positions(self) -> list[dict]:
        """Close ALL active positions immediately (used when stopping strategy)."""
        if not self._active_positions:
            return []

        results = []
        closed_symbols = []

        for symbol, signal in list(self._active_positions.items()):
            try:
                qty = signal.trade_qty or self._quantity
                quote = await market_data.get_system_quote_safe(symbol)
                current_price = (
                    quote["price"]
                    if quote and quote.get("price")
                    else signal.entry_price
                )

                close_side = "SELL" if signal.direction == "LONG" else "BUY"
                close_result = await self._place_trade(
                    symbol=symbol,
                    side=close_side,
                    quantity=qty,
                    price=current_price,
                )

                if not close_result or not close_result.get("success"):
                    err = (
                        close_result.get("error", "order rejected")
                        if close_result
                        else "order failed"
                    )
                    logger.warning(
                        f"[{symbol}] Strategy-stop close failed: {err}"
                    )
                    results.append({"symbol": symbol, "error": err})
                    continue

                if signal.direction == "LONG":
                    pnl = (current_price - signal.entry_price) * qty
                else:
                    pnl = (signal.entry_price - current_price) * qty
                net_pnl = round(pnl, 2)

                if net_pnl > 0:
                    signal.status = "PROFIT"
                    self._profit_trades += 1
                else:
                    signal.status = "STOPLOSS"
                    self._loss_trades += 1
                self._net_pnl += net_pnl

                await self._persist_signal_update(signal, net_pnl)

                await event_bus.emit(
                    Event(
                        type=EventType.ALGO_TRADE,
                        data={
                            "channel": "zeroloss",
                            "action": "FORCE_CLOSE",
                            "reason": "Strategy stopped by user",
                            "signal": signal.to_dict(),
                            "pnl": net_pnl,
                            "order": close_result.get("order"),
                            "stats": self.get_stats(),
                        },
                        user_id=self._user_id_text(),
                        source="zeroloss_controller",
                    )
                )

                closed_symbols.append(symbol)
                results.append(
                    {"symbol": symbol, "pnl": net_pnl, "status": signal.status}
                )
                logger.info(f"[{symbol}] Strategy-stop close | PnL: ₹{net_pnl:.2f}")

            except Exception as e:
                logger.error(f"[{symbol}] Error closing on stop: {e}", exc_info=True)
                results.append({"symbol": symbol, "error": str(e)})

        for sym in closed_symbols:
            self._active_positions.pop(sym, None)

        logger.info(
            f"ZeroLoss: closed {len(closed_symbols)} positions on strategy stop"
        )
        return results

    def is_enabled(self) -> bool:
        return self._enabled

    def clear_active_positions(self) -> None:
        """Drop in-memory Alpha Auto positions (e.g. after kill switch)."""
        self._active_positions.clear()

    def get_symbols(self) -> list[str]:
        return list(self._symbols)

    def set_symbols(self, symbols: list[str]) -> None:
        self._symbols = [market_data._format_symbol(s) for s in symbols]

    def set_confidence_threshold(self, threshold: float) -> None:
        self._threshold = threshold
        self._signal_gen.threshold = threshold

    def set_risk_reward_ratio(self, ratio: float) -> None:
        self._rr_ratio = ratio
        self._signal_gen.rr_ratio = ratio

    def set_quantity(self, quantity: int) -> None:
        self._quantity = quantity

    def get_latest_confidence(self) -> dict:
        return dict(self._latest_confidence)

    def get_active_positions(self) -> dict[str, dict]:
        return {sym: sig.to_dict() for sym, sig in self._active_positions.items()}

    def get_stats(self) -> dict:
        return {
            "enabled": self._enabled,
            "symbols": self._symbols,
            "confidence_threshold": self._threshold,
            "risk_reward_ratio": self._rr_ratio,
            "quantity": self._quantity,
            "simulation_mode": market_session.simulation_mode,
            "active_positions": len(self._active_positions),
            "today_trades": self._total_trades,
            "today_profit": self._profit_trades,
            "today_breakeven": self._breakeven_trades,
            "today_losses": self._loss_trades,
            "today_pnl": round(self._net_pnl, 2),
            "market_regime": self._market_regime,
            "regime_strength": round(self._regime_strength, 1),
            "regime_intelligence": (
                self._regime_snapshot.to_dict()
                if self._regime_snapshot
                else None
            ),
        }

    async def get_signal_history(
        self, limit: int = 50, symbol: Optional[str] = None
    ) -> list[dict]:
        user_id_text = self._user_id_text()
        if not user_id_text:
            return []

        query = """
            SELECT
                id,
                user_id,
                symbol,
                timestamp,
                confidence_score,
                direction,
                entry_price,
                stop_loss,
                target,
                status,
                COALESCE(pnl, 0) AS pnl,
                created_at
            FROM zeroloss_signals
            WHERE user_id = :user_id
        """
        params = {"user_id": user_id_text, "limit": int(limit)}
        if symbol:
            query += " AND symbol = :symbol"
            params["symbol"] = symbol

        query += " ORDER BY timestamp DESC LIMIT :limit"

        try:
            async with async_session_factory() as session:
                rows = await session.execute(text(query), params)
                return [dict(r) for r in rows.mappings().all()]
        except Exception as e:
            logger.error(f"Failed to read ZeroLoss signal history: {e}")
            return []

    async def get_performance_summary(self, days: int = 30) -> list[dict]:
        user_id_text = self._user_id_text()
        if not user_id_text:
            return []

        start_date = datetime.now(IST).date() - timedelta(days=max(days - 1, 0))
        try:
            async with async_session_factory() as session:
                rows = await session.execute(
                    text(
                        """
                        SELECT
                            DATE(timestamp) AS date,
                            COUNT(*) AS total_trades,
                            SUM(CASE WHEN status = 'PROFIT' THEN 1 ELSE 0 END) AS profit_trades,
                            SUM(CASE WHEN status = 'BREAKEVEN' THEN 1 ELSE 0 END) AS breakeven_trades,
                            SUM(CASE WHEN status = 'STOPLOSS' THEN 1 ELSE 0 END) AS loss_trades,
                            COALESCE(SUM(COALESCE(pnl, 0)), 0) AS net_pnl,
                            MIN(created_at) AS created_at
                        FROM zeroloss_signals
                        WHERE user_id = :user_id
                          AND DATE(timestamp) >= DATE(:start_date)
                        GROUP BY DATE(timestamp)
                        ORDER BY DATE(timestamp) DESC
                        LIMIT :days
                        """
                    ),
                    {
                        "user_id": user_id_text,
                        "start_date": start_date,
                        "days": int(days),
                    },
                )
                return [dict(r) for r in rows.mappings().all()]
        except Exception as e:
            logger.error(f"Failed to read ZeroLoss performance summary: {e}")
            return []

    def _build_simulation_fallback_signal(
        self,
        symbol: str,
        confidence,
        current_price: float,
        quantity: int,
        closes: Optional[list[float]] = None,
    ) -> Optional[ZeroLossSignal]:
        """Create a relaxed demo-only signal when strict gates block all entries."""
        if not market_session.is_live_trading_session():
            return None

        # Derive direction if NEUTRAL using recent price slope
        if confidence.direction == "BULLISH":
            direction = "LONG"
        elif confidence.direction == "BEARISH":
            direction = "SHORT"
        else:
            if closes and len(closes) >= 10:
                slope = closes[-1] - closes[-10]
                direction = "LONG" if slope >= 0 else "SHORT"
            else:
                direction = "LONG"

        # Permissive score floor for sim fallback
        min_score = max(self._threshold + self.SIMULATION_FALLBACK_BUFFER, 30.0)
        if confidence.total < min_score:
            return None

        logger.info(
            f"[{symbol}] SIM_FALLBACK {direction} | score={confidence.total:.1f} "
            f"regime={self._market_regime}"
        )

        levels = self._breakeven.compute_levels(
            entry_price=current_price,
            direction=direction,
            quantity=quantity,
            risk_reward_ratio=self._rr_ratio,
        )

        return ZeroLossSignal(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            direction=direction,
            confidence_score=confidence.total,
            entry_price=levels.entry,
            stop_loss=levels.stop_loss,
            target=levels.target,
            risk_reward_ratio=levels.risk_reward_ratio,
            status="WAITING",
            reasons=["SIMULATION_FALLBACK", *confidence.reasons],
            indicator_snapshot={
                "ema_20": confidence.ema_20,
                "ema_50": confidence.ema_50,
                "ema_200": confidence.ema_200,
                "rsi": confidence.rsi,
                "macd_hist": confidence.macd_hist,
                "volume_ratio": confidence.volume_ratio,
                "vix": confidence.vix,
                "vwap": confidence.vwap,
                "adx": confidence.adx,
            },
            peak_price=current_price,
        )

    # ── Main Loop ──────────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        logger.info(
            f"ZeroLoss Controller v2 started | Symbols: {len(self._symbols)} | "
            f"Threshold: {self._threshold} | RR: 1:{self._rr_ratio} | "
            f"Max positions: {self.MAX_CONCURRENT_POSITIONS}"
        )

        scan_counter = 0
        while self._running:
            try:
                await self._maybe_reset_daily()

                if not self._enabled:
                    await asyncio.sleep(self.SCAN_INTERVAL)
                    continue

                if not market_session.is_live_trading_session():
                    if self._enabled:
                        logger.info(
                            "ZeroLoss halted — market not open (%s)",
                            market_session.get_current_state().value,
                        )
                        self.disable()
                        if self._user_id:
                            from strategies.zeroloss.manager import zeroloss_manager

                            await zeroloss_manager.disable(
                                self._user_id, close_positions=False
                            )
                    await asyncio.sleep(self.SCAN_INTERVAL)
                    continue

                # ── Phase 0: Update market regime (every 60s) ──
                await self._update_market_regime()

                # ── Phase 1: Monitor active positions + trailing stops ──
                if self._active_positions:
                    await self._monitor_active_positions()

                # ── Phase 2: Force-close check (3:20 PM IST) ──
                await self._check_force_close()

                # ── Phase 3: Always scan for confidence (even in NEUTRAL) ──
                # This keeps the UI alive with confidence scores.
                # Trade execution is gated inside _scan_for_signals().
                scan_counter += 1
                if scan_counter >= (self.SCAN_INTERVAL // self.MONITOR_INTERVAL):
                    scan_counter = 0
                    await self._scan_for_signals()

                await asyncio.sleep(self.MONITOR_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"ZeroLoss Controller error: {e}", exc_info=True)
                await asyncio.sleep(5)

        logger.info("ZeroLoss Controller stopped")

    async def stop(self) -> None:
        self._running = False

    # ── Market Regime Detection ───────────────────────────────────────────────

    async def _update_market_regime(self) -> None:
        """
        Detect overall market direction using Nifty 50 EMA spread.
        Simple and reliable — just EMA-9 vs EMA-21 spread percentage.

        Also runs institutional MarketRegimeEngine (additive) for trade permission
        and market quality without replacing legacy BULLISH/BEARISH/NEUTRAL.
        """
        now = datetime.now(timezone.utc)

        if (
            self._regime_last_checked
            and (now - self._regime_last_checked).total_seconds() < 45
        ):
            return

        self._regime_last_checked = now

        try:
            candles = await market_data.get_historical_data(
                NIFTY_SYMBOL, self.CANDLE_PERIOD, self.CANDLE_INTERVAL
            )
            if not candles or len(candles) < 25:
                logger.debug("Nifty data insufficient for regime detection")
                return

            closes = [c["close"] for c in candles]

            from engines.indicators import IndicatorEngine

            ema_9 = IndicatorEngine.ema(closes, 9)
            ema_21 = IndicatorEngine.ema(closes, 21)

            e9 = ema_9[-1] if ema_9 else None
            e21 = ema_21[-1] if ema_21 else None

            if e9 is None or e21 is None:
                return

            spread_pct = (e9 - e21) / e21 * 100 if e21 != 0 else 0

            old_regime = self._market_regime

            # 0.05% spread threshold — cleaner regime detection, less noise
            if spread_pct > 0.05:
                self._market_regime = "BULLISH"
                self._regime_strength = min(abs(spread_pct) * 20, 100)
            elif spread_pct < -0.05:
                self._market_regime = "BEARISH"
                self._regime_strength = min(abs(spread_pct) * 20, 100)
            else:
                self._market_regime = "NEUTRAL"
                self._regime_strength = 0

            if self._market_regime != old_regime:
                logger.info(
                    f"Market regime changed: {old_regime} → {self._market_regime} "
                    f"(Nifty EMA spread: {spread_pct:.3f}%)"
                )

            if self._use_regime_intelligence:
                session = SessionTradeFilter.evaluate()
                session_blocks = session.reasons if not session.allowed else []
                self._regime_snapshot = self._regime_engine.evaluate(
                    candles,
                    session_block_reasons=session_blocks,
                )
                if self._regime_snapshot.suppress_reasons:
                    logger.debug(
                        "Regime intelligence suppress: %s (quality=%.1f)",
                        self._regime_snapshot.suppress_reasons,
                        self._regime_snapshot.market_quality_score,
                    )

        except Exception as e:
            logger.warning(f"Market regime detection failed: {e}")

    def _institutional_trade_allowed(self) -> bool:
        """Additive gate — when disabled, legacy regime rules only apply."""
        if not self._use_regime_intelligence:
            return True
        if not market_session.is_live_trading_session():
            return False
        snap = self._regime_snapshot
        if snap is None:
            return True
        return snap.trade_permission

    # ── Time Filter ───────────────────────────────────────────────────────────

    def _is_entry_window(self) -> bool:
        """
        Check if current time is within the entry window.
        Blocks: before 9:30 AM and after 2:45 PM.
        """
        if not market_session.is_live_trading_session():
            return False

        if not market_session.is_trading_hours():
            return False

        now_ist = datetime.now(IST).time()

        if now_ist < MARKET_SETTLE_TIME:
            return False

        if now_ist >= NO_NEW_ENTRY_TIME:
            return False

        return True

    # ── Symbol Cooldown ──────────────────────────────────────────────────────

    def _is_on_cooldown(self, symbol: str) -> bool:
        """Check if a symbol is still in cooldown after a recent exit."""
        if symbol not in self._symbol_cooldowns:
            return False
        if datetime.now(timezone.utc) >= self._symbol_cooldowns[symbol]:
            del self._symbol_cooldowns[symbol]
            return False
        return True

    def _set_cooldown(self, symbol: str) -> None:
        """Set cooldown for a symbol after exit."""
        self._symbol_cooldowns[symbol] = datetime.now(timezone.utc) + timedelta(
            seconds=SYMBOL_COOLDOWN_SECONDS
        )

    # ── Dynamic Quantity ──────────────────────────────────────────────────────

    async def _compute_quantity(self, price: float) -> int:
        """Calculate trade quantity based on available capital."""
        if not self._user_id or price <= 0:
            return self._quantity

        try:
            from sqlalchemy import select as sa_select
            from models.portfolio import Portfolio

            async with async_session_factory() as session:
                result = await session.execute(
                    sa_select(Portfolio).where(Portfolio.user_id == self._user_id)
                )
                portfolio = result.scalar_one_or_none()
                if not portfolio:
                    return self._quantity

                available = float(portfolio.available_capital)
                active_count = len(self._active_positions)
                remaining_slots = max(1, self.MAX_CONCURRENT_POSITIONS - active_count)
                # More conservative allocation: 20% per slot (was 30%)
                alloc_pct = min(0.20, 0.50 / remaining_slots)
                # MIS gives 5x leverage
                max_position_value = available * alloc_pct * 5
                qty = int(max_position_value / price)
                return max(qty, 1)
        except Exception as e:
            logger.warning(f"[ZeroLoss] Quantity calc failed: {e}")
            return self._quantity

    # ── Order Execution ──────────────────────────────────────────────────────

    async def _place_trade(
        self, symbol: str, side: str, quantity: int, price: float
    ) -> Optional[dict]:
        if not self._user_id:
            logger.warning("[ZeroLoss] Cannot place order — no user_id")
            return None

        try:
            async with async_session_factory() as db:
                result = await place_order(
                    db=db,
                    user_id=self._user_id,
                    symbol=symbol,
                    side=side,
                    order_type="MARKET",
                    quantity=quantity,
                    client_price=price,
                    product_type="MIS",
                    tag="ZEROLOSS",
                    bypass_market_session=True,
                )
                await db.commit()

                if result.get("success"):
                    order_info = result.get("order", {})
                    logger.info(
                        f"[ZeroLoss] {side} {quantity}x {symbol} @ ₹{price:.2f} "
                        f"→ {order_info.get('status', '?')}"
                    )
                else:
                    logger.error(
                        f"[ZeroLoss] ORDER REJECTED {symbol} {side} qty={quantity} "
                        f"@ ₹{price:.2f} — reason: {result.get('error')}"
                    )

                return result
        except Exception as e:
            logger.error(f"[ZeroLoss] Order error {symbol}: {e}", exc_info=True)
            return None

    # ── Scan for New Signals ───────────────────────────────────────────────────

    async def _scan_for_signals(self) -> None:
        """
        Always scan all symbols for confidence scores (keeps UI alive).
        Only execute trades when:
        1. Entry window is open (time filter)
        2. Signal direction aligns with market regime
           (or simulation-mode neutral override with higher confidence)
        4. All quality gates pass
        5. Symbol not on cooldown
        """
        can_trade = (
            self._is_entry_window()
            and len(self._active_positions) < self.MAX_CONCURRENT_POSITIONS
        )
        institutional_allowed = self._institutional_trade_allowed()
        entries_opened = 0

        for symbol in self._symbols:
            try:
                candles = await market_data.get_historical_data(
                    symbol, self.CANDLE_PERIOD, self.CANDLE_INTERVAL
                )
                if not candles or len(candles) < 55:
                    continue

                closes = [c["close"] for c in candles]
                highs = [c["high"] for c in candles]
                lows = [c["low"] for c in candles]
                volumes = [c["volume"] for c in candles]

                quote = await market_data.get_system_quote_safe(symbol)
                if not quote or not quote.get("price"):
                    continue

                current_price = quote["price"]

                # ALWAYS score confidence — keeps UI populated
                confidence = self._confidence.score(
                    closes=closes,
                    highs=highs,
                    lows=lows,
                    volumes=volumes,
                    vix=None,
                )

                logger.info(
                    f"[{symbol}] Confidence={confidence.total:.1f} "
                    f"Dir={confidence.direction} Regime={self._market_regime}"
                )

                # ALWAYS store + broadcast confidence for UI
                self._latest_confidence[symbol] = {
                    "symbol": symbol,
                    "score": confidence.total,
                    "direction": confidence.direction,
                    "breakdown": {
                        "ema": confidence.ema_score,
                        "rsi": confidence.rsi_score,
                        "macd": confidence.macd_score,
                        "volume": confidence.volume_score,
                        "volatility": confidence.volatility_score,
                        "support_resistance": confidence.sr_score,
                        "vwap": confidence.vwap_score,
                        "trend_strength": confidence.trend_strength_score,
                    },
                    "reasons": confidence.reasons,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                await event_bus.emit(
                    Event(
                        type=EventType.ALGO_SIGNAL,
                        data={
                            "channel": "zeroloss",
                            "type": "confidence_update",
                            "confidence": self._latest_confidence[symbol],
                            "stats": self.get_stats(),
                        },
                        user_id=self._user_id_text(),
                        source="zeroloss_controller",
                    )
                )

                # ── Trade execution gates (only if conditions are met) ──
                if not can_trade:
                    continue
                if entries_opened >= self.MAX_NEW_ENTRIES_PER_SCAN:
                    continue

                if symbol in self._active_positions:
                    continue
                if self._is_on_cooldown(symbol):
                    continue
                if len(self._active_positions) >= self.MAX_CONCURRENT_POSITIONS:
                    continue

                trade_qty = await self._compute_quantity(current_price)

                signal = self._signal_gen.generate(
                    confidence=confidence,
                    symbol=symbol,
                    current_price=current_price,
                    quantity=trade_qty,
                )

                if signal.direction not in ("LONG", "SHORT"):
                    fallback_signal = self._build_simulation_fallback_signal(
                        symbol=symbol,
                        confidence=confidence,
                        current_price=current_price,
                        quantity=trade_qty,
                        closes=closes,
                    )
                    if fallback_signal is not None:
                        signal = fallback_signal

                logger.info(
                    f"[{symbol}] Signal: dir={signal.direction} "
                    f"score={signal.confidence_score:.1f} qty={trade_qty}"
                )

                if signal.direction in ("LONG", "SHORT"):
                    is_sim = market_session.simulation_mode
                    if not institutional_allowed and signal.confidence_score < self._threshold + 8.0:
                        logger.info(
                            f"[{symbol}] BLOCKED — institutional regime filter; "
                            f"needs high conviction {self._threshold + 8.0:.1f}, "
                            f"got {signal.confidence_score:.1f}"
                        )
                        continue
                    if not is_sim:
                        if self._market_regime == "NEUTRAL":
                            if signal.confidence_score < self.NEUTRAL_REGIME_THRESHOLD:
                                logger.info(
                                    f"[{symbol}] NEUTRAL regime — needs "
                                    f"{self.NEUTRAL_REGIME_THRESHOLD}, got "
                                    f"{signal.confidence_score:.1f}"
                                )
                                continue
                        else:
                            aligns = (
                                signal.direction == "LONG"
                                and self._market_regime == "BULLISH"
                            ) or (
                                signal.direction == "SHORT"
                                and self._market_regime == "BEARISH"
                            )
                            if not aligns and signal.confidence_score < self._threshold + 5.0:
                                logger.info(
                                    f"[{symbol}] BLOCKED — {signal.direction} opposes "
                                    f"{self._market_regime}"
                                )
                                continue

                    # Place order
                    trade_side = "BUY" if signal.direction == "LONG" else "SELL"
                    order_result = await self._place_trade(
                        symbol=symbol,
                        side=trade_side,
                        quantity=trade_qty,
                        price=current_price,
                    )

                    if order_result and order_result.get("success"):
                        signal.status = "ACTIVE"
                        signal.order_id = order_result["order"].get("id")
                        signal.trade_qty = trade_qty
                        signal.peak_price = current_price
                        self._active_positions[symbol] = signal
                        entries_opened += 1
                        self._total_trades += 1

                        await self._persist_signal(signal)

                        await event_bus.emit(
                            Event(
                                type=EventType.ALGO_TRADE,
                                data={
                                    "channel": "zeroloss",
                                    "action": "ENTRY",
                                    "signal": signal.to_dict(),
                                    "order": order_result.get("order"),
                                    "market_regime": self._market_regime,
                                    "stats": self.get_stats(),
                                },
                                user_id=self._user_id_text(),
                                source="zeroloss_controller",
                            )
                        )

                        logger.info(
                            f"[{symbol}] ENTERED {signal.direction} | "
                            f"Confidence: {signal.confidence_score:.1f} | "
                            f"Entry: ₹{current_price:.2f} | SL: ₹{signal.stop_loss:.2f} | "
                            f"Target: ₹{signal.target:.2f} | Qty: {trade_qty}"
                        )
                    else:
                        logger.warning(f"[{symbol}] Order failed — skipping")

            except Exception as e:
                logger.error(f"[{symbol}] Scan error: {e}", exc_info=True)

    # ── Monitor Active Positions (with Trailing Stop + Momentum Exit) ────────

    async def _monitor_active_positions(self) -> None:
        """
        Monitor positions with:
        1. Trailing stop-loss system
        2. Momentum reversal exit (MACD flips against position)
        3. Target hit
        """
        closed_symbols: list[str] = []

        for symbol, signal in self._active_positions.items():
            try:
                quote = await market_data.get_system_quote_safe(symbol)
                if not quote or not quote.get("price"):
                    continue

                current_price = quote["price"]

                # ── Simulation price advancement ──────────────────────────────
                # On holidays/weekends prices are frozen; nudge the simulated price
                # toward the target so exits can be triggered for demo purposes.
                if market_session.is_live_trading_session() and market_session.simulation_mode and signal.entry_price:
                    age_seconds = (
                        datetime.now(timezone.utc) - signal.timestamp
                    ).total_seconds()
                    # After 3 min, simulate 0.05% per monitor cycle toward target
                    if age_seconds > 180:
                        nudge_pct = 0.0005  # 0.05% per 3-second cycle
                        if signal.direction == "LONG":
                            current_price = min(
                                current_price * (1 + nudge_pct), signal.target
                            )
                        else:
                            current_price = max(
                                current_price * (1 - nudge_pct), signal.target
                            )

                # Track peak price for display
                if signal.direction == "LONG":
                    if signal.peak_price is None or current_price > signal.peak_price:
                        signal.peak_price = current_price
                else:
                    if signal.peak_price is None or current_price < signal.peak_price:
                        signal.peak_price = current_price

                # Grace period: 60 seconds for trade to develop (was 45)
                age_seconds = (
                    datetime.now(timezone.utc) - signal.timestamp
                ).total_seconds()
                if age_seconds < 60:
                    # Only check target during grace
                    if signal.direction == "LONG" and current_price >= signal.target:
                        pass  # Fall through to exit logic
                    elif signal.direction == "SHORT" and current_price <= signal.target:
                        pass
                    else:
                        continue

                # ── Update trailing stop-loss ──
                new_sl = self._breakeven.compute_trailing_sl(
                    direction=signal.direction,
                    entry_price=signal.entry_price,
                    current_price=current_price,
                    current_sl=signal.stop_loss,
                )

                if new_sl != signal.stop_loss:
                    old_sl = signal.stop_loss
                    signal.stop_loss = new_sl
                    logger.info(
                        f"[{symbol}] Trailing SL updated: ₹{old_sl:.2f} → ₹{new_sl:.2f} "
                        f"(price: ₹{current_price:.2f})"
                    )

                # ── Check exit conditions ──
                exit_reason = self._breakeven.check_exit(
                    direction=signal.direction,
                    entry_price=signal.entry_price,
                    current_price=current_price,
                    stop_loss=signal.stop_loss,
                    target=signal.target,
                )

                # ── Momentum reversal exit (after 2 min) ──
                if exit_reason is None and age_seconds > 120:
                    exit_reason = await self._check_momentum_reversal(symbol, signal)

                if exit_reason is not None:
                    signal.status = exit_reason
                    qty = signal.trade_qty or self._quantity

                    close_side = "SELL" if signal.direction == "LONG" else "BUY"
                    close_result = await self._place_trade(
                        symbol=symbol,
                        side=close_side,
                        quantity=qty,
                        price=current_price,
                    )

                    if not close_result or not close_result.get("success"):
                        logger.warning(
                            f"[{symbol}] Exit order failed — retry next cycle"
                        )
                        continue

                    if signal.direction == "LONG":
                        pnl = (current_price - signal.entry_price) * qty
                    else:
                        pnl = (signal.entry_price - current_price) * qty
                    net_pnl = round(pnl, 2)

                    if exit_reason == "PROFIT":
                        self._profit_trades += 1
                    elif net_pnl >= 0:
                        self._breakeven_trades += 1
                    else:
                        self._loss_trades += 1
                    self._net_pnl += net_pnl

                    # Set cooldown for this symbol
                    self._set_cooldown(symbol)

                    await self._persist_signal_update(signal, net_pnl)

                    await event_bus.emit(
                        Event(
                            type=EventType.ALGO_TRADE,
                            data={
                                "channel": "zeroloss",
                                "action": "EXIT",
                                "reason": exit_reason,
                                "signal": signal.to_dict(),
                                "pnl": net_pnl,
                                "order": close_result.get("order"),
                                "stats": self.get_stats(),
                            },
                            user_id=self._user_id_text(),
                            source="zeroloss_controller",
                        )
                    )

                    closed_symbols.append(symbol)
                    logger.info(
                        f"[{symbol}] CLOSED — {exit_reason} | PnL: ₹{net_pnl:.2f}"
                    )

            except Exception as e:
                logger.error(f"[{symbol}] Monitor error: {e}", exc_info=True)

        for sym in closed_symbols:
            self._active_positions.pop(sym, None)

    async def _check_momentum_reversal(
        self, symbol: str, signal: ZeroLossSignal
    ) -> Optional[str]:
        """
        Check if MACD momentum has reversed against the position.
        Exit early to avoid turning a small profit into a loss.
        Only triggers if position is at a small profit or tiny loss (> -0.3%).
        """
        try:
            candles = await market_data.get_historical_data(
                symbol, self.CANDLE_PERIOD, self.CANDLE_INTERVAL
            )
            if not candles or len(candles) < 30:
                return None

            closes = [c["close"] for c in candles]
            from engines.indicators import IndicatorEngine

            macd_result = IndicatorEngine.macd(closes)
            if macd_result is None:
                return None

            hist = macd_result.histogram
            valid_hist = [h for h in hist if h is not None]
            if len(valid_hist) < 3:
                return None

            curr_hist = valid_hist[-1]
            prev_hist = valid_hist[-2]
            prev2_hist = valid_hist[-3]

            current_price = closes[-1]

            # Check if position is at small profit or tiny loss
            if signal.direction == "LONG":
                profit_pct = (current_price - signal.entry_price) / signal.entry_price
                # MACD crossed from positive to negative (momentum died)
                macd_reversed = curr_hist < 0 and prev_hist > 0
                # Or MACD is negative and getting worse
                macd_collapsing = curr_hist < prev_hist < prev2_hist < 0
            else:
                profit_pct = (signal.entry_price - current_price) / signal.entry_price
                macd_reversed = curr_hist > 0 and prev_hist < 0
                macd_collapsing = curr_hist > prev_hist > prev2_hist > 0

            # Only exit on reversal if we're not deep in profit (trailing stop handles that)
            # and not deep in loss (let SL handle that)
            if (macd_reversed or macd_collapsing) and -0.003 < profit_pct < 0.015:
                logger.info(
                    f"[{symbol}] Momentum reversal detected | MACD hist: {curr_hist:.4f} | "
                    f"Profit: {profit_pct*100:.2f}% — exiting early"
                )
                return "STOPLOSS"  # Early exit on reversal

        except Exception as e:
            logger.debug(f"[{symbol}] Momentum check failed: {e}")

        return None

    # ── Force Close (3:20 PM IST) ──────────────────────────────────────────────

    async def _check_force_close(self) -> None:
        now_ist = datetime.now(IST)
        current_time = now_ist.time()

        if current_time < FORCE_CLOSE_TIME:
            return
        # Skip force-close on weekends and exchange holidays only (not simulation).
        if now_ist.weekday() >= 5:
            return
        state = market_session.get_current_state()
        if state in (MarketState.WEEKEND, MarketState.HOLIDAY):
            return

        closed_symbols: list[str] = []

        for symbol, signal in self._active_positions.items():
            try:
                qty = signal.trade_qty or self._quantity
                quote = await market_data.get_system_quote_safe(symbol)
                current_price = quote["price"] if quote else signal.entry_price

                close_side = "SELL" if signal.direction == "LONG" else "BUY"
                close_result = await self._place_trade(
                    symbol=symbol,
                    side=close_side,
                    quantity=qty,
                    price=current_price,
                )

                if not close_result or not close_result.get("success"):
                    logger.warning(
                        f"[{symbol}] 3:20 PM force-close failed: "
                        f"{close_result.get('error') if close_result else 'order failed'}"
                    )
                    continue

                if signal.direction == "LONG":
                    pnl = (current_price - signal.entry_price) * qty
                else:
                    pnl = (signal.entry_price - current_price) * qty
                net_pnl = round(pnl, 2)

                if net_pnl > 0:
                    signal.status = "PROFIT"
                    self._profit_trades += 1
                else:
                    signal.status = "STOPLOSS"
                    self._loss_trades += 1
                self._net_pnl += net_pnl

                await self._persist_signal_update(signal, net_pnl)

                await event_bus.emit(
                    Event(
                        type=EventType.ALGO_TRADE,
                        data={
                            "channel": "zeroloss",
                            "action": "FORCE_CLOSE",
                            "reason": "3:20 PM IST market close",
                            "signal": signal.to_dict(),
                            "pnl": net_pnl,
                            "order": close_result.get("order"),
                            "stats": self.get_stats(),
                        },
                        user_id=self._user_id_text(),
                        source="zeroloss_controller",
                    )
                )

                closed_symbols.append(symbol)
                logger.info(f"[{symbol}] Force-closed | PnL: ₹{net_pnl:.2f}")

            except Exception as e:
                logger.error(f"[{symbol}] Force-close error: {e}", exc_info=True)

        for sym in closed_symbols:
            self._active_positions.pop(sym, None)

    # ── Daily Reset ────────────────────────────────────────────────────────────

    async def _maybe_reset_daily(self) -> None:
        today = datetime.now(IST).date()
        if self._today != today:
            self._today = today
            self._total_trades = 0
            self._profit_trades = 0
            self._breakeven_trades = 0
            self._loss_trades = 0
            self._net_pnl = 0.0
            self._market_regime = "NEUTRAL"
            self._regime_last_checked = None
            self._symbol_cooldowns.clear()

    # ── Database Persistence ───────────────────────────────────────────────────

    async def _persist_signal(self, signal: ZeroLossSignal) -> None:
        user_id_text = self._user_id_text()
        if not user_id_text:
            return
        try:
            async with async_session_factory() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO zeroloss_signals
                            (user_id, symbol, timestamp, confidence_score, direction,
                             entry_price, stop_loss, target, status, pnl)
                        VALUES (:user_id, :symbol, :ts, :score, :dir, :entry, :sl, :tgt, :status, :pnl)
                    """
                    ),
                    {
                        "user_id": user_id_text,
                        "symbol": signal.symbol,
                        "ts": signal.timestamp,
                        "score": signal.confidence_score,
                        "dir": signal.direction,
                        "entry": signal.entry_price,
                        "sl": signal.stop_loss,
                        "tgt": signal.target,
                        "status": signal.status,
                        "pnl": 0,
                    },
                )
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to persist signal: {e}")

    async def _persist_signal_update(self, signal: ZeroLossSignal, pnl: float) -> None:
        user_id_text = self._user_id_text()
        if not user_id_text:
            return
        try:
            async with async_session_factory() as session:
                await session.execute(
                    text(
                        """
                        UPDATE zeroloss_signals
                        SET status = :status, pnl = :pnl
                        WHERE user_id = :user_id AND symbol = :symbol AND timestamp = :ts
                    """
                    ),
                    {
                        "user_id": user_id_text,
                        "status": signal.status,
                        "pnl": pnl,
                        "symbol": signal.symbol,
                        "ts": signal.timestamp,
                    },
                )
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to update signal: {e}")

    async def _persist_daily_performance(self) -> None:
        user_id_text = self._user_id_text()
        if not user_id_text or self._today is None:
            return
        try:
            async with async_session_factory() as session:
                existing = await session.execute(
                    text(
                        """
                        SELECT id
                        FROM zeroloss_performance
                        WHERE user_id = :user_id AND date = :date
                        LIMIT 1
                        """
                    ),
                    {"user_id": user_id_text, "date": self._today},
                )
                row = existing.first()

                payload = {
                    "user_id": user_id_text,
                    "date": self._today,
                    "total": self._total_trades,
                    "profit": self._profit_trades,
                    "breakeven": self._breakeven_trades,
                    "loss": self._loss_trades,
                    "pnl": self._net_pnl,
                }
                if row:
                    await session.execute(
                        text(
                            """
                            UPDATE zeroloss_performance
                            SET total_trades = :total,
                                profit_trades = :profit,
                                breakeven_trades = :breakeven,
                                loss_trades = :loss,
                                net_pnl = :pnl
                            WHERE user_id = :user_id AND date = :date
                            """
                        ),
                        payload,
                    )
                else:
                    await session.execute(
                        text(
                            """
                            INSERT INTO zeroloss_performance
                                (user_id, date, total_trades, profit_trades, breakeven_trades,
                                 loss_trades, net_pnl)
                            VALUES (:user_id, :date, :total, :profit, :breakeven, :loss, :pnl)
                            """
                        ),
                        payload,
                    )
                await session.commit()
        except Exception as e:
            logger.warning(f"Failed to persist daily perf: {e}")


# ── Singleton ──
zeroloss_controller = ZeroLossController()
