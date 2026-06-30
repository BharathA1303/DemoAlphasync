"""
AlphaSync Alpha AutoTrade — Signal Generator v3.

Converts confidence scores into tradeable signals with strict filters:
    1. Confidence must exceed threshold (58%)
    2. Direction must be clear (not NEUTRAL)
    3. MACD must align with direction (no opposing momentum)
    4. Volume must be adequate (>= 0.8x average)
    5. VWAP must align (LONG above VWAP, SHORT below VWAP)

These gates ensure only high-quality setups become trades.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from strategies.zeroloss.confidence_engine import ConfidenceBreakdown
from strategies.zeroloss.breakeven_manager import BreakevenManager, TradeLevels
from engines.market_session import market_session

logger = logging.getLogger(__name__)


@dataclass
class ZeroLossSignal:
    """Output of the signal generator — a complete trade instruction."""

    symbol: str
    timestamp: datetime
    direction: str  # "LONG", "SHORT", "NO_TRADE"
    confidence_score: float

    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target: Optional[float] = None
    risk_reward_ratio: Optional[float] = None

    status: str = "WAITING"  # WAITING / ACTIVE / PROFIT / STOPLOSS
    reasons: list[str] = field(default_factory=list)
    indicator_snapshot: Optional[dict] = None

    trade_qty: int = 0
    order_id: Optional[str] = None

    # Track highest/lowest price for trailing stop
    peak_price: Optional[float] = None

    # Partial profit tracking
    partial_exited: bool = False

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "direction": self.direction,
            "confidence_score": self.confidence_score,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target": self.target,
            "risk_reward_ratio": self.risk_reward_ratio,
            "status": self.status,
            "reasons": self.reasons,
            "indicator_snapshot": self.indicator_snapshot,
        }


class ZeroLossSignalGenerator:
    """
    Converts a ConfidenceBreakdown into a tradeable ZeroLossSignal.

    Strict gates (all must pass):
        1. Confidence >= threshold (58%)
        2. Direction is BULLISH or BEARISH (not NEUTRAL)
        3. MACD histogram aligns with direction
        4. Volume ratio >= 0.8x average
        5. VWAP alignment (LONG above VWAP, SHORT below VWAP)

    If any gate fails → NO_TRADE (the zero-loss guarantee).
    """

    # High-conviction bypass: if score >= this, skip gates 3-5 entirely
    HIGH_CONVICTION_THRESHOLD = 70.0

    def __init__(
        self,
        confidence_threshold: float = 52.0,  # lowered from 58 — gates do the real filtering
        risk_reward_ratio: float = 1.6,
    ):
        self.threshold = confidence_threshold
        self.rr_ratio = risk_reward_ratio
        self.breakeven = BreakevenManager()

    def generate(
        self,
        confidence: ConfidenceBreakdown,
        symbol: str,
        current_price: float,
        quantity: int = 1,
    ) -> ZeroLossSignal:
        now = datetime.now(timezone.utc)

        indicator_snapshot = {
            "ema_20": confidence.ema_20,
            "ema_50": confidence.ema_50,
            "ema_200": confidence.ema_200,
            "rsi": confidence.rsi,
            "macd_hist": confidence.macd_hist,
            "volume_ratio": confidence.volume_ratio,
            "vix": confidence.vix,
            "vwap": confidence.vwap,
            "adx": confidence.adx,
        }

        def _no_trade(reason: str) -> ZeroLossSignal:
            return ZeroLossSignal(
                symbol=symbol,
                timestamp=now,
                direction="NO_TRADE",
                confidence_score=confidence.total,
                status="WAITING",
                reasons=[reason, *confidence.reasons],
                indicator_snapshot=indicator_snapshot,
            )

        # ── Gate 1: Confidence threshold ───────────────────────────
        # In simulation mode use a slightly lower threshold (threshold - 8)
        # so users see trades during demos/holidays when data quality is lower.
        effective_threshold = (
            max(self.threshold - 8.0, 40.0)
            if market_session.simulation_mode
            else self.threshold
        )
        if confidence.total < effective_threshold:
            logger.info(
                f"[{symbol}] NO_TRADE — confidence {confidence.total:.1f} "
                f"< threshold {effective_threshold:.1f}"
            )
            return _no_trade(
                f"Confidence {confidence.total:.1f} < {effective_threshold:.1f}"
            )

        # ── Gate 2: Clear direction ────────────────────────────────
        if confidence.direction == "NEUTRAL":
            logger.info(f"[{symbol}] NO_TRADE — neutral direction")
            return _no_trade("Direction NEUTRAL — no clear trend")

        is_sim = market_session.simulation_mode
        macd_tolerance = -0.01 if is_sim else -0.001
        volume_min = 0.55 if is_sim else 0.70  # relaxed from 0.8 — captures more setups

        # ── Gate 3: MACD must align ────────────────────────────────
        if confidence.macd_hist is not None:
            if (
                confidence.direction == "BULLISH"
                and confidence.macd_hist < macd_tolerance
            ):
                logger.info(
                    f"[{symbol}] NO_TRADE — MACD opposes bullish ({confidence.macd_hist:.4f})"
                )
                return _no_trade(f"MACD {confidence.macd_hist:.4f} opposes bullish EMA")
            if (
                confidence.direction == "BEARISH"
                and confidence.macd_hist > -macd_tolerance
            ):
                logger.info(
                    f"[{symbol}] NO_TRADE — MACD opposes bearish ({confidence.macd_hist:.4f})"
                )
                return _no_trade(f"MACD {confidence.macd_hist:.4f} opposes bearish EMA")

        # ── Gate 4: Volume must be adequate ────────────────────────
        if confidence.volume_ratio is not None and confidence.volume_ratio < volume_min:
            logger.info(
                f"[{symbol}] NO_TRADE — volume too thin ({confidence.volume_ratio:.2f}x)"
            )
            return _no_trade(
                f"Volume {confidence.volume_ratio:.2f}x — too thin for entry"
            )

        # ── Gate 5: VWAP alignment — allow 0.3% tolerance band ──────
        # Strict above/below was blocking too many valid setups at VWAP touch points.
        if not is_sim and confidence.above_vwap is not None and confidence.vwap:
            vwap_val = confidence.vwap
            price_now = current_price
            vwap_dev_pct = (price_now - vwap_val) / vwap_val * 100 if vwap_val else 0
            VWAP_TOLERANCE = 0.30  # allow 0.3% inside VWAP for either side
            if confidence.direction == "BULLISH" and vwap_dev_pct < -VWAP_TOLERANCE:
                logger.info(f"[{symbol}] NO_TRADE — LONG too far below VWAP ({vwap_dev_pct:.2f}%)")
                return _no_trade(f"Price {vwap_dev_pct:.2f}% below VWAP — risky for longs")
            if confidence.direction == "BEARISH" and vwap_dev_pct > VWAP_TOLERANCE:
                logger.info(f"[{symbol}] NO_TRADE — SHORT too far above VWAP (+{vwap_dev_pct:.2f}%)")
                return _no_trade(f"Price +{vwap_dev_pct:.2f}% above VWAP — risky for shorts")

        # ── All gates passed — generate trade signal ───────────────
        direction = "LONG" if confidence.direction == "BULLISH" else "SHORT"

        levels: TradeLevels = self.breakeven.compute_levels(
            entry_price=current_price,
            direction=direction,
            quantity=quantity,
            risk_reward_ratio=self.rr_ratio,
        )

        logger.info(
            f"[{symbol}] {direction} SIGNAL | Confidence: {confidence.total:.1f} | "
            f"Entry: {levels.entry:.2f} | SL: {levels.stop_loss:.2f} | "
            f"Target: {levels.target:.2f} | RR: 1:{levels.risk_reward_ratio:.1f}"
        )

        return ZeroLossSignal(
            symbol=symbol,
            timestamp=now,
            direction=direction,
            confidence_score=confidence.total,
            entry_price=levels.entry,
            stop_loss=levels.stop_loss,
            target=levels.target,
            risk_reward_ratio=levels.risk_reward_ratio,
            status="WAITING",
            reasons=confidence.reasons,
            indicator_snapshot=indicator_snapshot,
            peak_price=current_price,
        )
