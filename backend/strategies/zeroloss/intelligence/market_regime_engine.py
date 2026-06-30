"""
Institutional-style market regime intelligence (Phase A).

Additive layer: does not replace controller EMA spread regime; maps into legacy
BULLISH/BEARISH/NEUTRAL and adds trade_permission + market_quality_score.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from engines.indicators import IndicatorEngine

logger = logging.getLogger(__name__)


@dataclass
class MarketRegimeSnapshot:
    """Full regime state exposed to controller / API stats."""

    timestamp: str
    regime: str  # primary label
    legacy_direction: str  # BULLISH | BEARISH | NEUTRAL
    market_quality_score: float  # 0-100
    trade_permission: bool
    regime_confidence: float  # 0-100
    suppress_reasons: list[str] = field(default_factory=list)
    htf_1h: str = "NEUTRAL"
    htf_15m: str = "NEUTRAL"
    htf_5m: str = "NEUTRAL"
    atr_ratio: Optional[float] = None
    adx_proxy: Optional[float] = None
    overlap_pct: Optional[float] = None
    trend_persistence: Optional[float] = None
    volatility_state: str = "NORMAL"
    liquidity_state: str = "NORMAL"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketRegimeEngine:
    """
    Detects market structure and trade permission from OHLCV candles.

    Designed for a single benchmark symbol (NIFTY) per evaluation cycle.
    Higher timeframes are derived in-memory from 5m bars to avoid extra API calls.
    """

    MIN_BARS = 40
    CHOP_OVERLAP_THRESHOLD = 62.0
    CHOP_ADX_MAX = 22.0
    TREND_ADX_MIN = 26.0
    ATR_COMPRESSION_RATIO = 0.82
    ATR_EXPANSION_RATIO = 1.28
    LOW_LIQ_VOLUME_RATIO = 0.55

    def evaluate(
        self,
        candles_5m: list[dict],
        *,
        benchmark_volume_ratio: Optional[float] = None,
        session_block_reasons: Optional[list[str]] = None,
    ) -> MarketRegimeSnapshot:
        now = datetime.now(timezone.utc).isoformat()
        suppress: list[str] = list(session_block_reasons or [])

        if not candles_5m or len(candles_5m) < self.MIN_BARS:
            return MarketRegimeSnapshot(
                timestamp=now,
                regime="UNKNOWN",
                legacy_direction="NEUTRAL",
                market_quality_score=0.0,
                trade_permission=False,
                regime_confidence=0.0,
                suppress_reasons=["insufficient_candles", *suppress],
            )

        closes = [float(c["close"]) for c in candles_5m]
        highs = [float(c["high"]) for c in candles_5m]
        lows = [float(c["low"]) for c in candles_5m]
        volumes = [float(c.get("volume") or 0) for c in candles_5m]

        htf_5m = self._direction_from_closes(closes, fast=9, slow=21)
        candles_15m = self._resample(candles_5m, 3)
        candles_1h = self._resample(candles_5m, 12)
        htf_15m = (
            self._direction_from_closes(
                [float(c["close"]) for c in candles_15m], fast=8, slow=21
            )
            if len(candles_15m) >= 25
            else "NEUTRAL"
        )
        htf_1h = (
            self._direction_from_closes(
                [float(c["close"]) for c in candles_1h], fast=8, slow=21
            )
            if len(candles_1h) >= 20
            else "NEUTRAL"
        )

        atr_series = IndicatorEngine.atr(highs, lows, closes, 14)
        atr_now = atr_series[-1] if atr_series else None
        atr_prev = atr_series[-6] if atr_series and len(atr_series) >= 6 else None
        atr_ratio = (
            round(atr_now / atr_prev, 3)
            if atr_now and atr_prev and atr_prev > 0
            else None
        )

        overlap_pct = self._candle_overlap_pct(highs, lows, closes)
        adx_proxy = self._adx_proxy(highs, lows, closes)
        trend_persistence = self._trend_persistence(closes)

        vol_state = "NORMAL"
        if atr_ratio is not None:
            if atr_ratio >= self.ATR_EXPANSION_RATIO:
                vol_state = "EXPANSION"
            elif atr_ratio <= self.ATR_COMPRESSION_RATIO:
                vol_state = "COMPRESSION"

        liq_state = "NORMAL"
        vol_ratio = benchmark_volume_ratio
        if vol_ratio is None:
            vol_ratio = self._volume_ratio(volumes)
        if vol_ratio is not None and vol_ratio < self.LOW_LIQ_VOLUME_RATIO:
            liq_state = "LOW"
            suppress.append("low_liquidity")

        regime, legacy, confidence = self._classify_regime(
            htf_1h=htf_1h,
            htf_15m=htf_15m,
            htf_5m=htf_5m,
            overlap_pct=overlap_pct,
            adx_proxy=adx_proxy,
            atr_ratio=atr_ratio,
            trend_persistence=trend_persistence,
            vol_state=vol_state,
        )

        if overlap_pct >= self.CHOP_OVERLAP_THRESHOLD and adx_proxy < self.CHOP_ADX_MAX:
            regime = "SIDEWAYS_CHOP"
            suppress.append("sideways_chop")

        if vol_state == "EXPANSION" and adx_proxy < 18:
            regime = "HIGH_VOL_UNSTABLE"
            suppress.append("unstable_volatility_spike")

        if vol_state == "COMPRESSION" and adx_proxy < self.CHOP_ADX_MAX:
            suppress.append("volatility_compression_chop")

        if self._momentum_exhaustion(closes, highs, lows):
            suppress.append("momentum_exhaustion")

        if not self._htf_aligned(htf_1h, htf_15m, htf_5m):
            suppress.append("htf_misalignment")

        quality = self._market_quality_score(
            regime=regime,
            confidence=confidence,
            overlap_pct=overlap_pct,
            adx_proxy=adx_proxy,
            htf_aligned=self._htf_aligned(htf_1h, htf_15m, htf_5m),
            liq_state=liq_state,
            suppress_count=len(suppress),
        )

        trade_permission = len(suppress) == 0 and quality >= 42.0

        return MarketRegimeSnapshot(
            timestamp=now,
            regime=regime,
            legacy_direction=legacy,
            market_quality_score=round(quality, 1),
            trade_permission=trade_permission,
            regime_confidence=round(confidence, 1),
            suppress_reasons=suppress,
            htf_1h=htf_1h,
            htf_15m=htf_15m,
            htf_5m=htf_5m,
            atr_ratio=atr_ratio,
            adx_proxy=round(adx_proxy, 1) if adx_proxy is not None else None,
            overlap_pct=round(overlap_pct, 1) if overlap_pct is not None else None,
            trend_persistence=round(trend_persistence, 1)
            if trend_persistence is not None
            else None,
            volatility_state=vol_state,
            liquidity_state=liq_state,
        )

    @staticmethod
    def _resample(candles: list[dict], factor: int) -> list[dict]:
        if factor <= 1:
            return candles
        out: list[dict] = []
        for i in range(0, len(candles) - factor + 1, factor):
            chunk = candles[i : i + factor]
            out.append(
                {
                    "open": float(chunk[0]["open"]),
                    "high": max(float(c["high"]) for c in chunk),
                    "low": min(float(c["low"]) for c in chunk),
                    "close": float(chunk[-1]["close"]),
                    "volume": sum(float(c.get("volume") or 0) for c in chunk),
                }
            )
        return out

    @staticmethod
    def _direction_from_closes(
        closes: list[float], fast: int, slow: int
    ) -> str:
        ema_fast = IndicatorEngine.ema(closes, fast)
        ema_slow = IndicatorEngine.ema(closes, slow)
        if not ema_fast or not ema_slow:
            return "NEUTRAL"
        f, s = ema_fast[-1], ema_slow[-1]
        if f is None or s is None or s == 0:
            return "NEUTRAL"
        spread = (f - s) / s * 100
        if spread > 0.04:
            return "BULLISH"
        if spread < -0.04:
            return "BEARISH"
        return "NEUTRAL"

    @staticmethod
    def _candle_overlap_pct(
        highs: list[float], lows: list[float], closes: list[float], lookback: int = 12
    ) -> float:
        if len(closes) < lookback + 1:
            return 0.0
        overlaps = 0
        for i in range(-lookback, 0):
            prev_hi, prev_lo = highs[i - 1], lows[i - 1]
            cur_hi, cur_lo = highs[i], lows[i]
            overlap = max(0.0, min(cur_hi, prev_hi) - max(cur_lo, prev_lo))
            span = max(cur_hi - cur_lo, prev_hi - prev_lo, 1e-9)
            if overlap / span > 0.45:
                overlaps += 1
        return overlaps / lookback * 100

    @staticmethod
    def _adx_proxy(highs: list[float], lows: list[float], closes: list[float]) -> float:
        atr = IndicatorEngine.atr(highs, lows, closes, 14)
        if not atr or atr[-1] is None or closes[-1] == 0:
            return 0.0
        return min(100.0, (atr[-1] / closes[-1]) * 100 * 8)

    @staticmethod
    def _trend_persistence(closes: list[float], lookback: int = 15) -> float:
        if len(closes) < lookback + 1:
            return 0.0
        same_dir = 0
        for i in range(-lookback, 0):
            if closes[i] > closes[i - 1]:
                same_dir += 1
        return same_dir / lookback * 100

    @staticmethod
    def _volume_ratio(volumes: list[float]) -> Optional[float]:
        if len(volumes) < 22:
            return None
        recent = volumes[-1]
        avg = sum(volumes[-21:-1]) / 20
        if avg <= 0:
            return None
        return recent / avg

    @staticmethod
    def _momentum_exhaustion(
        closes: list[float], highs: list[float], lows: list[float]
    ) -> bool:
        if len(closes) < 8:
            return False
        ema = IndicatorEngine.ema(closes, 8)
        if not ema or ema[-1] is None:
            return False
        stretch = abs(closes[-1] - ema[-1]) / ema[-1] * 100
        range_pct = (highs[-1] - lows[-1]) / closes[-1] * 100 if closes[-1] else 0
        return stretch > 0.35 and range_pct < 0.08

    @staticmethod
    def _htf_aligned(htf_1h: str, htf_15m: str, htf_5m: str) -> bool:
        dirs = [d for d in (htf_1h, htf_15m, htf_5m) if d != "NEUTRAL"]
        if len(dirs) < 2:
            return True
        return len(set(dirs)) == 1

    def _classify_regime(
        self,
        *,
        htf_1h: str,
        htf_15m: str,
        htf_5m: str,
        overlap_pct: float,
        adx_proxy: float,
        atr_ratio: Optional[float],
        trend_persistence: float,
        vol_state: str,
    ) -> tuple[str, str, float]:
        legacy = htf_15m if htf_15m != "NEUTRAL" else htf_5m

        if vol_state == "COMPRESSION":
            regime = "VOLATILITY_COMPRESSION"
            conf = 55.0
        elif vol_state == "EXPANSION" and adx_proxy >= self.TREND_ADX_MIN:
            regime = "BREAKOUT_EXPANSION"
            conf = min(90.0, adx_proxy + trend_persistence * 0.3)
        elif adx_proxy >= self.TREND_ADX_MIN and overlap_pct < 50:
            regime = "TRENDING"
            conf = min(95.0, adx_proxy + trend_persistence * 0.25)
        elif overlap_pct >= self.CHOP_OVERLAP_THRESHOLD:
            regime = "SIDEWAYS_CHOP"
            conf = max(30.0, 70.0 - overlap_pct * 0.4)
            legacy = "NEUTRAL"
        else:
            regime = "TRANSITIONAL"
            conf = 50.0

        if legacy == "NEUTRAL" and htf_1h != "NEUTRAL":
            legacy = htf_1h

        if atr_ratio and atr_ratio >= 1.35 and adx_proxy >= 24:
            regime = "HIGH_VOL_TREND"

        return regime, legacy, conf

    @staticmethod
    def _market_quality_score(
        *,
        regime: str,
        confidence: float,
        overlap_pct: float,
        adx_proxy: float,
        htf_aligned: bool,
        liq_state: str,
        suppress_count: int,
    ) -> float:
        score = confidence * 0.55
        if regime == "TRENDING":
            score += 18
        elif regime == "BREAKOUT_EXPANSION":
            score += 14
        elif regime in ("SIDEWAYS_CHOP", "VOLATILITY_COMPRESSION"):
            score -= 22
        score -= max(0.0, overlap_pct - 45) * 0.25
        score += min(12.0, adx_proxy * 0.35)
        if htf_aligned:
            score += 8
        if liq_state == "LOW":
            score -= 15
        score -= suppress_count * 6
        return max(0.0, min(100.0, score))
