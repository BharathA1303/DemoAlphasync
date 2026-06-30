/**
 * ZebuLiveChart — TradingView Lightweight Charts candlestick chart.
 *
 * Uses lightweight-charts v4 for professional charting.
 * All OHLCV data comes from Zebu REST API (/TPSeries, /EODChartData).
 * Live candle updates come from Zebu WebSocket ticks via the market store.
 *
 * Features:
 *  - Candlestick + volume chart via TradingView lightweight-charts
 *  - Real-time current candle updates from live tick data
 *  - Indicator overlays (EMA, SMA, BB, VWAP, SuperTrend, Ichimoku)
 *  - Toolbar with timeframe, indicators, drawing tools
 *  - Responsive resize via ResizeObserver
 *  - Fullscreen toggle
 *  - ZEBU LIVE badge
 */

import { useEffect, useRef, useState, useCallback, memo, useMemo, useSyncExternalStore } from 'react';
import { createChart, CrosshairMode } from 'lightweight-charts';

// Keep timestamps in canonical Unix seconds; avoid manual timezone shifts
// so REST history and live ticks stay aligned.
const MARKET_TIMEZONE = 'Asia/Kolkata';
const IST_OFFSET_SECONDS = 5.5 * 3600;
const MARKET_OPEN_MINUTES_IST = (9 * 60) + 15;

const marketTimeTickFormatter = new Intl.DateTimeFormat('en-IN', {
    timeZone: MARKET_TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
});

const marketDateTickFormatter = new Intl.DateTimeFormat('en-IN', {
    timeZone: MARKET_TIMEZONE,
    day: '2-digit',
    month: 'short',
});

const marketTimeCrosshairFormatter = new Intl.DateTimeFormat('en-IN', {
    timeZone: MARKET_TIMEZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
});

const marketDateCrosshairFormatter = new Intl.DateTimeFormat('en-IN', {
    timeZone: MARKET_TIMEZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
});

const chartTimeToEpochMs = (time) => {
    if (typeof time === 'number' && Number.isFinite(time)) {
        return Math.floor(time * 1000);
    }
    if (typeof time === 'string') {
        const parsed = Date.parse(time);
        return Number.isFinite(parsed) ? parsed : null;
    }
    if (time && typeof time === 'object' && Number.isFinite(time.year) && Number.isFinite(time.month) && Number.isFinite(time.day)) {
        return Date.UTC(time.year, time.month - 1, time.day);
    }
    return null;
};

const istMinuteOfDay = (epochSeconds) => {
    if (!Number.isFinite(epochSeconds)) return null;
    const daySeconds = 24 * 60 * 60;
    const local = Math.floor(epochSeconds + IST_OFFSET_SECONDS);
    const seconds = ((local % daySeconds) + daySeconds) % daySeconds;
    return Math.floor(seconds / 60);
};

const formatMarketTimeTick = (time, isIntraday = true) => {
    const ms = chartTimeToEpochMs(time);
    if (ms == null) return '';
    if (!isIntraday) {
        return marketDateTickFormatter.format(new Date(ms));
    }

    const date = new Date(ms);
    const hhmm = marketTimeTickFormatter.format(date);
    const minuteOfDay = istMinuteOfDay(Math.floor(ms / 1000));

    if (minuteOfDay === MARKET_OPEN_MINUTES_IST) {
        return `${marketDateTickFormatter.format(date)} ${hhmm}`;
    }

    return hhmm;
};

const formatMarketTimeCrosshair = (time, isIntraday = true) => {
    const ms = chartTimeToEpochMs(time);
    if (ms == null) return '';
    return isIntraday
        ? marketTimeCrosshairFormatter.format(new Date(ms))
        : marketDateCrosshairFormatter.format(new Date(ms));
};
import { TrendingUp, TrendingDown, MinusCircle, Eye, EyeOff, X, ChevronDown, ChevronUp } from 'lucide-react';
import { useTheme } from '../../context/ThemeContext';
import { useMarketStore } from '../../store/useMarketStore';
import { getLiveQuoteForSymbol } from '../../utils/liveQuote';
import { marketSessionManager } from '../../market/MarketSessionManager';
import { shouldUseRealtimePrices } from '../../market/utils/marketSessionUtils';
import { cn } from '../../utils/cn';
import { cleanSymbol } from '../../utils/formatters';
import { CHART_PERIODS, DEFAULT_CHART_PERIOD, isMcxSymbol } from '../../utils/constants';
import {
    sma, ema, wma, dema, tema, hma,
    bollingerBands, vwap, supertrend, ichimoku, psar,
    keltnerChannels, donchianChannels, envelope, pivotPoints,
    rsi, macd, atr, adx, cci, stochastic,
    obv, mfi, williamsR, roc, aroon, cmf, stddev,
} from '../../strategy/indicators';

// ── Constants ─────────────────────────────────────────────────────────────────

const TREND_STYLE = {
    BULLISH: { cls: 'signal-pill signal-pill-bullish', icon: '▲', label: 'BULLISH' },
    BEARISH: { cls: 'signal-pill signal-pill-bearish', icon: '▼', label: 'BEARISH' },
    NEUTRAL: { cls: 'signal-pill signal-pill-neutral', icon: '—', label: 'NEUTRAL' },
};

const EMPTY_LIVE_QUOTES = Object.freeze({});

const UP_COLOR = '#26A69A';
const DOWN_COLOR = '#EF5350';
const RSI_LEVELS = [70, 50, 30];
const INTERVAL_SECONDS = {
    '1m': 60,
    '2m': 120,
    '3m': 180,
    '5m': 300,
    '10m': 600,
    '15m': 900,
    '30m': 1800,
    '1h': 3600,
    '2h': 7200,
    '4h': 14400,
    '1d': 86400,
    '1wk': 604800,
    '1mo': 2592000,
};
const CLOSED_MARKET_STATUSES = new Set([
    'pre_market',
    'closing',
    'after_market',
    'closed',
    'holiday',
    'weekend',
    'demo',
]);
const LIVE_QUOTE_MAX_AGE_SECONDS = 180;
const LOADING_CANDLE_TEMPLATE = [
    { wick: 78, body: 26, base: 8, tone: 'up' },
    { wick: 66, body: 32, base: 14, tone: 'down' },
    { wick: 54, body: 24, base: 10, tone: 'up' },
    { wick: 72, body: 28, base: 20, tone: 'down' },
    { wick: 62, body: 36, base: 12, tone: 'up' },
    { wick: 58, body: 22, base: 18, tone: 'down' },
    { wick: 70, body: 30, base: 10, tone: 'up' },
    { wick: 52, body: 24, base: 16, tone: 'down' },
    { wick: 68, body: 34, base: 14, tone: 'up' },
    { wick: 60, body: 28, base: 8, tone: 'down' },
    { wick: 74, body: 26, base: 18, tone: 'up' },
    { wick: 64, body: 22, base: 12, tone: 'down' },
];
const isValidVisibleRange = (range) =>
    !!range &&
    range.from != null &&
    range.to != null;
const toFiniteNumber = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
};

const rebaseCandlesToTargetClose = (rows, targetClose) => {
    const normalizedTarget = toFiniteNumber(targetClose);
    if (!Array.isArray(rows) || rows.length === 0 || normalizedTarget == null || normalizedTarget <= 0) {
        return rows || [];
    }

    const lastClose = toFiniteNumber(rows[rows.length - 1]?.close);
    if (lastClose == null || lastClose <= 0) {
        return rows;
    }

    const scale = normalizedTarget / lastClose;
    if (!Number.isFinite(scale) || scale <= 0 || scale < 0.05 || scale > 20) {
        return rows;
    }

    return rows.map((c) => {
        const open = toFiniteNumber(c?.open);
        const high = toFiniteNumber(c?.high);
        const low = toFiniteNumber(c?.low);
        const close = toFiniteNumber(c?.close);

        if (open == null || high == null || low == null || close == null) {
            return c;
        }

        const scaledOpen = Number((open * scale).toFixed(2));
        const scaledHigh = Number((high * scale).toFixed(2));
        const scaledLow = Number((low * scale).toFixed(2));
        const scaledClose = Number((close * scale).toFixed(2));

        return {
            ...c,
            open: scaledOpen,
            high: Math.max(scaledHigh, scaledOpen, scaledLow, scaledClose),
            low: Math.min(scaledLow, scaledOpen, scaledHigh, scaledClose),
            close: scaledClose,
        };
    });
};

const shouldRebaseFromQuote = (baseClose, livePrice) => {
    const close = toFiniteNumber(baseClose);
    const quote = toFiniteNumber(livePrice);
    if (close == null || close <= 0 || quote == null || quote <= 0) return false;

    const deviation = Math.abs(quote - close) / close;
    return deviation > 0.5;
};

/** Align only the last bar to live LTP (keeps history intact for small gaps). */
const patchLastCandleToLivePrice = (rows, livePrice) => {
    if (!Array.isArray(rows) || rows.length === 0) return rows || [];

    const lp = toFiniteNumber(livePrice);
    if (lp == null || lp <= 0) return rows;

    const lastIdx = rows.length - 1;
    const last = rows[lastIdx];
    const close = toFiniteNumber(last?.close);
    if (close == null || close <= 0) return rows;

    const patchedClose = Number(lp.toFixed(2));
    const patchedHigh = Math.max(
        toFiniteNumber(last.high) ?? patchedClose,
        toFiniteNumber(last.open) ?? patchedClose,
        patchedClose,
    );
    const patchedLow = Math.min(
        toFiniteNumber(last.low) ?? patchedClose,
        toFiniteNumber(last.open) ?? patchedClose,
        patchedClose,
    );

    const next = rows.map((c, i) => (i === lastIdx
        ? {
            ...c,
            close: patchedClose,
            high: Number(patchedHigh.toFixed(2)),
            low: Number(patchedLow.toFixed(2)),
        }
        : c));

    return next;
};

const alignCandlesToLiveQuote = (rows, livePrice) => {
    if (!Array.isArray(rows) || rows.length === 0) return rows || [];

    const lastClose = toFiniteNumber(rows[rows.length - 1]?.close);
    const quote = toFiniteNumber(livePrice);
    if (quote == null || quote <= 0) return rows;

    if (shouldRebaseFromQuote(lastClose, quote)) {
        return rebaseCandlesToTargetClose(rows, quote);
    }
    // For small deviations, return candles as-is. The live price line and
    // real-time tick updates handle showing the current market price without
    // artificially distorting the last historical candle's shape.
    return rows;
};

