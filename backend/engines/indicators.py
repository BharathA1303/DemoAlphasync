"""
AlphaSync Indicator Engine — Technical indicator computation.

Pure math functions with no I/O or DB dependencies. Takes lists of prices
(floats) and returns computed indicator values. Used by the Algo Strategy
Worker's signal generation pipeline.

All functions operate on plain Python lists for portability.
NumPy/pandas can be introduced later for performance if needed.

Usage:
    from engines.indicators import IndicatorEngine

    closes = [100.0, 101.5, 102.3, ...]
    sma_20 = IndicatorEngine.sma(closes, 20)
    rsi_14 = IndicatorEngine.rsi(closes, 14)
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class MACDResult:
    """Result of MACD computation."""
    macd_line: list[float]
    signal_line: list[float]
    histogram: list[float]


@dataclass
class BollingerResult:
    """Result of Bollinger Bands computation."""
    upper: list[float]
    middle: list[float]
    lower: list[float]


class IndicatorEngine:
    """
    Stateless technical indicator calculator.

    All methods are static — this class is a namespace, not an instance.
    Each method returns a list the same length as the input, padded with
    None for the lookback period where the indicator cannot be computed.
    """

    @staticmethod
    def sma(prices: list[float], period: int) -> list[Optional[float]]:
        """
        Simple Moving Average.

        Returns a list of length len(prices). The first (period-1) values
        are None (insufficient data), followed by the SMA values.
        """
        if len(prices) < period:
            return [None] * len(prices)

        result: list[Optional[float]] = [None] * (period - 1)
        window_sum = sum(prices[:period])
        result.append(round(window_sum / period, 4))

        for i in range(period, len(prices)):
            window_sum += prices[i] - prices[i - period]
            result.append(round(window_sum / period, 4))

        return result

    @staticmethod
    def ema(prices: list[float], period: int) -> list[Optional[float]]:
        """
        Exponential Moving Average.

        Uses SMA of the first `period` values as the seed, then applies
        the EMA formula: EMA_t = price * k + EMA_(t-1) * (1 - k)
        where k = 2 / (period + 1).
        """
        if len(prices) < period:
            return [None] * len(prices)

        k = 2.0 / (period + 1)
        result: list[Optional[float]] = [None] * (period - 1)

        # Seed with SMA
        sma_seed = sum(prices[:period]) / period
        result.append(round(sma_seed, 4))

        for i in range(period, len(prices)):
            ema_val = prices[i] * k + result[-1] * (1 - k)
            result.append(round(ema_val, 4))

        return result

    @staticmethod
    def rsi(prices: list[float], period: int = 14) -> list[Optional[float]]:
        """
        Relative Strength Index (Wilder's method).

        RSI = 100 - (100 / (1 + RS))
        RS = avg_gain / avg_loss over the period.

        Returns values between 0 and 100.
        """
        if len(prices) < period + 1:
            return [None] * len(prices)

        # Calculate price changes
        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

        gains = [max(c, 0) for c in changes]
        losses = [abs(min(c, 0)) for c in changes]

        # Initial averages (SMA of first `period` changes)
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        result: list[Optional[float]] = [None] * period

        def _to_rsi(gain: float, loss: float) -> float:
            if loss == 0 and gain == 0:
                return 50.0
            if loss == 0:
                return 100.0
            if gain == 0:
                return 0.0
            rs = gain / loss
            return round(100 - (100 / (1 + rs)), 2)

        # First RSI value
        result.append(_to_rsi(avg_gain, avg_loss))

        # Subsequent values using Wilder's smoothing
        for i in range(period, len(changes)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

            result.append(_to_rsi(avg_gain, avg_loss))

        return result

    @staticmethod
    def macd(
        prices: list[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> Optional[MACDResult]:
        """
        Moving Average Convergence Divergence.

        Returns:
            MACDResult with macd_line, signal_line, histogram.
            None if insufficient data.
        """
        if len(prices) < slow_period + signal_period:
            return None

        fast_ema = IndicatorEngine.ema(prices, fast_period)
        slow_ema = IndicatorEngine.ema(prices, slow_period)

        # MACD line = fast EMA - slow EMA
        macd_line: list[Optional[float]] = []
        for f, s in zip(fast_ema, slow_ema):
            if f is not None and s is not None:
                macd_line.append(round(f - s, 4))
            else:
                macd_line.append(None)

        # Signal line = EMA of MACD line
        valid_macd = [v for v in macd_line if v is not None]
        signal_ema = IndicatorEngine.ema(valid_macd, signal_period)

        # Pad signal line to align with macd_line
        none_count = len(macd_line) - len(valid_macd)
        signal_line: list[Optional[float]] = [None] * none_count + signal_ema

        # Histogram = MACD - Signal
        histogram: list[Optional[float]] = []
        for m, s in zip(macd_line, signal_line):
            if m is not None and s is not None:
                histogram.append(round(m - s, 4))
            else:
                histogram.append(None)

        return MACDResult(
            macd_line=macd_line,
            signal_line=signal_line,
            histogram=histogram,
        )

    @staticmethod
    def bollinger_bands(
        prices: list[float],
        period: int = 20,
        std_dev_multiplier: float = 2.0,
    ) -> Optional[BollingerResult]:
        """
        Bollinger Bands.

        Upper  = SMA + (std_dev * multiplier)
        Middle = SMA
        Lower  = SMA - (std_dev * multiplier)
        """
        if len(prices) < period:
            return None

        middle = IndicatorEngine.sma(prices, period)

        upper: list[Optional[float]] = [None] * (period - 1)
        lower: list[Optional[float]] = [None] * (period - 1)

        for i in range(period - 1, len(prices)):
            window = prices[i - period + 1 : i + 1]
            mean = middle[i]
            if mean is None:
                upper.append(None)
                lower.append(None)
                continue

            variance = sum((p - mean) ** 2 for p in window) / period
            std = variance ** 0.5

            upper.append(round(mean + std * std_dev_multiplier, 4))
            lower.append(round(mean - std * std_dev_multiplier, 4))

        return BollingerResult(upper=upper, middle=middle, lower=lower)

    @staticmethod
    def vwap(
        highs: list[float],
        lows: list[float],
        closes: list[float],
        volumes: list[int],
    ) -> list[Optional[float]]:
        """
        Volume Weighted Average Price (intraday).

        VWAP = cumulative(typical_price * volume) / cumulative(volume)
        typical_price = (high + low + close) / 3
        """
        if not highs or not (len(highs) == len(lows) == len(closes) == len(volumes)):
            return []

        result: list[Optional[float]] = []
        cum_tp_vol = 0.0
        cum_vol = 0

        for h, l, c, v in zip(highs, lows, closes, volumes):
            typical_price = (h + l + c) / 3.0
            cum_tp_vol += typical_price * v
            cum_vol += v

            if cum_vol == 0:
                result.append(None)
            else:
                result.append(round(cum_tp_vol / cum_vol, 4))

        return result

    @staticmethod
    def atr(
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 14,
    ) -> list[Optional[float]]:
        """
        Average True Range — measures volatility.

        TR = max(high - low, |high - prev_close|, |low - prev_close|)
        ATR = SMA of TR over period.
        """
        if len(highs) < period + 1:
            return [None] * len(highs)

        true_ranges: list[float] = [highs[0] - lows[0]]

        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            true_ranges.append(round(tr, 4))

        return IndicatorEngine.sma(true_ranges, period)
