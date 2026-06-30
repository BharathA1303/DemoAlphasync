"""
Algo Strategy Worker — Background algo trading runtime.

Periodically evaluates all ACTIVE strategies: fetches historical data,
computes indicators, generates signals, validates through risk engine,
and places orders automatically.

Key improvements:
    1. Position tracking — won't BUY if already long, or SELL if already short
    2. SL/TP monitoring — checks open positions each cycle for stop-loss / take-profit
    3. P&L calculation — computes realized P&L on every exit trade
    4. Strategy stats — updates win_rate and total_pnl on AlgoStrategy model
"""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.event_bus import event_bus, Event, EventType
from engines.market_session import market_session
from engines.signals import signal_generator
from engines.risk_engine import risk_engine
from database.connection import async_session_factory
from models.algo import AlgoStrategy, AlgoTrade, AlgoLog
from services import market_data
from services.trading_engine import place_order

logger = logging.getLogger(__name__)


class _OpenPosition:
    """Tracks an open algo position in memory."""

    __slots__ = (
        "strategy_id",
        "symbol",
        "side",
        "entry_price",
        "quantity",
        "stop_loss",
        "take_profit",
        "entry_time",
        "entry_trade_id",
    )

    def __init__(
        self,
        strategy_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: int,
        stop_loss: float,
        take_profit: float,
        entry_trade_id: Optional[str] = None,
    ):
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.side = side  # "BUY" (long) or "SELL" (short)
        self.entry_price = entry_price
        self.quantity = quantity
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.entry_time = datetime.now(timezone.utc)
        self.entry_trade_id = entry_trade_id