const normalizeChartCandles = (candles) => {
    const seen = new Map();
    const nowSec = Math.floor(Date.now() / 1000);
    for (const c of candles || []) {
        let time = Number(c?.time);
        if (!Number.isFinite(time) && c?.timestamp != null) {
            time = Number(c.timestamp);
        }

        // Accept mixed epoch units from different providers/cache layers.
        if (Number.isFinite(time)) {
            if (time > 1e18) time = Math.floor(time / 1_000_000_000);
            else if (time > 1e15) time = Math.floor(time / 1_000_000);
            else if (time > 1e12) time = Math.floor(time / 1_000);
            else time = Math.floor(time);
        }

        const open = toFiniteNumber(c?.open);
        const high = toFiniteNumber(c?.high);
        const low = toFiniteNumber(c?.low);
        const close = toFiniteNumber(c?.close);
        const volume = toFiniteNumber(c?.volume) ?? 0;

        if (!Number.isFinite(time) || open == null || high == null || low == null || close == null) {
            continue;
        }
        if (time < 946684800 || time > nowSec + 7 * 24 * 60 * 60) {
            continue;
        }
        // Reject zero or negative prices from malformed payloads.
        if (open <= 0 || high <= 0 || low <= 0 || close <= 0) {
            continue;
        }

        const candleHigh = Math.max(high, open, close, low);
        const candleLow = Math.min(low, open, close, high);

        // Reject extreme wick outliers — wick > 500% of mid-price is corrupt data
        const midPrice = (open + close) / 2;
        if (midPrice > 0 && (candleHigh > midPrice * 6 || candleLow < midPrice / 6)) {
            continue;
        }

        seen.set(time, {
            time,
            open,
            high: candleHigh,
            low: candleLow,
            close,
            volume: Math.max(0, volume),
        });
    }

    return [...seen.values()].sort((a, b) => a.time - b.time);
};

const getIntervalSeconds = (periodKey) => {
    const cfg = CHART_PERIODS[periodKey] || CHART_PERIODS[DEFAULT_CHART_PERIOD];
    return INTERVAL_SECONDS[cfg?.interval] || 60;
};

const startOfIstWeek = (epochSeconds) => {
    if (!Number.isFinite(epochSeconds)) return null;
    const date = new Date(Math.floor((epochSeconds + IST_OFFSET_SECONDS)) * 1000);
    const weekday = (date.getUTCDay() + 6) % 7; // Monday=0 ... Sunday=6 (IST-shifted)
    date.setUTCDate(date.getUTCDate() - weekday);
    date.setUTCHours(0, 0, 0, 0);
    return Math.floor(date.getTime() / 1000) - IST_OFFSET_SECONDS;
};

const startOfIstMonth = (epochSeconds) => {
    if (!Number.isFinite(epochSeconds)) return null;
    const date = new Date(Math.floor((epochSeconds + IST_OFFSET_SECONDS)) * 1000);
    date.setUTCDate(1);
    date.setUTCHours(0, 0, 0, 0);
    return Math.floor(date.getTime() / 1000) - IST_OFFSET_SECONDS;
};

const startOfIstDay = (epochSeconds) => {
    if (!Number.isFinite(epochSeconds)) return null;
    const daySeconds = 24 * 60 * 60;
    const localSeconds = Math.floor(epochSeconds + IST_OFFSET_SECONDS);
    const dayStartLocal = Math.floor(localSeconds / daySeconds) * daySeconds;
    return dayStartLocal - IST_OFFSET_SECONDS;
};

const intradaySessionBucketStart = (epochSeconds, intervalSeconds) => {
    if (!Number.isFinite(epochSeconds) || !Number.isFinite(intervalSeconds) || intervalSeconds <= 0) return null;

    const istDayStart = startOfIstDay(epochSeconds);
    if (!Number.isFinite(istDayStart)) return null;

    const sessionStart = istDayStart + (MARKET_OPEN_MINUTES_IST * 60);
    if (epochSeconds <= sessionStart) return sessionStart;

    const elapsed = epochSeconds - sessionStart;
    return sessionStart + (Math.floor(elapsed / intervalSeconds) * intervalSeconds);
};

const alignBucketTime = (displayTs, _lastCandleTime, intervalSeconds, intervalCode) => {
    if (!Number.isFinite(displayTs)) return null;

    // Calendar buckets for daily/weekly/monthly should align to IST session dates.
    if (intervalCode === '1wk') {
        const bucket = startOfIstWeek(displayTs);
        if (!Number.isFinite(bucket)) return null;
        return bucket;
    }
    if (intervalCode === '1mo') {
        const bucket = startOfIstMonth(displayTs);
        if (!Number.isFinite(bucket)) return null;
        return bucket;
    }
    if (intervalCode === '1d') {
        const bucket = startOfIstDay(displayTs);
        if (!Number.isFinite(bucket)) return null;
        return bucket;
    }

    if (!Number.isFinite(intervalSeconds) || intervalSeconds <= 0) {
        return Math.floor(displayTs);
    }

    if (intervalSeconds > 60) {
        const bucket = intradaySessionBucketStart(displayTs, intervalSeconds);
        if (Number.isFinite(bucket)) return bucket;
    }

    return Math.floor(displayTs / intervalSeconds) * intervalSeconds;
};

const alignCandlesToPeriodBuckets = (rows, intervalCode) => {
    if (!Array.isArray(rows) || rows.length === 0) return rows || [];

    const intervalSeconds = INTERVAL_SECONDS[intervalCode] || 60;
    if (intervalCode === '1m' || intervalSeconds <= 0) return rows;

    const merged = new Map();
    for (const candle of rows) {
        const rawTime = Number(candle?.time);
        if (!Number.isFinite(rawTime)) continue;

        const bucketTime = alignBucketTime(rawTime, rawTime, intervalSeconds, intervalCode);
        if (!Number.isFinite(bucketTime)) continue;

        const open = toFiniteNumber(candle?.open);
        const high = toFiniteNumber(candle?.high);
        const low = toFiniteNumber(candle?.low);
        const close = toFiniteNumber(candle?.close);
        const volume = Math.max(0, toFiniteNumber(candle?.volume) ?? 0);
        if (open == null || high == null || low == null || close == null) continue;

        const existing = merged.get(bucketTime);
        if (!existing) {
            merged.set(bucketTime, {
                time: bucketTime,
                open,
                high,
                low,
                close,
                volume,
                _firstRawTime: rawTime,
                _lastRawTime: rawTime,
            });
            continue;
        }

        if (rawTime < existing._firstRawTime) {
            existing.open = open;
            existing._firstRawTime = rawTime;
        }
        if (rawTime >= existing._lastRawTime) {
            existing.close = close;
            existing._lastRawTime = rawTime;
        }

        existing.high = Math.max(existing.high, high, open, close);
        existing.low = Math.min(existing.low, low, open, close);
        existing.volume += volume;
    }

    return [...merged.values()]
        .sort((a, b) => a.time - b.time)
        .map(({ _firstRawTime, _lastRawTime, ...rest }) => rest);
};

const parseQuoteEpochSeconds = (raw) => {
    if (raw == null || raw === '') return null;

    const n = Number(raw);
    if (Number.isFinite(n) && n > 0) {
        if (n > 1e18) return Math.floor(n / 1_000_000_000);
        if (n > 1e15) return Math.floor(n / 1_000_000);
        if (n > 1e12) return Math.floor(n / 1_000);
        return Math.floor(n);
    }

    if (typeof raw === 'string') {
        const parsed = Date.parse(raw);
        if (Number.isFinite(parsed) && parsed > 0) {
            return Math.floor(parsed / 1000);
        }
    }

    return null;
};

const INDICATOR_DEFS = {
    // ── Moving Averages ──
    ema9: { label: 'EMA 9', group: 'Moving Averages', color: '#38BDF8', width: 1 },
    ema20: { label: 'EMA 20', group: 'Moving Averages', color: '#00bcd4', width: 1.5 },
    ema50: { label: 'EMA 50', group: 'Moving Averages', color: '#8B5CF6', width: 1.5 },
    ema100: { label: 'EMA 100', group: 'Moving Averages', color: '#D946EF', width: 1.5 },
    ema200: { label: 'EMA 200', group: 'Moving Averages', color: '#EC4899', width: 2 },
    sma10: { label: 'SMA 10', group: 'Moving Averages', color: '#67E8F9', width: 1 },
    sma20: { label: 'SMA 20', group: 'Moving Averages', color: '#06B6D4', width: 1.5 },
    sma50: { label: 'SMA 50', group: 'Moving Averages', color: '#14B8A6', width: 1.5 },
    sma100: { label: 'SMA 100', group: 'Moving Averages', color: '#2DD4BF', width: 1.5 },
    sma200: { label: 'SMA 200', group: 'Moving Averages', color: '#F472B6', width: 2 },
    wma20: { label: 'WMA 20', group: 'Moving Averages', color: '#FACC15', width: 1.5 },
    wma50: { label: 'WMA 50', group: 'Moving Averages', color: '#EAB308', width: 1.5 },
    hma20: { label: 'HMA 20', group: 'Moving Averages', color: '#22D3EE', width: 1.5 },
    hma50: { label: 'HMA 50', group: 'Moving Averages', color: '#818CF8', width: 1.5 },
    dema20: { label: 'DEMA 20', group: 'Moving Averages', color: '#FB923C', width: 1.5 },
    tema20: { label: 'TEMA 20', group: 'Moving Averages', color: '#F97316', width: 1.5 },
    vwap: { label: 'VWAP', group: 'Moving Averages', color: '#A855F7', width: 2 },

    // ── Bands & Channels ──
    bb: { label: 'Bollinger Bands', group: 'Bands & Channels', color: '#00bcd4', width: 1 },
    keltner: { label: 'Keltner Channel', group: 'Bands & Channels', color: '#8B5CF6', width: 1 },
    donchian: { label: 'Donchian Channel', group: 'Bands & Channels', color: '#10B981', width: 1 },
    envelope: { label: 'MA Envelope', group: 'Bands & Channels', color: '#F59E0B', width: 1 },

    // ── Trend ──
    supertrend: { label: 'SuperTrend', group: 'Trend', color: '#10B981', width: 2 },
    ichimoku: { label: 'Ichimoku Cloud', group: 'Trend', color: '#F97316', width: 1 },
    psar: { label: 'Parabolic SAR', group: 'Trend', color: '#FBBF24', width: 0 },
    pivots: { label: 'Pivot Points', group: 'Trend', color: '#94A3B8', width: 1 },

    // ── Oscillators ──
    rsi14: { label: 'RSI (14)', group: 'Oscillators', color: '#FBBF24', width: 1.5 },
    macd: { label: 'MACD', group: 'Oscillators', color: '#34D399', width: 1.5 },
    stoch: { label: 'Stochastic', group: 'Oscillators', color: '#4ADE80', width: 1.5 },
    cci20: { label: 'CCI (20)', group: 'Oscillators', color: '#FB923C', width: 1.5 },
    willr: { label: 'Williams %R', group: 'Oscillators', color: '#C084FC', width: 1.5 },
    roc12: { label: 'ROC (12)', group: 'Oscillators', color: '#F472B6', width: 1.5 },
    aroon25: { label: 'Aroon (25)', group: 'Oscillators', color: '#2DD4BF', width: 1.5 },

    // ── Volatility ──
    atr14: { label: 'ATR (14)', group: 'Volatility', color: '#F472B6', width: 1.5 },
    adx14: { label: 'ADX (14)', group: 'Volatility', color: '#A78BFA', width: 1.5 },
    stddev: { label: 'Std Dev (20)', group: 'Volatility', color: '#FB7185', width: 1.5 },

    // ── Volume ──
    obv: { label: 'OBV', group: 'Volume', color: '#22D3EE', width: 1.5 },
    mfi14: { label: 'MFI (14)', group: 'Volume', color: '#34D399', width: 1.5 },
    cmf20: { label: 'Chaikin MF (20)', group: 'Volume', color: '#FBBF24', width: 1.5 },
};

