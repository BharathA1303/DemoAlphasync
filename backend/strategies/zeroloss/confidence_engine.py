"""
AlphaSync ZeroLoss — Confidence Engine v2.

Enhanced multi-dimensional scorer with VWAP, ADX-style trend strength,
and momentum quality checks. Produces a composite score from 0 to 100.

Scoring breakdown (total = 100):
    EMA Stack Alignment   :  20 pts  (trend direction)
    RSI Sweet-Zone        :  15 pts  (not overbought/oversold)
    MACD Momentum         :  15 pts  (momentum confirms direction)
    Volume Confirmation   :  15 pts  (smart money participation)
    Volatility Regime     :  10 pts  (market calm enough to trade)
    Support/Resistance    :  10 pts  (price positioning)
    VWAP Alignment        :  10 pts  (institutional price reference)
    Trend Strength (ADX)  :   5 pts  (avoid ranging markets)

Key principle: NO FREE POINTS. Each dimension must genuinely confirm
the trade direction to earn points. Opposing signals score 0.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from engines.indicators import IndicatorEngine

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceBreakdown:
    """Detailed breakdown returned by the Confidence Engine."""

    ema_score: float = 0.0         # 0 – 20
    rsi_score: float = 0.0         # 0 – 15
    macd_score: float = 0.0        # 0 – 15
    volume_score: float = 0.0      # 0 – 15
    volatility_score: float = 0.0  # 0 – 10
    sr_score: float = 0.0          # 0 – 10
    vwap_score: float = 0.0        # 0 – 10
    trend_strength_score: float = 0.0  # 0 – 5
    total: float = 0.0             # 0 – 100
    direction: str = "NEUTRAL"     # BULLISH / BEARISH / NEUTRAL
    reasons: list[str] = field(default_factory=list)

    # Raw indicator values for downstream consumers
    ema_20: Optional[float] = None
    ema_50: Optional[float] = None
    ema_200: Optional[float] = None
    rsi: Optional[float] = None
    macd_hist: Optional[float] = None
    volume_ratio: Optional[float] = None
    vix: Optional[float] = None
    vwap: Optional[float] = None
    adx: Optional[float] = None

    # Momentum quality flags (used by signal generator)
    macd_growing: bool = False
    volume_strong: bool = False
    above_vwap: Optional[bool] = None


class ConfidenceEngine:
    """
    Multi-dimensional market confidence scorer v2.

    Improvements over v1:
    - VWAP alignment (institutional price reference)
    - ADX-style trend strength (avoid choppy markets)
    - MACD histogram acceleration check (3-bar momentum)
    - Stricter volume requirements
    - RSI momentum divergence detection
    """

    MIN_CANDLES = 30

    # RSI sweet-zones — widened to capture more momentum setups
    RSI_BULL_LOW = 38.0     # was 40 — catch earlier momentum
    RSI_BULL_HIGH = 72.0    # was 65 — allow stronger uptrends
    RSI_BEAR_LOW = 28.0     # was 35 — allow stronger downtrends
    RSI_BEAR_HIGH = 62.0    # was 60 — catch earlier short setups

    # VIX regime bands
    VIX_LOW = 14.0
    VIX_MED = 20.0
    VIX_HIGH = 25.0    # Lowered from 28 — more conservative

    # Volume thresholds
    VOL_STRONG_RATIO = 1.3
    VOL_ADEQUATE_RATIO = 1.0
    VOL_MIN_RATIO = 0.8

    def score(
        self,
        closes: list[float],
        highs: list[float],
        lows: list[float],
        volumes: list[int],
        vix: Optional[float] = None,
    ) -> ConfidenceBreakdown:
        result = ConfidenceBreakdown()

        if len(closes) < self.MIN_CANDLES:
            result.reasons.append(
                f"Insufficient data: need {self.MIN_CANDLES} candles, got {len(closes)}"
            )
            return result

        # 1. EMA Stack (20 pts) — also determines direction
        result.ema_score, result.direction = self._score_ema_stack(closes, result)

        # 2. RSI Sweet-Zone (15 pts)
        result.rsi_score = self._score_rsi(closes, result)

        # 3. MACD Momentum (15 pts)
        result.macd_score = self._score_macd(closes, result)

        # 4. Volume Confirmation (15 pts)
        result.volume_score = self._score_volume(volumes, result)

        # 5. Volatility / VIX (10 pts)
        result.volatility_score = self._score_volatility(vix, result)

        # 6. Support/Resistance (10 pts)
        result.sr_score = self._score_support_resistance(closes, highs, lows, result)

        # 7. VWAP Alignment (10 pts)
        result.vwap_score = self._score_vwap(closes, highs, lows, volumes, result)

        # 8. Trend Strength / ADX-style (5 pts)
        result.trend_strength_score = self._score_trend_strength(closes, highs, lows, result)

        # Total
        result.total = round(
            result.ema_score + result.rsi_score + result.macd_score
            + result.volume_score + result.volatility_score + result.sr_score
            + result.vwap_score + result.trend_strength_score,
            2,
        )

        logger.debug(
            f"Confidence: {result.total}/100 | Dir: {result.direction} | "
            f"EMA={result.ema_score} RSI={result.rsi_score} "
            f"MACD={result.macd_score} VOL={result.volume_score} "
            f"VIX={result.volatility_score} SR={result.sr_score} "
            f"VWAP={result.vwap_score} ADX={result.trend_strength_score}"
        )

        return result

    # ── Component Scorers ──────────────────────────────────────────────────────

    def _score_ema_stack(
        self, closes: list[float], result: ConfidenceBreakdown
    ) -> tuple[float, str]:
        """
        EMA Stack Alignment — up to 20 points.
        Full stack alignment = 20. Partial = 10. Mixed = 0.
        """
        if len(closes) >= 210:
            ema_short = IndicatorEngine.ema(closes, 20)
            ema_mid = IndicatorEngine.ema(closes, 50)
            ema_long = IndicatorEngine.ema(closes, 200)
        else:
            ema_short = IndicatorEngine.ema(closes, 9)
            ema_mid = IndicatorEngine.ema(closes, 21)
            ema_long = IndicatorEngine.ema(closes, 50) if len(closes) >= 55 else None

        e20 = ema_short[-1]
        e50 = ema_mid[-1]
        e200 = ema_long[-1] if ema_long is not None else None

        result.ema_20 = e20
        result.ema_50 = e50
        result.ema_200 = e200

        if e20 is None or e50 is None:
            result.reasons.append("EMA data incomplete")
            return 0.0, "NEUTRAL"

        if e200 is not None:
            if e20 > e50 > e200:
                result.reasons.append("EMA stack fully bullish (20 > 50 > 200)")
                return 20.0, "BULLISH"
            if e20 < e50 < e200:
                result.reasons.append("EMA stack fully bearish (20 < 50 < 200)")
                return 20.0, "BEARISH"

            if e20 > e50 and e20 > e200:
                result.reasons.append("Partial bullish: short EMA leading above long-term")
                return 10.0, "BULLISH"
            if e20 < e50 and e20 < e200:
                result.reasons.append("Partial bearish: short EMA leading below long-term")
                return 10.0, "BEARISH"

            result.reasons.append("EMA stack mixed — no clear direction")
            return 0.0, "NEUTRAL"

        # Only short + mid EMAs available
        spread_pct = abs(e20 - e50) / e50 * 100 if e50 != 0 else 0

        if spread_pct < 0.08:  # Raised from 0.05 — need clearer separation
            result.reasons.append(f"EMAs converged (spread {spread_pct:.2f}%) — no direction")
            return 0.0, "NEUTRAL"

        if e20 > e50:
            result.reasons.append(f"EMA-9 > EMA-21 (spread {spread_pct:.2f}%) — bullish")
            return 15.0, "BULLISH"
        if e20 < e50:
            result.reasons.append(f"EMA-9 < EMA-21 (spread {spread_pct:.2f}%) — bearish")
            return 15.0, "BEARISH"

        return 0.0, "NEUTRAL"

    def _score_rsi(self, closes: list[float], result: ConfidenceBreakdown) -> float:
        """RSI Sweet-Zone — up to 15 points."""
        rsi_vals = IndicatorEngine.rsi(closes, 14)
        rsi = rsi_vals[-1]
        result.rsi = rsi

        if rsi is None:
            result.reasons.append("RSI data incomplete")
            return 0.0

        direction = result.direction

        if direction == "BULLISH":
            if self.RSI_BULL_LOW <= rsi <= self.RSI_BULL_HIGH:
                result.reasons.append(f"RSI {rsi:.1f} in bullish sweet zone")
                return 15.0
            if (self.RSI_BULL_LOW - 5) <= rsi < self.RSI_BULL_LOW:
                result.reasons.append(f"RSI {rsi:.1f} near bullish zone edge")
                return 8.0
            result.reasons.append(f"RSI {rsi:.1f} outside bullish zone")
            return 0.0

        elif direction == "BEARISH":
            if self.RSI_BEAR_LOW <= rsi <= self.RSI_BEAR_HIGH:
                result.reasons.append(f"RSI {rsi:.1f} in bearish sweet zone")
                return 15.0
            if self.RSI_BEAR_HIGH < rsi <= (self.RSI_BEAR_HIGH + 5):
                result.reasons.append(f"RSI {rsi:.1f} near bearish zone edge")
                return 8.0
            result.reasons.append(f"RSI {rsi:.1f} outside bearish zone")
            return 0.0

        result.reasons.append(f"RSI {rsi:.1f} — neutral direction, no score")
        return 0.0

    def _score_macd(self, closes: list[float], result: ConfidenceBreakdown) -> float:
        """
        MACD Momentum — up to 15 points.
        Now checks 3-bar histogram acceleration for stronger confirmation.
        """
        macd_result = IndicatorEngine.macd(closes)
        if macd_result is None:
            result.reasons.append("MACD data incomplete")
            return 0.0

        hist = macd_result.histogram
        valid_hist = [h for h in hist if h is not None]
        if len(valid_hist) < 3:
            result.reasons.append("MACD histogram insufficient")
            return 0.0

        curr_hist = valid_hist[-1]
        prev_hist = valid_hist[-2]
        prev2_hist = valid_hist[-3]
        result.macd_hist = curr_hist

        # Check if momentum is growing (accelerating)
        growing = abs(curr_hist) > abs(prev_hist)
        # 3-bar acceleration: getting stronger over 3 bars
        accelerating = growing and abs(prev_hist) > abs(prev2_hist)
        result.macd_growing = growing

        direction = result.direction

        if direction == "BULLISH" and curr_hist > 0:
            if accelerating:
                result.reasons.append(f"MACD positive & accelerating ({curr_hist:.4f})")
                return 15.0
            if growing:
                result.reasons.append(f"MACD positive & growing ({curr_hist:.4f})")
                return 12.0
            # Fading momentum — reduced score
            result.reasons.append(f"MACD positive but fading ({curr_hist:.4f})")
            return 5.0

        if direction == "BEARISH" and curr_hist < 0:
            if accelerating:
                result.reasons.append(f"MACD negative & accelerating ({curr_hist:.4f})")
                return 15.0
            if growing:
                result.reasons.append(f"MACD negative & growing ({curr_hist:.4f})")
                return 12.0
            result.reasons.append(f"MACD negative but fading ({curr_hist:.4f})")
            return 5.0

        result.reasons.append(f"MACD ({curr_hist:.4f}) opposes {direction} — 0 points")
        return 0.0

    def _score_volume(self, volumes: list[int], result: ConfidenceBreakdown) -> float:
        """Volume Confirmation — up to 15 points."""
        if len(volumes) < 20:
            result.reasons.append("Volume data insufficient (<20 bars)")
            return 0.0

        avg_vol = sum(volumes[-20:]) / 20
        current_vol = volumes[-1]

        if avg_vol == 0:
            result.reasons.append("Average volume is zero")
            return 0.0

        ratio = current_vol / avg_vol
        result.volume_ratio = round(ratio, 2)

        if ratio >= self.VOL_STRONG_RATIO:
            result.reasons.append(f"Volume strong: {ratio:.2f}x avg — high conviction")
            result.volume_strong = True
            return 15.0

        if ratio >= self.VOL_ADEQUATE_RATIO:
            result.reasons.append(f"Volume adequate: {ratio:.2f}x avg")
            return 10.0

        if ratio >= self.VOL_MIN_RATIO:
            result.reasons.append(f"Volume moderate: {ratio:.2f}x avg — marginal")
            return 5.0

        result.reasons.append(f"Volume thin: {ratio:.2f}x avg — insufficient")
        return 0.0

    def _score_volatility(self, vix: Optional[float], result: ConfidenceBreakdown) -> float:
        """Volatility Regime (India VIX) — up to 10 points."""
        if vix is None:
            vix = 15.0
            result.reasons.append("VIX unavailable — assumed moderate (15)")

        result.vix = vix

        if vix < self.VIX_LOW:
            result.reasons.append(f"VIX {vix:.1f} — calm market")
            return 10.0
        if vix < self.VIX_MED:
            result.reasons.append(f"VIX {vix:.1f} — moderate volatility")
            return 8.0
        if vix < self.VIX_HIGH:
            result.reasons.append(f"VIX {vix:.1f} — elevated volatility")
            return 4.0

        result.reasons.append(f"VIX {vix:.1f} — extreme volatility, unsafe")
        return 0.0

    def _score_support_resistance(
        self, closes: list[float], highs: list[float], lows: list[float],
        result: ConfidenceBreakdown,
    ) -> float:
        """Support / Resistance Proximity — up to 10 points."""
        lookback = 20
        if len(closes) < lookback:
            result.reasons.append("Insufficient data for S/R analysis")
            return 0.0

        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]
        resistance = max(recent_highs)
        support = min(recent_lows)
        price = closes[-1]

        if resistance == support:
            result.reasons.append("Flat range — S/R not meaningful")
            return 5.0

        position = (price - support) / (resistance - support)
        direction = result.direction

        if direction == "BULLISH":
            if position <= 0.30:
                result.reasons.append(f"Price near support ({position:.0%}) — ideal long zone")
                return 10.0
            if position <= 0.55:
                result.reasons.append(f"Price in lower-mid range ({position:.0%}) — acceptable")
                return 5.0
            result.reasons.append(f"Price near resistance ({position:.0%}) — risky for longs")
            return 0.0

        if direction == "BEARISH":
            if position >= 0.70:
                result.reasons.append(f"Price near resistance ({position:.0%}) — ideal short zone")
                return 10.0
            if position >= 0.45:
                result.reasons.append(f"Price in upper-mid range ({position:.0%}) — acceptable")
                return 5.0
            result.reasons.append(f"Price near support ({position:.0%}) — risky for shorts")
            return 0.0

        result.reasons.append(f"Neutral direction — S/R position {position:.0%}")
        return 5.0

    def _score_vwap(
        self, closes: list[float], highs: list[float], lows: list[float],
        volumes: list[int], result: ConfidenceBreakdown,
    ) -> float:
        """
        VWAP Alignment — up to 10 points.

        Uses only the current trading session's candles (last 78 bars = 6.5hr at 5m)
        for accurate intraday VWAP. Multi-day VWAP is meaningless for day-trading.
        """
        try:
            # Use only today's session candles (~78 bars = 6.5hr * 12 bars/hr at 5m)
            # This ensures VWAP resets each day as it should
            session_bars = min(78, len(closes))
            session_closes = closes[-session_bars:]
            session_highs = highs[-session_bars:]
            session_lows = lows[-session_bars:]
            session_volumes = volumes[-session_bars:]

            vwap_values = IndicatorEngine.vwap(
                session_highs, session_lows, session_closes, session_volumes
            )
            if not vwap_values:
                result.reasons.append("VWAP calculation failed")
                return 0.0

            vwap_val = vwap_values[-1]
            if vwap_val is None or vwap_val == 0:
                result.reasons.append("VWAP data invalid")
                return 0.0

            price = closes[-1]
            result.vwap = vwap_val
            vwap_distance_pct = (price - vwap_val) / vwap_val * 100

            direction = result.direction
            result.above_vwap = price > vwap_val

            if direction == "BULLISH":
                if price >= vwap_val:
                    if vwap_distance_pct <= 0.5:
                        result.reasons.append(f"Price just above VWAP (+{vwap_distance_pct:.2f}%) — strong long setup")
                        return 10.0
                    result.reasons.append(f"Price above VWAP (+{vwap_distance_pct:.2f}%) — bullish confirmed")
                    return 7.0
                # Slightly below VWAP — partial credit (may be testing support)
                if vwap_distance_pct >= -0.3:
                    result.reasons.append(f"Price near VWAP ({vwap_distance_pct:.2f}%) — acceptable for long")
                    return 5.0
                result.reasons.append(f"Price below VWAP ({vwap_distance_pct:.2f}%) — risky long")
                return 0.0

            if direction == "BEARISH":
                if price <= vwap_val:
                    if vwap_distance_pct >= -0.5:
                        result.reasons.append(f"Price just below VWAP ({vwap_distance_pct:.2f}%) — strong short setup")
                        return 10.0
                    result.reasons.append(f"Price below VWAP ({vwap_distance_pct:.2f}%) — bearish confirmed")
                    return 7.0
                if vwap_distance_pct <= 0.3:
                    result.reasons.append(f"Price near VWAP (+{vwap_distance_pct:.2f}%) — acceptable for short")
                    return 5.0
                result.reasons.append(f"Price above VWAP (+{vwap_distance_pct:.2f}%) — risky short")
                return 0.0

            result.reasons.append(f"VWAP neutral — distance {vwap_distance_pct:.2f}%")
            return 0.0
        except Exception as e:
            result.reasons.append(f"VWAP error: {e}")
            return 0.0

    def _score_trend_strength(
        self, closes: list[float], highs: list[float], lows: list[float],
        result: ConfidenceBreakdown,
    ) -> float:
        """
        ADX-style Trend Strength — up to 5 points.

        Uses ATR-normalized price movement to gauge if market is trending
        or chopping sideways. Avoid entries in ranging (choppy) markets.
        """
        try:
            atr_values = IndicatorEngine.atr(highs, lows, closes, period=14)
            if not atr_values:
                result.reasons.append("ATR calculation failed")
                return 0.0

            valid_atr = [a for a in atr_values if a is not None]
            if len(valid_atr) < 5:
                result.reasons.append("ATR data insufficient")
                return 0.0

            current_atr = valid_atr[-1]
            avg_atr = sum(valid_atr[-14:]) / len(valid_atr[-14:])

            if avg_atr == 0:
                result.reasons.append("ATR is zero — flat market")
                return 0.0

            # Directional movement: how much has price moved in trend direction
            # over last 5 bars vs ATR (noise level)
            price_move = abs(closes[-1] - closes[-6]) if len(closes) >= 6 else 0
            atr_ratio = price_move / (current_atr * 5) if current_atr > 0 else 0

            result.adx = round(atr_ratio * 100, 1)  # Pseudo-ADX

            if atr_ratio > 0.4:
                result.reasons.append(f"Strong trend (directional ratio: {atr_ratio:.2f})")
                return 5.0
            if atr_ratio > 0.2:
                result.reasons.append(f"Moderate trend (directional ratio: {atr_ratio:.2f})")
                return 3.0
            result.reasons.append(f"Weak/choppy market (directional ratio: {atr_ratio:.2f}) — avoid")
            return 0.0
        except Exception as e:
            result.reasons.append(f"Trend strength error: {e}")
            return 0.0