class AlgoStrategyWorker:
    """
    Schedules and executes algorithmic trading strategies.

    Each cycle:
    1. Monitor open positions for SL/TP hits (fast — every cycle)
    2. Evaluate strategies for new signals (slower — gated by cooldown)
    """

    EVAL_INTERVAL = 30  # seconds between evaluation cycles
    MONITOR_INTERVAL = 10  # seconds between SL/TP checks
    SIGNAL_COOLDOWN = 120  # seconds before re-evaluating a strategy after entry

    def __init__(self):
        self._running = False
        self._stats = {"cycles": 0, "signals": 0, "trades": 0, "exits": 0, "errors": 0}
        # strategy_id → _OpenPosition
        self._positions: dict[str, _OpenPosition] = {}
        # strategy_id → last signal timestamp (cooldown)
        self._last_signal_time: dict[str, float] = {}

    async def run(self) -> None:
        """Main loop — started via asyncio.create_task in lifespan."""
        self._running = True
        logger.info("Algo Strategy Worker started")

        cycle = 0
        while self._running:
            try:
                if not market_session.can_run_algo():
                    await asyncio.sleep(60)
                    continue

                # Monitor open positions every cycle (fast)
                if self._positions:
                    await self._monitor_open_positions()

                # Evaluate strategies for new signals every Nth cycle
                cycle += 1
                if cycle % max(1, self.EVAL_INTERVAL // self.MONITOR_INTERVAL) == 0:
                    await self._evaluate_all_strategies()
                    self._stats["cycles"] += 1

                await asyncio.sleep(self.MONITOR_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(f"Algo Strategy Worker error: {e}", exc_info=True)
                await asyncio.sleep(15)

        logger.info("Algo Strategy Worker stopped")

    # ── Position Monitoring ────────────────────────────────────────────────────

    async def _monitor_open_positions(self) -> None:
        """Check all open positions for SL/TP hit."""
        positions_to_close: list[tuple[str, str, float]] = (
            []
        )  # (strategy_id, reason, price)

        for sid, pos in list(self._positions.items()):
            try:
                quote = await market_data.get_quote_safe(pos.symbol, "system")
                if not quote or "price" not in quote:
                    continue

                current_price = float(quote["price"])

                if pos.side == "BUY":
                    # Long position: SL below entry, TP above entry
                    if current_price <= pos.stop_loss:
                        positions_to_close.append((sid, "STOP_LOSS", current_price))
                    elif current_price >= pos.take_profit:
                        positions_to_close.append((sid, "TAKE_PROFIT", current_price))

                elif pos.side == "SELL":
                    # Short position: SL above entry, TP below entry
                    if current_price >= pos.stop_loss:
                        positions_to_close.append((sid, "STOP_LOSS", current_price))
                    elif current_price <= pos.take_profit:
                        positions_to_close.append((sid, "TAKE_PROFIT", current_price))

            except Exception as e:
                logger.error(f"Monitor position error [{sid}]: {e}")

        # Close positions that hit SL/TP
        for sid, reason, exit_price in positions_to_close:
            await self._close_position(sid, reason, exit_price)

    async def _close_position(
        self, strategy_id: str, reason: str, exit_price: float
    ) -> None:
        """Close an open position and update P&L."""
        pos = self._positions.get(strategy_id)
        if not pos:
            return

        # Determine exit side (opposite of entry)
        exit_side = "SELL" if pos.side == "BUY" else "BUY"

        # Calculate P&L
        if pos.side == "BUY":
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity

        async with async_session_factory() as db:
            try:
                # Place the exit order
                order_result = await place_order(
                    db=db,
                    user_id="system",
                    symbol=pos.symbol,
                    side=exit_side,
                    order_type="MARKET",
                    quantity=pos.quantity,
                    tag="ALGO",
                )

                # Record exit trade with P&L
                exit_trade = AlgoTrade(
                    strategy_id=pos.strategy_id,
                    user_id="system",
                    symbol=pos.symbol,
                    side=exit_side,
                    quantity=pos.quantity,
                    price=Decimal(str(exit_price)),
                    pnl=Decimal(str(round(pnl, 2))),
                    signal=f"{reason} @ ₹{exit_price:.2f}",
                )
                db.add(exit_trade)

                # Update strategy stats
                strategy = await db.get(AlgoStrategy, pos.strategy_id)
                if strategy:
                    strategy.total_trades = (strategy.total_trades or 0) + 1
                    strategy.total_pnl = Decimal(
                        str(float(strategy.total_pnl or 0) + pnl)
                    )

                    # Calculate win rate from all trades with non-zero P&L
                    result = await db.execute(
                        select(AlgoTrade).where(
                            AlgoTrade.strategy_id == strategy.id,
                            AlgoTrade.pnl != 0,
                        )
                    )
                    all_exit_trades = result.scalars().all()
                    if all_exit_trades:
                        wins = sum(1 for t in all_exit_trades if float(t.pnl) > 0)
                        strategy.win_rate = Decimal(
                            str(round(wins / len(all_exit_trades) * 100, 2))
                        )

                db.add(
                    AlgoLog(
                        strategy_id=pos.strategy_id,
                        level="TRADE",
                        message=(
                            f"EXIT {exit_side} {pos.quantity}x {pos.symbol} "
                            f"@ ₹{exit_price:.2f} | {reason} | "
                            f"P&L: ₹{pnl:+,.2f}"
                        ),
                        data={
                            "entry_price": pos.entry_price,
                            "exit_price": exit_price,
                            "pnl": round(pnl, 2),
                            "reason": reason,
                            "hold_time_sec": (
                                datetime.now(timezone.utc) - pos.entry_time
                            ).total_seconds(),
                        },
                    )
                )

                await db.commit()
                self._stats["exits"] += 1

                logger.info(
                    f"[{pos.symbol}] {reason} exit — "
                    f"P&L: ₹{pnl:+,.2f} | Entry: {pos.entry_price:.2f} → Exit: {exit_price:.2f}"
                )

                await event_bus.emit(
                    Event(
                        type=EventType.ALGO_TRADE,
                        data={
                            "strategy_id": strategy_id,
                            "symbol": pos.symbol,
                            "side": exit_side,
                            "quantity": pos.quantity,
                            "price": exit_price,
                            "pnl": round(pnl, 2),
                            "reason": reason,
                        },
                        user_id="system",
                        source="algo_worker",
                    )
                )

            except Exception as e:
                await db.rollback()
                logger.error(
                    f"Failed to close position [{strategy_id}]: {e}", exc_info=True
                )
                return

        # Remove from tracking
        del self._positions[strategy_id]

    # ── Strategy Evaluation ────────────────────────────────────────────────────

    async def _evaluate_all_strategies(self) -> None:
        """Fetch all active strategies and evaluate each."""
        async with async_session_factory() as db:
            try:
                result = await db.execute(
                    select(AlgoStrategy).where(AlgoStrategy.is_active == True)
                )
                strategies = result.scalars().all()

                if not strategies:
                    return

                logger.debug(f"Evaluating {len(strategies)} active strategies")

                for strategy in strategies:
                    try:
                        await self._evaluate_strategy(db, strategy)
                    except Exception as e:
                        self._stats["errors"] += 1
                        logger.error(
                            f"Strategy evaluation failed [{strategy.id}]: {e}",
                            exc_info=True,
                        )
                        db.add(
                            AlgoLog(
                                strategy_id=strategy.id,
                                level="ERROR",
                                message=str(e)[:500],
                            )
                        )

                await db.commit()

            except Exception as e:
                await db.rollback()
                raise

    async def _evaluate_strategy(
        self, db: AsyncSession, strategy: AlgoStrategy
    ) -> None:
        """Evaluate a single strategy and potentially place an order."""
        sid = str(strategy.id)

        # Skip if already has an open position
        if sid in self._positions:
            return

        # Skip if in cooldown after last signal
        now_ts = datetime.now(timezone.utc).timestamp()
        last_ts = self._last_signal_time.get(sid, 0)
        if now_ts - last_ts < self.SIGNAL_COOLDOWN:
            return

        # ── Step 1: Fetch historical data ───────────────────────────
        candles = await market_data.get_historical_data(
            strategy.symbol,
            period="3mo",
            interval="1d",
            user_id=str(strategy.user_id),
        )

        if not candles or len(candles) < 30:
            db.add(
                AlgoLog(
                    strategy_id=strategy.id,
                    level="WARNING",
                    message=f"Insufficient historical data ({len(candles) if candles else 0} candles)",
                )
            )
            return

        closes = [c["close"] for c in candles if "close" in c]
        highs = [c.get("high", c["close"]) for c in candles]
        lows = [c.get("low", c["close"]) for c in candles]
        volumes = [c.get("volume", 0) for c in candles]

        # ── Step 2 & 3: Compute indicators + generate signal ──────
        parameters = (
            strategy.parameters if isinstance(strategy.parameters, dict) else {}
        )
        signal = signal_generator.evaluate(
            strategy_type=strategy.strategy_type,
            closes=closes,
            highs=highs,
            lows=lows,
            volumes=volumes,
            parameters=parameters,
        )

        self._stats["signals"] += 1

        # Log every signal (even HOLD for audit trail)
        db.add(
            AlgoLog(
                strategy_id=strategy.id,
                level="TRADE" if signal.action != "HOLD" else "INFO",
                message=f"[{signal.action}] {signal.reason}",
                data=signal.indicator_values,
            )
        )

        if signal.action == "HOLD":
            return

        # ── Step 4: Risk pre-check ────────────────────────────────
        quote = await market_data.get_quote_safe(strategy.symbol, str(strategy.user_id))
        if not quote or "price" not in quote:
            return

        current_price = float(quote["price"])
        try:
            quantity = int(float(parameters.get("quantity", 1)))
        except (TypeError, ValueError):
            quantity = 1
        quantity = max(1, min(quantity, 100000))

        risk_result = await risk_engine.validate_order(
            db=db,
            user_id=str(strategy.user_id),
            symbol=strategy.symbol,
            side=signal.action,
            order_type="MARKET",
            quantity=quantity,
            price=current_price,
            is_algo=True,
        )

        if not risk_result.passed:
            db.add(
                AlgoLog(
                    strategy_id=strategy.id,
                    level="WARNING",
                    message=f"Risk rejected {signal.action}: {risk_result.reason}",
                    data={
                        "check": risk_result.check_name,
                        "details": risk_result.details,
                    },
                )
            )

            await event_bus.emit(
                Event(
                    type=EventType.ALGO_ERROR,
                    data={
                        "strategy_id": sid,
                        "reason": risk_result.reason,
                    },
                    user_id=str(strategy.user_id),
                    source="algo_worker",
                )
            )
            return

        # ── Step 5: Compute SL/TP levels from strategy config ─────
        sl_pct = float(strategy.stop_loss_percent or 2.0) / 100.0
        tp_pct = float(strategy.take_profit_percent or 5.0) / 100.0

        if signal.action == "BUY":
            stop_loss = round(current_price * (1 - sl_pct), 2)
            take_profit = round(current_price * (1 + tp_pct), 2)
        else:  # SELL (short)
            stop_loss = round(current_price * (1 + sl_pct), 2)
            take_profit = round(current_price * (1 - tp_pct), 2)

        # ── Step 6: Place the order ───────────────────────────────
        try:
            order_result = await place_order(
                db=db,
                user_id=str(strategy.user_id),
                symbol=strategy.symbol,
                side=signal.action,
                order_type="MARKET",
                quantity=quantity,
                tag="ALGO",
            )

            if order_result.get("success"):
                self._stats["trades"] += 1

                # Record entry trade
                entry_trade = AlgoTrade(
                    strategy_id=strategy.id,
                    user_id=str(strategy.user_id),
                    symbol=strategy.symbol,
                    side=signal.action,
                    quantity=quantity,
                    price=Decimal(str(current_price)),
                    signal=signal.reason[:50] if signal.reason else None,
                )
                db.add(entry_trade)
                await db.flush()  # get the trade ID

                # Track the open position
                self._positions[sid] = _OpenPosition(
                    strategy_id=sid,
                    symbol=strategy.symbol,
                    side=signal.action,
                    entry_price=current_price,
                    quantity=quantity,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    entry_trade_id=str(entry_trade.id),
                )
                self._last_signal_time[sid] = datetime.now(timezone.utc).timestamp()

                db.add(
                    AlgoLog(
                        strategy_id=strategy.id,
                        level="TRADE",
                        message=(
                            f"ENTRY {signal.action} {quantity}x {strategy.symbol} "
                            f"@ ₹{current_price:.2f} | SL: ₹{stop_loss:.2f} | "
                            f"TP: ₹{take_profit:.2f} | {signal.reason}"
                        ),
                        data={
                            "entry_price": current_price,
                            "stop_loss": stop_loss,
                            "take_profit": take_profit,
                            "confidence": signal.confidence,
                            **signal.indicator_values,
                        },
                    )
                )

                await event_bus.emit(
                    Event(
                        type=EventType.ALGO_TRADE,
                        data={
                            "strategy_id": sid,
                            "symbol": strategy.symbol,
                            "side": signal.action,
                            "quantity": quantity,
                            "price": current_price,
                            "stop_loss": stop_loss,
                            "take_profit": take_profit,
                            "reason": signal.reason,
                        },
                        user_id=str(strategy.user_id),
                        source="algo_worker",
                    )
                )

                logger.info(
                    f"[{strategy.symbol}] ENTRY {signal.action} @ ₹{current_price:.2f} "
                    f"| SL: ₹{stop_loss:.2f} | TP: ₹{take_profit:.2f}"
                )
            else:
                db.add(
                    AlgoLog(
                        strategy_id=strategy.id,
                        level="ERROR",
                        message=f"Order placement failed: {order_result.get('error', 'Unknown error')}",
                    )
                )

        except Exception as e:
            db.add(
                AlgoLog(
                    strategy_id=strategy.id,
                    level="ERROR",
                    message=f"Order placement error: {str(e)[:200]}",
                )
            )
            raise

    # ── Close all positions (called when strategy is deactivated) ─────────────

    async def close_strategy_position(self, strategy_id: str) -> Optional[float]:
        """Force-close an open position for a specific strategy. Returns P&L or None."""
        sid = str(strategy_id)
        pos = self._positions.get(sid)
        if not pos:
            return None

        quote = await market_data.get_quote_safe(pos.symbol, "system")
        if not quote or "price" not in quote:
            # Remove from tracking even if we can't get a quote
            del self._positions[sid]
            return None

        current_price = float(quote["price"])
        await self._close_position(sid, "STRATEGY_STOPPED", current_price)
        return current_price

    async def stop(self) -> None:
        self._running = False

    def get_stats(self) -> dict:
        stats = self._stats.copy()
        stats["open_positions"] = len(self._positions)
        stats["positions"] = {
            sid: {
                "symbol": p.symbol,
                "side": p.side,
                "entry": p.entry_price,
                "sl": p.stop_loss,
                "tp": p.take_profit,
                "qty": p.quantity,
            }
            for sid, p in self._positions.items()
        }
        return stats


# ── Singleton ──────────────────────────────────────────────────────
algo_strategy_worker = AlgoStrategyWorker()