// Indicators that use a separate oscillator price scale (not overlaid on price)
const OSCILLATOR_IDS = new Set([
    'rsi14', 'macd', 'atr14', 'adx14', 'cci20', 'stoch',
    'willr', 'roc12', 'aroon25', 'obv', 'mfi14', 'cmf20', 'stddev',
]);

// ── Indicator computation ─────────────────────────────────────────────────────

function computeIndicatorData(id, candles) {
    const closes = candles.map(c => c.close);
    const toLineData = (vals, clr, w = 1.5, scaleId) => ({
        values: vals.map((v, i) => ({
            time: candles[i].time,
            value: isNaN(v) || !isFinite(v) ? undefined : v,
        })).filter(d => d.value !== undefined),
        color: clr,
        width: w,
        priceScaleId: scaleId,
    });
    const def = INDICATOR_DEFS[id] || {};
    const osc = 'oscillator';

    switch (id) {
        // ── Moving Averages (overlay on price) ──
        case 'ema9': return [toLineData(ema(closes, 9), def.color, def.width)];
        case 'ema20': return [toLineData(ema(closes, 20), def.color, def.width)];
        case 'ema50': return [toLineData(ema(closes, 50), def.color, def.width)];
        case 'ema100': return [toLineData(ema(closes, 100), def.color, def.width)];
        case 'ema200': return [toLineData(ema(closes, 200), def.color, def.width)];
        case 'sma10': return [toLineData(sma(closes, 10), def.color, def.width)];
        case 'sma20': return [toLineData(sma(closes, 20), def.color, def.width)];
        case 'sma50': return [toLineData(sma(closes, 50), def.color, def.width)];
        case 'sma100': return [toLineData(sma(closes, 100), def.color, def.width)];
        case 'sma200': return [toLineData(sma(closes, 200), def.color, def.width)];
        case 'wma20': return [toLineData(wma(closes, 20), def.color, def.width)];
        case 'wma50': return [toLineData(wma(closes, 50), def.color, def.width)];
        case 'hma20': return [toLineData(hma(closes, 20), def.color, def.width)];
        case 'hma50': return [toLineData(hma(closes, 50), def.color, def.width)];
        case 'dema20': return [toLineData(dema(closes, 20), def.color, def.width)];
        case 'tema20': return [toLineData(tema(closes, 20), def.color, def.width)];
        case 'vwap': return [toLineData(vwap(candles), def.color, def.width)];

        // ── Bands & Channels (overlay on price) ──
        case 'bb': {
            const { upper, middle, lower } = bollingerBands(closes, 20, 2);
            return [toLineData(upper, '#0369A1', 1), toLineData(middle, '#00bcd4', 1), toLineData(lower, '#0369A1', 1)];
        }
        case 'keltner': {
            const { upper, middle, lower } = keltnerChannels(candles, 20, 1.5);
            return [toLineData(upper, '#7C3AED', 1), toLineData(middle, '#8B5CF6', 1), toLineData(lower, '#7C3AED', 1)];
        }
        case 'donchian': {
            const { upper, middle, lower } = donchianChannels(candles, 20);
            return [toLineData(upper, '#059669', 1), toLineData(middle, '#10B981', 1), toLineData(lower, '#059669', 1)];
        }
        case 'envelope': {
            const { upper, middle, lower } = envelope(closes, 20, 2.5);
            return [toLineData(upper, '#D97706', 1), toLineData(middle, '#F59E0B', 1), toLineData(lower, '#D97706', 1)];
        }

        // ── Trend (overlay on price) ──
        case 'supertrend': {
            const { supertrend: st, direction: dir } = supertrend(candles, 10, 3);
            return [
                toLineData(st.map((v, i) => dir[i] === 1 ? v : NaN), '#10B981', 2),
                toLineData(st.map((v, i) => dir[i] !== 1 ? v : NaN), '#EF4444', 2),
            ];
        }
        case 'ichimoku': {
            const { tenkan, kijun, senkouA, senkouB } = ichimoku(candles, 9, 26, 52);
            return [toLineData(tenkan, '#2DD4BF', 1), toLineData(kijun, '#F87171', 1), toLineData(senkouA, '#A3E635', 1), toLineData(senkouB, '#FB923C', 1)];
        }
        case 'psar': {
            const { sar, direction } = psar(candles, 0.02, 0.2);
            return [
                toLineData(sar.map((v, i) => direction[i] === 1 ? v : NaN), '#10B981', 1),
                toLineData(sar.map((v, i) => direction[i] !== 1 ? v : NaN), '#EF4444', 1),
            ];
        }
        case 'pivots': {
            const { pp, r1, r2, s1, s2 } = pivotPoints(candles);
            return [
                toLineData(pp, '#94A3B8', 1), toLineData(r1, '#F87171', 1), toLineData(r2, '#EF4444', 1),
                toLineData(s1, '#34D399', 1), toLineData(s2, '#10B981', 1),
            ];
        }

        // ── Oscillators (separate pane) ──
        case 'rsi14':
            return [toLineData(rsi(closes, 14), def.color, 1.5, osc)];
        case 'macd': {
            const { macd: ml, signal: sl } = macd(closes, 12, 26, 9);
            return [toLineData(ml, '#34D399', 1.5, osc), toLineData(sl, '#F87171', 1, osc)];
        }
        case 'stoch': {
            const { k, d } = stochastic(candles, 14, 3, 3);
            return [toLineData(k, '#4ADE80', 1.5, osc), toLineData(d, '#FB923C', 1, osc)];
        }
        case 'cci20':
            return [toLineData(cci(candles, 20), def.color, 1.5, osc)];
        case 'willr':
            return [toLineData(williamsR(candles, 14), def.color, 1.5, osc)];
        case 'roc12':
            return [toLineData(roc(closes, 12), def.color, 1.5, osc)];
        case 'aroon25': {
            const { up, down } = aroon(candles, 25);
            return [toLineData(up, '#2DD4BF', 1.5, osc), toLineData(down, '#F87171', 1, osc)];
        }

        // ── Volatility (separate pane) ──
        case 'atr14':
            return [toLineData(atr(candles, 14), def.color, 1.5, osc)];
        case 'adx14': {
            const { adx: adxVals, plusDI, minusDI } = adx(candles, 14);
            return [toLineData(adxVals, '#A78BFA', 2, osc), toLineData(plusDI, '#34D399', 1, osc), toLineData(minusDI, '#F87171', 1, osc)];
        }
        case 'stddev':
            return [toLineData(stddev(closes, 20), def.color, 1.5, osc)];

        // ── Volume (separate pane) ──
        case 'obv':
            return [toLineData(obv(candles), def.color, 1.5, osc)];
        case 'mfi14':
            return [toLineData(mfi(candles, 14), def.color, 1.5, osc)];
        case 'cmf20':
            return [toLineData(cmf(candles, 20), def.color, 1.5, osc)];

        default: return [];
    }
}

// ── Toolbar sub-components ────────────────────────────────────────────────────

function IndicatorMenu({ active, onToggle, menuRef }) {
    const [search, setSearch] = useState('');
    const GROUP_ORDER = ['Moving Averages', 'Bands & Channels', 'Trend', 'Oscillators', 'Volatility', 'Volume'];
    const groups = {};
    Object.entries(INDICATOR_DEFS).forEach(([id, def]) => {
        if (search && !def.label.toLowerCase().includes(search.toLowerCase())) return;
        (groups[def.group] = groups[def.group] || []).push({ id, ...def });
    });
    const sortedGroups = GROUP_ORDER.filter(g => groups[g]).map(g => [g, groups[g]]);
    return (
        <div ref={menuRef} className="absolute top-full left-0 mt-1 w-64 bg-surface-800 border border-edge/10 rounded-xl shadow-panel z-50 animate-slide-in overflow-hidden"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}>
            <div className="px-3 py-2 border-b border-edge/5">
                <div className="text-[11px] text-gray-500 font-semibold uppercase tracking-wider mb-1.5">Indicators</div>
                <input
                    type="text" placeholder="Search indicators..." value={search} onChange={e => setSearch(e.target.value)}
                    className="w-full bg-surface-700/60 border border-edge/10 rounded-md px-2 py-1 text-xs text-heading placeholder-gray-600 focus:outline-none focus:border-primary-500/30"
                    autoFocus
                />
            </div>
            <div className="max-h-80 overflow-y-auto py-1">
                {sortedGroups.map(([group, items]) => (
                    <div key={group}>
                        <div className="px-3 pt-2.5 pb-1 text-[10px] text-gray-500 uppercase tracking-wider font-semibold flex items-center gap-2">
                            <span>{group}</span>
                            <span className="flex-1 h-px bg-edge/5" />
                            <span className="text-gray-600">{items.length}</span>
                        </div>
                        {items.map(ind => (
                            <button key={ind.id} onClick={() => onToggle(ind.id)}
                                className="w-full flex items-center gap-2.5 px-3 py-1.5 hover:bg-overlay/5 transition-colors text-left">
                                <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0 border"
                                    style={{ backgroundColor: active.has(ind.id) ? ind.color : 'transparent', borderColor: ind.color }} />
                                <span className={cn('text-xs', active.has(ind.id) ? 'text-heading font-medium' : 'text-gray-400')}>{ind.label}</span>
                                {active.has(ind.id) && <span className="ml-auto text-[10px] text-primary-500">✓</span>}
                            </button>
                        ))}
                    </div>
                ))}
                {sortedGroups.length === 0 && (
                    <div className="px-3 py-4 text-xs text-gray-600 text-center">No indicators match "{search}"</div>
                )}
            </div>
            {active.size > 0 && (
                <div className="px-3 py-1.5 border-t border-edge/5 flex items-center justify-between">
                    <span className="text-[11px] text-gray-500">{active.size} active</span>
                    <button onClick={() => active.forEach(id => onToggle(id))} className="text-[11px] text-red-400 hover:text-red-300 transition-colors">Clear all</button>
                </div>
            )}
        </div>
    );
}

function ToolsMenu({ activeTool, onSelect, onClose, menuRef }) {
    const toolGroups = [
        {
            label: 'Cursor',
            items: [
                { id: 'crosshair', label: 'Crosshair', icon: '＋' },
            ],
        },
        {
            label: 'Lines',
            items: [
                { id: 'hline', label: 'Horizontal Line', icon: '─' },
                { id: 'hline_sup', label: 'Support Line', icon: '─', color: '#10B981' },
                { id: 'hline_res', label: 'Resistance Line', icon: '─', color: '#EF4444' },
            ],
        },
        {
            label: 'Levels',
            items: [
                { id: 'hline_target', label: 'Target Price', icon: '◎', color: '#00bcd4' },
                { id: 'hline_sl', label: 'Stop Loss', icon: '⊘', color: '#EF4444' },
                { id: 'hline_entry', label: 'Entry Price', icon: '▸', color: '#FBBF24' },
            ],
        },
    ];
    return (
        <div ref={menuRef} className="absolute top-full left-0 mt-1 w-52 bg-surface-800 border border-edge/10 rounded-xl shadow-panel z-50 animate-slide-in overflow-hidden">
            <div className="px-3 py-2 border-b border-edge/5 text-[11px] text-gray-500 font-semibold uppercase tracking-wider">Drawing Tools</div>
            <div className="py-1">
                {toolGroups.map(group => (
                    <div key={group.label}>
                        <div className="px-3 pt-2 pb-1 text-[10px] text-gray-600 uppercase tracking-wider font-medium">{group.label}</div>
                        {group.items.map(t => (
                            <button key={t.id} onClick={() => { onSelect(activeTool === t.id ? null : t.id); onClose(); }}
                                className={cn('w-full flex items-center gap-2.5 px-3 py-1.5 hover:bg-overlay/5 transition-colors text-left', activeTool === t.id && 'bg-primary-500/10')}>
                                <span className="w-5 text-center text-sm flex-shrink-0" style={{ color: t.color || '#9CA3AF' }}>{t.icon}</span>
                                <span className={cn('text-xs', activeTool === t.id ? 'text-primary-600 font-medium' : 'text-gray-400')}>{t.label}</span>
                            </button>
                        ))}
                    </div>
                ))}
            </div>
        </div>
    );
}



// ═══════════════════════════════════════════════════════════════════════════════
// ── ZebuLiveChart React component ─────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════

const ZebuLiveChart = memo(function ZebuLiveChart({
    candles = [],
    isLoading = false,
    trendData = null,
    period = '1D',
    onPeriodChange,
    symbol = '',
    zeroLossTrend = null,
    onPriceUpdate,
    livePrice = null,
    liveVolume = null,
    isolateLivePrice = false,
}) {
    const { theme } = useTheme();
    const chartContainerRef = useRef(null);
    const rsiChartContainerRef = useRef(null);
    const chartWrapperRef = useRef(null);
    const chartRef = useRef(null);
    const rsiChartRef = useRef(null);
    const candleSeriesRef = useRef(null);
    const volumeSeriesRef = useRef(null);
    const indicatorSeriesRef = useRef([]);
    const rsiSeriesRef = useRef(null);
    const rsiLevelLinesRef = useRef([]);
    const rsiCurrentLineRef = useRef(null);
    const livePriceLineRef = useRef(null);
    const hLinePricesRef = useRef([]);
    const candlesRef = useRef([]);
    const activeToolRef = useRef(null);
    const liveUpdateRafRef = useRef(null);
    const pendingLiveQuoteRef = useRef(null);
    const liveVolumeStateRef = useRef(null);
    const liveQuotePriceRef = useRef(null);

    const liveQuotes = useMarketStore((s) => (isolateLivePrice ? EMPTY_LIVE_QUOTES : s.symbols));
    const liveQuote = useMemo(() => {
        const ext = Number(livePrice);
        if (Number.isFinite(ext) && ext > 0) {
            return {
                price: ext,
                timestamp: Math.floor(Date.now() / 1000),
                source: 'futures_ws',
            };
        }
        if (isolateLivePrice) return null;
        return getLiveQuoteForSymbol(symbol, liveQuotes);
    }, [symbol, liveQuotes, livePrice, isolateLivePrice]);
    const wsStatus = useMarketStore((s) => s.wsStatus);
    const lastQuoteAt = useMarketStore((s) => (isolateLivePrice ? 0 : s.lastQuoteAt));
    const marketSessionTick = useSyncExternalStore(
        (cb) => marketSessionManager.subscribe(cb),
        () => marketSessionManager.getSnapshot().fetchedAt,
        () => 0,
    );
    const marketLive = shouldUseRealtimePrices();
    const livePriceForEffect = useMemo(() => {
        const ext = Number(livePrice);
        if (Number.isFinite(ext) && ext > 0) return ext;
        return toFiniteNumber(liveQuote?.price);
    }, [livePrice, liveQuote?.price]);

    const [activeIndicators, setActiveIndicators] = useState(() => {
        try {
            const saved = localStorage.getItem('zebu_active_indicators');
            return saved ? new Set(JSON.parse(saved)) : new Set();
        } catch {
            return new Set();
        }
    });
    const [hiddenIndicators, setHiddenIndicators] = useState(() => {
        try {
            const saved = localStorage.getItem('zebu_hidden_indicators');
            return saved ? new Set(JSON.parse(saved)) : new Set();
        } catch {
            return new Set();
        }
    });
    const [legendCollapsed, setLegendCollapsed] = useState(() => {
        try {
            const saved = localStorage.getItem('zebu_legend_collapsed');
            return saved === 'true';
        } catch {
            return false;
        }
    });

    useEffect(() => {
        localStorage.setItem('zebu_active_indicators', JSON.stringify([...activeIndicators]));
    }, [activeIndicators]);

    useEffect(() => {
        localStorage.setItem('zebu_hidden_indicators', JSON.stringify([...hiddenIndicators]));
    }, [hiddenIndicators]);

    useEffect(() => {
        localStorage.setItem('zebu_legend_collapsed', String(legendCollapsed));
    }, [legendCollapsed]);

    const [showIndicatorMenu, setShowIndicatorMenu] = useState(false);
    const [showToolsMenu, setShowToolsMenu] = useState(false);
    const [showPeriodMenu, setShowPeriodMenu] = useState(false);
    const periodMenuRef = useRef(null);
    const [activeTool, setActiveTool] = useState(null);
    const [hLines, setHLines] = useState([]);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const menuRef = useRef(null);
    const indicatorMenuRef = useRef(null);
    const toolsMenuRef = useRef(null);
    const showRSIPane = activeIndicators.has('rsi14') && !hiddenIndicators.has('rsi14');
    const periodCfg = CHART_PERIODS[period] || CHART_PERIODS[DEFAULT_CHART_PERIOD];
    const isIntradayPeriod = periodCfg?.group === 'intraday';
    const isIntradayPeriodRef = useRef(isIntradayPeriod);
    const isDarkTheme = theme === 'dark';

    useEffect(() => {
        isIntradayPeriodRef.current = isIntradayPeriod;
    }, [isIntradayPeriod]);

    useEffect(() => {
        liveQuotePriceRef.current = toFiniteNumber(liveQuote?.price);
    }, [liveQuote?.price]);

    const tickMarkFormatter = useCallback(
        (time) => formatMarketTimeTick(time, isIntradayPeriodRef.current),
        []
    );

    const crosshairTimeFormatter = useCallback(
        (time) => formatMarketTimeCrosshair(time, isIntradayPeriodRef.current),
        []
    );

    // Keep activeToolRef in sync for chart click handler
    useEffect(() => { activeToolRef.current = activeTool; }, [activeTool]);

    useEffect(() => {
        return () => {
            if (liveUpdateRafRef.current) {
                cancelAnimationFrame(liveUpdateRafRef.current);
                liveUpdateRafRef.current = null;
            }
            pendingLiveQuoteRef.current = null;
            liveVolumeStateRef.current = null;
        };
    }, []);

    // ── Close menus on outside click ──────────────────────────────
    useEffect(() => {
        if (!showIndicatorMenu && !showToolsMenu && !showPeriodMenu) return;
        const handler = (e) => {
            if (indicatorMenuRef.current && !indicatorMenuRef.current.contains(e.target)) setShowIndicatorMenu(false);
            if (toolsMenuRef.current && !toolsMenuRef.current.contains(e.target)) setShowToolsMenu(false);
            if (periodMenuRef.current && !periodMenuRef.current.contains(e.target)) setShowPeriodMenu(false);
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [showIndicatorMenu, showToolsMenu, showPeriodMenu]);

    // ── Indicator toggle ──────────────────────────────────────────
    const toggleIndicator = useCallback((id) => {
        setActiveIndicators(prev => {
            const next = new Set(prev);
            if (next.has(id)) {
                next.delete(id);
                setHiddenIndicators(h => {
                    const nextH = new Set(h);
                    nextH.delete(id);
                    return nextH;
                });
            } else {
                next.add(id);
            }
            return next;
        });
    }, []);

    const toggleHideIndicator = useCallback((id) => {
        setHiddenIndicators(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    }, []);

    // ── Chart creation & cleanup ──────────────────────────────────
    useEffect(() => {
        if (!chartContainerRef.current) return;

        const isDark = theme === 'dark';
        const chart = createChart(chartContainerRef.current, {
            autoSize: true,
            layout: {
                background: { color: 'transparent' },
                textColor: isDark ? '#9ca3af' : '#6b7280',
                fontFamily: 'Inter, system-ui, sans-serif',
                fontSize: 11,
            },
            localization: {
                locale: 'en-IN',
                timeFormatter: crosshairTimeFormatter,
            },
            grid: {
                vertLines: { color: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.07)' },
                horzLines: { color: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.07)' },
            },
            crosshair: {
                mode: CrosshairMode.Normal,
                vertLine: { color: 'rgba(99,102,241,0.4)', width: 1, style: 3, labelBackgroundColor: 'rgba(99,102,241,0.85)', labelVisible: false },
                horzLine: { color: 'rgba(99,102,241,0.4)', width: 1, style: 3, labelBackgroundColor: 'rgba(99,102,241,0.85)' },
            },
            rightPriceScale: {
                borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.08)',
                scaleMargins: { top: 0.08, bottom: 0.22 },
                autoScale: true,
            },
            timeScale: {
                borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.08)',
                timeVisible: true,
                secondsVisible: false,
                tickMarkFormatter,
                rightOffset: 5,
                barSpacing: 8,
                minBarSpacing: 2,
                rightBarStaysOnScroll: true,
                lockVisibleTimeRangeOnResize: true,
            },
            handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
            handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
        });

        const candleSeries = chart.addCandlestickSeries({
            upColor: UP_COLOR,
            downColor: DOWN_COLOR,
            borderUpColor: UP_COLOR,
            borderDownColor: DOWN_COLOR,
            wickUpColor: UP_COLOR,
            wickDownColor: DOWN_COLOR,
            priceLineVisible: false,
            lastValueVisible: true,
        });

        const volumeSeries = chart.addHistogramSeries({
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
        });
        chart.priceScale('volume').applyOptions({
            scaleMargins: { top: 0.80, bottom: 0 },
        });

        chartRef.current = chart;
        candleSeriesRef.current = candleSeries;
        volumeSeriesRef.current = volumeSeries;

        // Click handler for horizontal line tools
        chart.subscribeClick((param) => {
            const tool = activeToolRef.current;
            if (!tool || tool === 'crosshair' || !param.point) return;
            const price = candleSeries.coordinateToPrice(param.point.y);
            if (price != null && isFinite(price)) {
                const colorMap = {
                    hline: '#00bcd4',
                    hline_sup: '#10B981',
                    hline_res: '#EF4444',
                    hline_target: '#00bcd4',
                    hline_sl: '#EF4444',
                    hline_entry: '#FBBF24',
                };
                const labelMap = {
                    hline_sup: 'Support',
                    hline_res: 'Resistance',
                    hline_target: 'Target',
                    hline_sl: 'Stop Loss',
                    hline_entry: 'Entry',
                };
                const color = colorMap[tool] || '#00bcd4';
                const title = labelMap[tool] || '';
                setHLines(prev => [...prev, { price, color, title }]);
            }
        });

        return () => {
            chart.remove();
            chartRef.current = null;
            candleSeriesRef.current = null;
            volumeSeriesRef.current = null;
            indicatorSeriesRef.current = [];
        };
    }, [theme, crosshairTimeFormatter, tickMarkFormatter]); // Recreate chart when theme changes

    // ── RSI dedicated pane (professional oscillator panel) ───────────────────
    useEffect(() => {
        if (!showRSIPane) {
            if (rsiChartRef.current) {
                try { rsiChartRef.current.remove(); } catch { /* ignore */ }
            }
            rsiChartRef.current = null;
            rsiSeriesRef.current = null;
            rsiLevelLinesRef.current = [];
            rsiCurrentLineRef.current = null;
            return;
        }

        if (!rsiChartContainerRef.current || !chartRef.current) return;

        const isDark = theme === 'dark';
        const mainChart = chartRef.current;
        const rsiChart = createChart(rsiChartContainerRef.current, {
            autoSize: true,
            layout: {
                background: { color: isDark ? 'rgba(91, 33, 182, 0.06)' : 'rgba(99, 102, 241, 0.06)' },
                textColor: isDark ? '#9ca3af' : '#6b7280',
                fontFamily: 'Inter, system-ui, sans-serif',
                fontSize: 11,
            },
            localization: {
                locale: 'en-IN',
                timeFormatter: crosshairTimeFormatter,
            },
            grid: {
                vertLines: { color: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)' },
                horzLines: { color: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)' },
            },
            crosshair: {
                mode: CrosshairMode.Normal,
                vertLine: { color: 'rgba(99,102,241,0.35)', width: 1, style: 3, labelBackgroundColor: 'rgba(99,102,241,0.85)' },
                horzLine: { color: 'rgba(99,102,241,0.35)', width: 1, style: 3, labelBackgroundColor: 'rgba(99,102,241,0.85)' },
            },
            rightPriceScale: {
                borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.08)',
                scaleMargins: { top: 0.06, bottom: 0.08 },
            },
            timeScale: {
                borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.08)',
                timeVisible: true,
                secondsVisible: false,
                tickMarkFormatter,
                rightOffset: 5,
                barSpacing: 8,
                minBarSpacing: 2,
                visible: false,
            },
            handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
            handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
        });

        const rsiSeries = rsiChart.addLineSeries({
            color: INDICATOR_DEFS.rsi14.color,
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: true,
            crosshairMarkerVisible: true,
            crosshairMarkerRadius: 3,
            autoscaleInfoProvider: () => ({
                priceRange: { minValue: 0, maxValue: 100 },
            }),
        });

        const levelStyles = {
            70: { color: 'rgba(239,68,68,0.65)', lineStyle: 2 },
            50: { color: 'rgba(148,163,184,0.45)', lineStyle: 1 },
            30: { color: 'rgba(16,185,129,0.65)', lineStyle: 2 },
        };
        rsiLevelLinesRef.current = RSI_LEVELS.map((lvl) => rsiSeries.createPriceLine({
            price: lvl,
            color: levelStyles[lvl].color,
            lineWidth: 1,
            lineStyle: levelStyles[lvl].lineStyle,
            axisLabelVisible: true,
            title: '',
        }));

        let syncing = false;
        const syncFromMain = (range) => {
            if (syncing || !isValidVisibleRange(range)) return;
            syncing = true;
            try {
                rsiChart.timeScale().setVisibleRange(range);
            } catch {
                // Ignore transient invalid ranges emitted during chart/data transitions
            }
            syncing = false;
        };

        mainChart.timeScale().subscribeVisibleTimeRangeChange(syncFromMain);

        const mainRange = mainChart.timeScale().getVisibleRange();
        if (isValidVisibleRange(mainRange)) {
            try {
                rsiChart.timeScale().setVisibleRange(mainRange);
            } catch {
                // Ignore if range cannot be applied during initialization
            }
        }

        rsiChartRef.current = rsiChart;
        rsiSeriesRef.current = rsiSeries;

        return () => {
            mainChart.timeScale().unsubscribeVisibleTimeRangeChange(syncFromMain);
            try { rsiChart.remove(); } catch { /* ignore */ }
            rsiChartRef.current = null;
            rsiSeriesRef.current = null;
            rsiLevelLinesRef.current = [];
            rsiCurrentLineRef.current = null;
        };
    }, [showRSIPane, theme]);

    // ── RSI series data & current value line ─────────────────────────────────
    useEffect(() => {
        if (!showRSIPane || !rsiSeriesRef.current || candlesRef.current.length === 0) return;

        const rsiVals = rsi(candlesRef.current.map((c) => c.close), 14);
        const data = rsiVals
            .map((v, i) => ({ time: candlesRef.current[i]?.time, value: Number.isFinite(v) ? Math.max(0, Math.min(100, v)) : undefined }))
            .filter((d) => d.time != null && d.value !== undefined);

        rsiSeriesRef.current.setData(data);

        const last = data.length ? data[data.length - 1].value : null;
        if (last != null) {
            if (rsiCurrentLineRef.current) {
                try { rsiSeriesRef.current.removePriceLine(rsiCurrentLineRef.current); } catch { /* ignore */ }
            }
            const currentColor = last >= 70
                ? '#EF4444'
                : last <= 30
                    ? '#10B981'
                    : INDICATOR_DEFS.rsi14.color;
            rsiCurrentLineRef.current = rsiSeriesRef.current.createPriceLine({
                price: last,
                color: currentColor,
                lineWidth: 1,
                lineStyle: 2,
                axisLabelVisible: true,
                title: '',
            });
        }
    }, [showRSIPane, candles, theme, crosshairTimeFormatter, tickMarkFormatter]);

    // ── Set candle data ───────────────────────────────────────────
    useEffect(() => {
        const cs = candleSeriesRef.current;
        const vs = volumeSeriesRef.current;
        if (!cs || !vs) return;

        if (!candles || candles.length === 0) {
            candlesRef.current = [];
            cs.setData([]);
            vs.setData([]);
            onPriceUpdate?.({ price: null, source: 'reset', symbol });
            return;
        }

        const deduped = normalizeChartCandles(candles);
        const bucketAligned = alignCandlesToPeriodBuckets(deduped, periodCfg?.interval);

        if (bucketAligned.length === 0) {
            candlesRef.current = [];
            cs.setData([]);
            vs.setData([]);
            onPriceUpdate?.({ price: null, source: 'reset', symbol });
            return;
        }

        const quotePrice = liveQuotePriceRef.current;
        const alignedCandles = alignCandlesToLiveQuote(bucketAligned, quotePrice);

        candlesRef.current = alignedCandles.map(c => ({ ...c, time: c.time }));
        liveVolumeStateRef.current = null;

        cs.setData(alignedCandles.map(c => ({
            time: c.time,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
        })));

        vs.setData(alignedCandles.map(c => ({
            time: c.time,
            value: c.volume || 0,
            color: c.close >= c.open ? 'rgba(38,166,154,0.50)' : 'rgba(239,83,80,0.50)',
        })));

        // For intraday charts with many candles, show only the most recent
        // portion so candles are a readable size. For daily+ charts, fit all.
        const chart = chartRef.current;
        if (chart) {
            const totalBars = alignedCandles.length;
            // Show a wider intraday window so previous candles remain visible,
            // while still keeping readable bar width.
            if (isIntradayPeriod && totalBars > 0) {
                const visibleBars = Math.min(240, totalBars);
                chart.timeScale().applyOptions({
                    rightOffset: 5,
                    barSpacing: Math.max(4, Math.min(10, (chartContainerRef.current?.clientWidth || 800) / visibleBars)),
                });
                chart.timeScale().scrollToRealTime();
            } else {
                chart.timeScale().fitContent();
            }
        }
    }, [candles, period, theme, onPriceUpdate, isIntradayPeriod]);

    // ── Quote-based history alignment safeguard ─────────────────
    // If history loaded from fallback source is far from live quote (>50%),
    // rebase once so timeframe switches don't show wildly different prices.
    // Small deviations are left as-is — the live price line and real-time
    // tick updates handle showing the current price without distorting candles.
    useEffect(() => {
        if (!marketLive) return;
        const cs = candleSeriesRef.current;
        const vs = volumeSeriesRef.current;
        const quotePrice = toFiniteNumber(liveQuote?.price);
        if (!cs || !vs || quotePrice == null || quotePrice <= 0) return;
        if (!candlesRef.current || candlesRef.current.length === 0) return;

        const lastClose = toFiniteNumber(candlesRef.current[candlesRef.current.length - 1]?.close);
        if (!shouldRebaseFromQuote(lastClose, quotePrice)) return;

        const rebased = rebaseCandlesToTargetClose(candlesRef.current, quotePrice);
        if (!rebased || rebased.length === 0) return;

        candlesRef.current = rebased;
        cs.setData(rebased.map(c => ({
            time: c.time,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
        })));
        vs.setData(rebased.map(c => ({
            time: c.time,
            value: c.volume || 0,
            color: c.close >= c.open ? 'rgba(38,166,154,0.50)' : 'rgba(239,83,80,0.50)',
        })));
    }, [liveQuote?.price, symbol, marketLive]);

    // ── Clear stale refs on symbol change ────────────────────────
    // NOTE: We do NOT call cs.setData([]) here. The candle-data effect
    // below already handles clearing (when candles==[]) and setting new data.
    // Calling setData([]) here causes a black flash because TradingView schedules
    // a canvas repaint via requestAnimationFrame — the canvas goes visibly black
    // for one frame before the candle-data effect sets the new symbol's data.
    useEffect(() => {
        const cs = candleSeriesRef.current;
        candlesRef.current = [];
        onPriceUpdate?.({ price: null, source: 'reset', symbol });
        liveVolumeStateRef.current = null;
        if (livePriceLineRef.current) {
            try { cs?.removePriceLine(livePriceLineRef.current); } catch { /* ignore */ }
            livePriceLineRef.current = null;
        }
        // Clear indicator series (these are safe to remove immediately)
        const chart = chartRef.current;
        if (chart) {
            for (const s of indicatorSeriesRef.current) {
                try { chart.removeSeries(s); } catch { /* ignore */ }
            }
            indicatorSeriesRef.current = [];
        }
    }, [symbol, onPriceUpdate]);

    // ── Live price updates (live session only — frozen on holiday/closed) ──
    useEffect(() => {
        if (!marketLive) return;
        const cs = candleSeriesRef.current;
        const vs = volumeSeriesRef.current;
        const ltp = toFiniteNumber(livePriceForEffect);
        if (!cs || !vs || ltp == null || ltp <= 0) return;

        if (!isolateLivePrice) {
            const marketStatus = String(liveQuote?.market_status || '').toLowerCase();
            if (CLOSED_MARKET_STATUSES.has(marketStatus)) return;
            // Block only if the last known live quote is very stale (>5 min).
            if (lastQuoteAt > 0 && (Date.now() - lastQuoteAt) > 300_000) return;
        }

        const quoteTs = isolateLivePrice
            ? Math.floor(Date.now() / 1000)
            : parseQuoteEpochSeconds(
                liveQuote?.last_trade_time ?? liveQuote?.timestamp ?? liveQuote?.ft
            );
        if (quoteTs == null) return;

        const nowSec = Math.floor(Date.now() / 1000);
        if (quoteTs > nowSec + 120) return;

        const maxAgeSeconds = Math.max(LIVE_QUOTE_MAX_AGE_SECONDS, getIntervalSeconds(period) * 3);
        if ((nowSec - quoteTs) > maxAgeSeconds) return;

        pendingLiveQuoteRef.current = {
            ltp,
            cumulativeVolume: toFiniteNumber(liveQuote?.volume ?? liveVolume),
            quoteTs,
            intervalSeconds: getIntervalSeconds(period),
            intervalCode: periodCfg?.interval,
        };

        if (liveUpdateRafRef.current) return;

        liveUpdateRafRef.current = requestAnimationFrame(() => {
            liveUpdateRafRef.current = null;
            const pending = pendingLiveQuoteRef.current;
            pendingLiveQuoteRef.current = null;
            if (!pending) return;

            const quoteSec = pending.quoteTs;
            if (!Number.isFinite(quoteSec)) return;
            const displayTs = quoteSec;

            if (candlesRef.current.length === 0) {
                return;
            }

            let lastCandle = candlesRef.current[candlesRef.current.length - 1];
            if (!lastCandle) return;

            const bucketTime = alignBucketTime(
                displayTs,
                Number(lastCandle.time),
                pending.intervalSeconds,
                pending.intervalCode,
            );
            if (!Number.isFinite(bucketTime)) return;

            if (bucketTime < lastCandle.time) return;

            const maxForwardGap = Math.max(pending.intervalSeconds * 12, 30 * 60);
            if ((bucketTime - lastCandle.time) > maxForwardGap) return;

            // Guard against cross-symbol/stale-source jumps creating extreme spikes.
            const baseClose = toFiniteNumber(lastCandle.close);
            if (shouldRebaseFromQuote(baseClose, pending.ltp)) {
                const rebased = rebaseCandlesToTargetClose(candlesRef.current, pending.ltp);
                if (!rebased || rebased.length === 0) return;

                candlesRef.current = rebased;
                lastCandle = candlesRef.current[candlesRef.current.length - 1];
                if (!lastCandle) return;

                cs.setData(rebased.map(c => ({
                    time: c.time,
                    open: c.open,
                    high: c.high,
                    low: c.low,
                    close: c.close,
                })));

                vs.setData(rebased.map(c => ({
                    time: c.time,
                    value: c.volume || 0,
                    color: c.close >= c.open ? 'rgba(38,166,154,0.50)' : 'rgba(239,83,80,0.50)',
                })));
            }

            let updated;

            // Roll into a new candle when timeframe bucket changes.
            if (bucketTime > lastCandle.time) {
                let nextVolume = 0;
                const prevVolState = liveVolumeStateRef.current;
                if (pending.cumulativeVolume != null && pending.cumulativeVolume >= 0) {
                    const baseCum = prevVolState && Number.isFinite(prevVolState.lastCumVolume)
                        ? prevVolState.lastCumVolume
                        : pending.cumulativeVolume;
                    nextVolume = Math.max(0, pending.cumulativeVolume - baseCum);
                    liveVolumeStateRef.current = {
                        bucketTime,
                        baseCumVolume: baseCum,
                        lastCumVolume: pending.cumulativeVolume,
                    };
                } else {
                    liveVolumeStateRef.current = null;
                }

                updated = {
                    time: bucketTime,
                    open: lastCandle.close,
                    high: Math.max(lastCandle.close, pending.ltp),
                    low: Math.min(lastCandle.close, pending.ltp),
                    close: pending.ltp,
                    volume: nextVolume,
                };
                candlesRef.current.push(updated);
            } else {
                // Update current in-progress candle.
                updated = { ...lastCandle };
                updated.close = pending.ltp;
                if (pending.ltp > updated.high) updated.high = pending.ltp;
                if (pending.ltp < updated.low) updated.low = pending.ltp;

                if (pending.cumulativeVolume != null && pending.cumulativeVolume >= 0) {
                    let volState = liveVolumeStateRef.current;
                    if (!volState || volState.bucketTime !== bucketTime) {
                        const priorVolume = toFiniteNumber(updated.volume) ?? 0;
                        const baseCum = Math.max(0, pending.cumulativeVolume - priorVolume);
                        volState = {
                            bucketTime,
                            baseCumVolume: baseCum,
                            lastCumVolume: pending.cumulativeVolume,
                        };
                    }

                    if (pending.cumulativeVolume < volState.baseCumVolume) {
                        volState.baseCumVolume = pending.cumulativeVolume;
                    }
                    volState.lastCumVolume = pending.cumulativeVolume;
                    updated.volume = Math.max(0, pending.cumulativeVolume - volState.baseCumVolume);
                    liveVolumeStateRef.current = volState;
                }

                candlesRef.current[candlesRef.current.length - 1] = updated;
            }

            cs.update({
                time: updated.time,
                open: updated.open,
                high: updated.high,
                low: updated.low,
                close: updated.close,
            });

            vs.update({
                time: updated.time,
                value: updated.volume || 0,
                color: updated.close >= updated.open ? 'rgba(38,166,154,0.50)' : 'rgba(239,83,80,0.50)',
            });

            // Update live price line (same LTP as last candle close)
            const axisPrice = toFiniteNumber(updated.close) ?? pending.ltp;
            if (livePriceLineRef.current) {
                try { cs.removePriceLine(livePriceLineRef.current); } catch { /* ignore */ }
            }
            livePriceLineRef.current = cs.createPriceLine({
                price: axisPrice,
                color: '#00bcd4',
                lineWidth: 1,
                lineStyle: 2, // Dashed
                axisLabelVisible: false,
                title: '',
            });
        });
    }, [livePriceForEffect, wsStatus, lastQuoteAt, periodCfg?.interval, isolateLivePrice, marketLive, marketSessionTick]);

    // ── Indicator overlays ────────────────────────────────────────
    useEffect(() => {
        const chart = chartRef.current;
        if (!chart || candlesRef.current.length === 0) return;

        // Remove old indicator series
        for (const s of indicatorSeriesRef.current) {
            try { chart.removeSeries(s); } catch { /* ignore */ }
        }
        indicatorSeriesRef.current = [];

        const hasOscillator = [...activeIndicators].some(id => id !== 'rsi14' && OSCILLATOR_IDS.has(id) && !hiddenIndicators.has(id));

        // Adjust main candle scale to leave room for oscillator panel
        chart.priceScale('right').applyOptions({
            scaleMargins: hasOscillator ? { top: 0.08, bottom: 0.30 } : { top: 0.08, bottom: 0.22 },
        });
        if (hasOscillator) {
            chart.priceScale('oscillator').applyOptions({
                scaleMargins: { top: 0.76, bottom: 0.02 },
                borderVisible: true,
            });
        }

        // Add new ones
        for (const id of activeIndicators) {
            if (id === 'rsi14') continue;
            if (hiddenIndicators.has(id)) continue;
            const lines = computeIndicatorData(id, candlesRef.current);
            for (const line of lines) {
                const series = chart.addLineSeries({
                    color: line.color,
                    lineWidth: line.width,
                    priceLineVisible: false,
                    lastValueVisible: false,
                    crosshairMarkerVisible: false,
                    ...(line.priceScaleId ? { priceScaleId: line.priceScaleId } : {}),
                });
                series.setData(line.values);
                indicatorSeriesRef.current.push(series);
            }
        }
    }, [activeIndicators, hiddenIndicators, candles, theme]);

    // ── Horizontal user lines ─────────────────────────────────────
    useEffect(() => {
        const cs = candleSeriesRef.current;
        if (!cs) return;

        // Remove old hLines
        for (const pl of hLinePricesRef.current) {
            try { cs.removePriceLine(pl); } catch { /* ignore */ }
        }
        hLinePricesRef.current = [];

        // Add new
        for (const hl of hLines) {
            const pl = cs.createPriceLine({
                price: hl.price,
                color: hl.color || '#00bcd4',
                lineWidth: 1,
                lineStyle: 2,
                axisLabelVisible: true,
                title: hl.title || '',
            });
            hLinePricesRef.current.push(pl);
        }
    }, [hLines, theme]);

    // ── Fullscreen ────────────────────────────────────────────────
    const toggleFullscreen = useCallback(() => {
        if (!chartWrapperRef.current) return;
        if (!document.fullscreenElement) {
            chartWrapperRef.current.requestFullscreen().catch(() => { });
        } else {
            document.exitFullscreen().catch(() => { });
        }
    }, []);

    useEffect(() => {
        const handler = () => {
            setIsFullscreen(document.fullscreenElement === chartWrapperRef.current);
            // autoSize handles resize automatically via its internal ResizeObserver.
        };

        document.addEventListener('fullscreenchange', handler);
        return () => {
            document.removeEventListener('fullscreenchange', handler);
        };
    }, []);

    const clearDrawings = useCallback(() => setHLines([]), []);

    const hasFreshQuotes = lastQuoteAt > 0 && (Date.now() - lastQuoteAt) < 90_000;
    const effectiveWsStatus = wsStatus === 'connected'
        ? 'connected'
        : hasFreshQuotes
            ? 'connected'
            : wsStatus;

    const trend = trendData?.overall ? TREND_STYLE[trendData.overall] || TREND_STYLE.NEUTRAL : null;
    const confidence = trendData?.confidence ?? 0;
    const periodLabel = (CHART_PERIODS[period] || CHART_PERIODS[DEFAULT_CHART_PERIOD]).label;

    return (
        <div ref={chartWrapperRef} className={cn('flex flex-col h-full relative overflow-hidden', isFullscreen && 'bg-surface-900 z-50')}>
            {/* ── Toolbar ──────────────────────────────────────────── */}
            <div className="flex items-center gap-1.5 px-2.5 py-1.5 border-b border-edge/5 bg-surface-900/30 flex-shrink-0 relative z-20" ref={menuRef}>
                {/* Symbol + Period — shown in fullscreen */}
                {isFullscreen && (
                    <>
                        <span className="text-sm font-semibold text-heading flex-shrink-0">
                            {cleanSymbol(symbol)}
                        </span>
                        <div className="relative flex-shrink-0" ref={periodMenuRef}>
                            <button
                                onClick={() => setShowPeriodMenu(v => !v)}
                                className={cn(
                                    'flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium transition-colors',
                                    showPeriodMenu
                                        ? 'bg-primary-500/15 text-primary-500 border border-primary-500/20'
                                        : 'text-gray-500 hover:text-gray-400 hover:bg-surface-800/60'
                                )}
                            >
                                {(CHART_PERIODS[period] || CHART_PERIODS[DEFAULT_CHART_PERIOD]).label}
                                <svg className={cn('w-3 h-3 transition-transform', showPeriodMenu && 'rotate-180')} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                    <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                            </button>
                            {showPeriodMenu && (
                                <div className="absolute top-full left-0 mt-1 w-28 bg-surface-800 border border-edge/10 rounded-xl shadow-panel z-50 animate-slide-in overflow-hidden py-1">
                                    {Object.entries(CHART_PERIODS).map(([key, cfg]) => (
                                        <button
                                            key={key}
                                            onClick={() => { onPeriodChange?.(key); setShowPeriodMenu(false); }}
                                            className={cn(
                                                'w-full text-left px-3 py-1.5 text-xs font-semibold transition-colors',
                                                period === key
                                                    ? 'bg-primary-500/15 text-primary-500'
                                                    : 'text-gray-400 hover:text-gray-300 hover:bg-overlay/[0.04]'
                                            )}
                                        >
                                            {cfg.label}
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                        <div className="w-px h-4 bg-edge/10 flex-shrink-0" />
                    </>
                )}

                {/* Status badge */}
                <div className={cn(
                    'flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold flex-shrink-0 border',
                    effectiveWsStatus === 'connected'
                        ? 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20'
                        : effectiveWsStatus === 'connecting'
                            ? 'text-primary-600 bg-primary-500/10 border-primary-500/20'
                            : 'text-gray-500 bg-surface-800/60 border-edge/10'
                )}>
                    <span className={cn(
                        'w-1.5 h-1.5 rounded-full',
                        effectiveWsStatus === 'connected' ? 'bg-emerald-400 animate-pulse'
                            : effectiveWsStatus === 'connecting' ? 'bg-primary-500 animate-pulse'
                                : 'bg-gray-500'
                    )} />
                    {!marketLive
                        ? 'FROZEN'
                        : effectiveWsStatus === 'connected'
                            ? 'LIVE'
                            : effectiveWsStatus === 'connecting'
                                ? 'CONNECTING'
                                : 'OFFLINE'}
                </div>

                <div className="w-px h-4 bg-edge/10 flex-shrink-0" />

                <div className="relative flex-shrink-0">
                    <button onClick={() => { setShowIndicatorMenu(v => !v); setShowToolsMenu(false); }}
                        className={cn('flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium transition-colors',
                            activeIndicators.size > 0 ? 'bg-primary-500/15 text-primary-500 border border-primary-500/20' : 'text-gray-500 hover:text-gray-400 hover:bg-surface-800/60')}>
                        <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M3 3v18h18" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M7 16l4-8 4 5 5-9" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        Indicators
                        {activeIndicators.size > 0 && <span className="w-3.5 h-3.5 rounded-full bg-primary-500/30 text-[9px] flex items-center justify-center">{activeIndicators.size}</span>}
                    </button>
                    {showIndicatorMenu && <IndicatorMenu active={activeIndicators} onToggle={toggleIndicator} menuRef={indicatorMenuRef} />}
                </div>

                <div className="relative flex-shrink-0">
                    <button onClick={() => { setShowToolsMenu(v => !v); setShowIndicatorMenu(false); }}
                        className={cn('flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium transition-colors',
                            activeTool ? 'bg-primary-500/15 text-primary-500 border border-primary-500/20' : 'text-gray-500 hover:text-gray-400 hover:bg-surface-800/60')}>
                        <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M2 17l10-10M11.7 7.3l4-4a1.4 1.4 0 0 1 2 2l-4 4M15.7 11.3l4 4a1.4 1.4 0 0 1-2 2l-4-4" strokeLinecap="round" strokeLinejoin="round" />
                            <path d="M18 22H4a2 2 0 0 1-2-2V4" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        Tools
                    </button>
                    {showToolsMenu && <ToolsMenu activeTool={activeTool} onSelect={setActiveTool} onClose={() => setShowToolsMenu(false)} menuRef={toolsMenuRef} />}
                </div>

                {hLines.length > 0 && (
                    <button onClick={clearDrawings} className="px-2 py-0.5 rounded-md text-[11px] font-medium text-gray-600 hover:text-red-400 hover:bg-red-500/10 transition-colors flex-shrink-0">
                        Clear
                    </button>
                )}



                {/* Spacer */}
                <div className="flex-1 min-w-[8px]" />

                {/* Right group: Strategy signals + Fullscreen */}
                <div
                    className="flex items-center gap-1.5 flex-shrink-0 transition-opacity duration-500"
                    style={{ opacity: candles.length > 0 ? 1 : 0 }}
                >
                    {trend && (
                        <div className={cn(trend.cls, 'text-[10px] !py-0.5 !px-2')}>
                            <span className="text-[10px] leading-none">{trend.icon}</span>
                            <span>Multi-Strategy</span>
                            <span>{trend.label}</span>
                            {confidence > 0 && <span className="opacity-60 font-price font-medium ml-0.5">{Math.round(confidence)}%</span>}
                        </div>
                    )}
                    {zeroLossTrend && (() => {
                        const dir = zeroLossTrend.direction;
                        let color, icon, label;
                        if (dir === 'BULLISH') { color = 'bg-emerald-500/15 border-emerald-500/25 text-emerald-600'; icon = <TrendingUp className="w-3 h-3" />; label = 'BULLISH'; }
                        else if (dir === 'BEARISH') { color = 'bg-red-500/15 border-red-500/25 text-red-500'; icon = <TrendingDown className="w-3 h-3" />; label = 'BEARISH'; }
                        else { color = 'bg-primary-500/10 border-primary-500/20 text-primary-600'; icon = <MinusCircle className="w-3 h-3" />; label = 'NEUTRAL'; }
                        return (
                            <div className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold', color)}>
                                {icon}<span>Alpha AutoTrade</span><span>{label}</span>
                                {typeof zeroLossTrend.score === 'number' && zeroLossTrend.score > 0 && <span className="opacity-60 font-medium ml-0.5">{Math.round(zeroLossTrend.score)}%</span>}
                            </div>
                        );
                    })()}
                </div>

                <button onClick={toggleFullscreen} className="p-1 rounded-md text-gray-500 hover:text-gray-400 hover:bg-surface-800/60 transition-colors flex-shrink-0" title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
                    {isFullscreen ? (
                        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3" />
                        </svg>
                    ) : (
                        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
                        </svg>
                    )}
                </button>
            </div>

            {/* ── Chart area ───────────────────────────────────────── */}
            <div className="flex-1 relative min-h-0 bg-surface-900">
                {/* Loading skeleton — shown while loading with no candles yet */}
                <div
                    className="absolute inset-0 flex items-center justify-center z-20 transition-opacity duration-300"
                    style={{
                        opacity: isLoading && candles.length === 0 ? 1 : 0,
                        pointerEvents: isLoading && candles.length === 0 ? 'auto' : 'none',
                    }}
                >
                    <div className="absolute inset-0">
                        <div
                            className="absolute inset-0"
                            style={{
                                background: isDarkTheme
                                    ? 'radial-gradient(120% 100% at 50% 0%, rgba(14,165,233,0.14) 0%, rgba(15,23,42,0.88) 48%, rgba(2,6,23,0.98) 100%)'
                                    : 'radial-gradient(120% 100% at 50% 0%, rgba(14,165,233,0.10) 0%, rgba(244,248,252,0.94) 52%, rgba(255,255,255,0.98) 100%)',
                            }}
                        />

                        <div
                            className="absolute inset-0 opacity-35"
                            style={{
                                backgroundImage: isDarkTheme
                                    ? 'linear-gradient(to right, rgba(148,163,184,0.10) 1px, transparent 1px), linear-gradient(to bottom, rgba(148,163,184,0.09) 1px, transparent 1px)'
                                    : 'linear-gradient(to right, rgba(148,163,184,0.16) 1px, transparent 1px), linear-gradient(to bottom, rgba(148,163,184,0.14) 1px, transparent 1px)',
                                backgroundSize: '64px 100%, 100% 52px',
                            }}
                        />

                        <div className="absolute left-0 right-0 bottom-[24%] h-px bg-primary-500/25" />

                        <div className="absolute left-4 right-4 top-16 bottom-16 flex items-end justify-between gap-1.5">
                            {LOADING_CANDLE_TEMPLATE.map((bar, idx) => {
                                const isBull = bar.tone === 'up';
                                return (
                                    <div
                                        key={`${bar.tone}-${idx}`}
                                        className="relative flex-1 max-w-[20px] min-w-[6px] animate-pulse"
                                        style={{ animationDelay: `${idx * 90}ms` }}
                                    >
                                        <div
                                            className={cn(
                                                'absolute left-1/2 -translate-x-1/2 w-px rounded-full',
                                                isBull ? 'bg-emerald-400/50' : 'bg-rose-400/50'
                                            )}
                                            style={{
                                                height: `${bar.wick}%`,
                                                bottom: `${Math.max(0, bar.base - 6)}%`,
                                            }}
                                        />
                                        <div
                                            className={cn(
                                                'absolute left-1/2 -translate-x-1/2 w-2 rounded-sm',
                                                isBull ? 'bg-emerald-400/35' : 'bg-rose-400/35'
                                            )}
                                            style={{
                                                height: `${bar.body}%`,
                                                bottom: `${bar.base}%`,
                                            }}
                                        />
                                    </div>
                                );
                            })}
                        </div>

                        <div className="absolute left-1/2 bottom-5 -translate-x-1/2">
                            <div className={cn(
                                'flex items-center gap-2 rounded-full border border-primary-500/25 px-3 py-1.5 backdrop-blur-sm',
                                isDarkTheme ? 'bg-surface-900/80' : 'bg-surface-50/90'
                            )}>
                                <div className="w-3.5 h-3.5 border-2 rounded-full animate-spin" style={{ borderColor: 'rgba(6,182,212,0.28)', borderTopColor: '#06b6d4' }} />
                                <span className={cn('text-[11px] font-medium', isDarkTheme ? 'text-gray-400' : 'text-gray-600')}>
                                    Loading {cleanSymbol(symbol)} · {periodLabel}
                                </span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Empty state — shown after load completes with no data */}
                {!isLoading && candles.length === 0 && (
                    <div className="absolute inset-0 flex items-center justify-center z-20">
                        <div className="text-gray-600 text-sm">No chart data available for this symbol</div>
                    </div>
                )}

                {/* Floating Legend Overlay */}
                {candles.length > 0 && (
                    <div className="absolute top-3 left-3 z-10 pointer-events-auto flex flex-col gap-1 bg-surface-900/85 backdrop-blur-sm px-2.5 py-1.5 rounded-lg border border-edge/10 select-none min-w-[150px] max-w-xs shadow-lg">
                        {/* Symbol Info */}
                        <div className="flex items-center gap-1.5 text-[11px] font-semibold text-heading">
                            <span className="text-primary-500 font-bold">{cleanSymbol(symbol)}</span>
                            <span className="text-gray-600">·</span>
                            <span className="text-gray-400 font-medium">{periodLabel}</span>
                            <span className="text-gray-600">·</span>
                            <span className="text-gray-500 text-[10px]">NSE</span>
                            
                            <button
                                onClick={() => setLegendCollapsed(c => !c)}
                                className="ml-2 p-0.5 rounded hover:bg-overlay/10 text-gray-500 hover:text-gray-300 transition-colors"
                                title={legendCollapsed ? "Expand legend" : "Collapse legend"}
                            >
                                {legendCollapsed ? (
                                    <ChevronDown className="w-3.5 h-3.5" />
                                ) : (
                                    <ChevronUp className="w-3.5 h-3.5" />
                                )}
                            </button>
                        </div>

                        {/* Active Indicators List */}
                        {!legendCollapsed && activeIndicators.size > 0 && (
                            <div className="flex flex-col gap-1 mt-1.5 border-t border-edge/5 pt-1.5">
                                {[...activeIndicators].map(id => {
                                    const def = INDICATOR_DEFS[id];
                                    if (!def) return null;
                                    const isHidden = hiddenIndicators.has(id);
                                    return (
                                        <div key={id} className="group/item flex items-center gap-2 hover:bg-overlay/5 px-1 py-0.5 rounded transition-colors text-[10px]">
                                            {/* Color dot */}
                                            <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: def.color }} />
                                            
                                            {/* Label */}
                                            <span className={cn("transition-colors", isHidden ? "text-gray-600 line-through" : "text-gray-300")}>
                                                {def.label}
                                            </span>

                                            {/* Controls (visible on hover) */}
                                            <div className="ml-auto flex items-center gap-1 opacity-0 group-hover/item:opacity-100 transition-opacity">
                                                {/* Toggle visibility */}
                                                <button
                                                    onClick={(e) => { e.stopPropagation(); toggleHideIndicator(id); }}
                                                    className="p-0.5 rounded hover:bg-overlay/10 text-gray-500 hover:text-gray-300 transition-colors"
                                                    title={isHidden ? "Show indicator" : "Hide indicator"}
                                                >
                                                    {isHidden ? (
                                                        <EyeOff className="w-3.5 h-3.5" />
                                                    ) : (
                                                        <Eye className="w-3.5 h-3.5" />
                                                    )}
                                                </button>
                                                
                                                {/* Remove */}
                                                <button
                                                    onClick={(e) => { e.stopPropagation(); toggleIndicator(id); }}
                                                    className="p-0.5 rounded hover:bg-overlay/10 text-gray-500 hover:text-red-400 transition-colors"
                                                    title="Remove indicator"
                                                >
                                                    <X className="w-3.5 h-3.5" />
                                                </button>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                )}


                {activeTool && (
                    <div className="absolute bottom-10 left-1/2 -translate-x-1/2 z-10 pointer-events-none select-none">
                        <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-800/90 border border-edge/10 text-xs text-gray-400 backdrop-blur-sm shadow-lg">
                            {activeTool === 'hline' && 'Click to place horizontal line'}
                            {activeTool === 'hline_sup' && 'Click to place support line (green)'}
                            {activeTool === 'hline_res' && 'Click to place resistance line (red)'}
                            {activeTool === 'crosshair' && 'Crosshair mode active'}
                            <button onClick={() => setActiveTool(null)} className="ml-2 text-gray-600 hover:text-gray-700 pointer-events-auto">ESC</button>
                        </div>
                    </div>
                )}

                <div className="absolute inset-0 flex flex-col">
                    <div className={cn('relative min-h-0 transition-[height] duration-300', showRSIPane ? 'h-[72%]' : 'h-full')}>
                        {/* Main price chart container — fades in smoothly */}
                        <div ref={chartContainerRef} className="absolute inset-0 transition-opacity duration-300"
                            style={{ opacity: candles.length > 0 ? 1 : 0 }} />
                    </div>

                    {showRSIPane && (
                        <div className="relative h-[28%] min-h-[140px] border-t border-edge/10 bg-surface-900/40">
                            <div className="absolute left-2 top-1 z-10 text-[10px] text-gray-500 uppercase tracking-wider font-semibold pointer-events-none">
                                RSI (14)
                            </div>
                            <div ref={rsiChartContainerRef} className="absolute inset-0" />
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}, (prev, next) =>
    prev.candles === next.candles &&
    prev.isLoading === next.isLoading &&
    prev.period === next.period &&
    prev.symbol === next.symbol &&
    prev.livePrice === next.livePrice &&
    prev.liveVolume === next.liveVolume &&
    prev.isolateLivePrice === next.isolateLivePrice &&
    prev.trendData?.overall === next.trendData?.overall &&
    prev.trendData?.confidence === next.trendData?.confidence &&
    prev.zeroLossTrend === next.zeroLossTrend
);

export default ZebuLiveChart;
