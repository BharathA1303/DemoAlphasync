import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import api, { isRateLimited } from '../services/api';
import { shouldUseRealtimePrices, setMarketSessionSnapshot } from '../market/utils/marketSessionUtils';
import { useMarketStore } from '../store/useMarketStore';
import { getLiveQuoteForSymbol } from '../utils/liveQuote';

// Module-level candle cache shared across hook instances.
// Key: `${symbol}:${period}:${interval}` → { candles: [], ts: number }
// Survives symbol switches so switching back to a recent symbol is instant.
const _candleCache = new Map();
const CANDLE_CACHE_TTL = 60_000; // 60 s — matches backend SmartCache TTL
const INTRADAY_INTERVALS = new Set(['1m', '2m', '3m', '5m', '10m', '15m', '30m', '1h', '2h', '4h']);

const shouldCacheCandles = (symbol, interval, candles) => {
    const isIndex = String(symbol || '').trim().startsWith('^');
    if (!isIndex || !INTRADAY_INTERVALS.has(interval)) return true;
    return (candles || []).some((c) => Number(c?.volume) > 0);
};

function getLatestCachedCandlesForSymbol(symbol) {
    let latest = null;
    for (const [key, value] of _candleCache.entries()) {
        if (!key.startsWith(`${symbol}:`)) continue;
        if (!latest || (value?.ts ?? 0) > (latest?.ts ?? 0)) {
            latest = value;
        }
    }
    return latest?.candles || null;
}

/**
 * Fetch and manage market data for a given symbol.
 * Polls for quote updates at a configurable interval.
 *
 * @param {string} symbol - e.g. 'RELIANCE.NS'
 * @param {{ pollInterval?: number }} [options]
 * @returns {{
 *   quote: object|null,
 *   candles: Array,
 *   isLoading: boolean,
 *   hasError: boolean,
 *   refetch: () => void,
 * }}
 */
export function useMarketData(symbol, { pollInterval = 3_000 } = {}) {
    const [candles, setCandles] = useState([]);
    const [candlesSymbol, setCandlesSymbol] = useState(null);
    const [isLoading, setIsLoading] = useState(true);
    const [hasError, setHasError] = useState(false);
    const [isMarketTrading, setIsMarketTrading] = useState(false);

    const MAX_CANDLE_RETRIES = 3;
    const MIN_INDEX_CANDLES_FOR_CACHE = 20;

    const normalizeCandles = useCallback((rows) => {
        const seen = new Map();
        const nowSec = Math.floor(Date.now() / 1000);

        for (const c of rows || []) {
            let time = Number(c?.time ?? c?.timestamp);
            if (!Number.isFinite(time)) continue;

            if (time > 1e18) time = Math.floor(time / 1_000_000_000);
            else if (time > 1e15) time = Math.floor(time / 1_000_000);
            else if (time > 1e12) time = Math.floor(time / 1_000);
            else time = Math.floor(time);

            const open = Number(c?.open);
            const high = Number(c?.high);
            const low = Number(c?.low);
            const close = Number(c?.close);
            const volume = Number(c?.volume ?? 0);

            if (![open, high, low, close].every(Number.isFinite)) continue;
            if (time < 946684800 || time > nowSec + 7 * 24 * 60 * 60) continue;
            if (open <= 0 || high <= 0 || low <= 0 || close <= 0) continue;

            const candleHigh = Math.max(high, open, low, close);
            const candleLow = Math.min(low, open, high, close);

            seen.set(time, {
                time,
                open: Number(open.toFixed(2)),
                high: Number(candleHigh.toFixed(2)),
                low: Number(candleLow.toFixed(2)),
                close: Number(close.toFixed(2)),
                volume: Number.isFinite(volume) ? Math.max(0, Math.floor(volume)) : 0,
            });
        }

        return [...seen.values()].sort((a, b) => a.time - b.time);
    }, []);

    const updateQuote = useMarketStore((s) => s.updateQuote);
    const liveQuotes = useMarketStore((s) => s.symbols);
    const quote = useMemo(
        () => getLiveQuoteForSymbol(symbol, liveQuotes),
        [symbol, liveQuotes],
    );

    // Track current symbol to prevent stale fetch results from overwriting
    const currentSymbolRef = useRef(symbol);
    currentSymbolRef.current = symbol;

    // AbortController ref for cancelling in-flight candle fetches
    const abortRef = useRef(null);

    // Retry timer for transient candle fetch failures (401 race, 429, network blips)
    const candleRetryRef = useRef(null);

    // Track consecutive failures to avoid flashing error on transient network blips
    const failCountRef = useRef(0);

    useEffect(() => {
        let mounted = true;

        const refreshMarketSession = async () => {
            const applySession = (session) => {
                const state = String(session?.state || '').toLowerCase();
                if (mounted) setIsMarketTrading(state === 'open');
            };

            try {
                const res = await api.get('/market/session');
                if (res?.data) setMarketSessionSnapshot(res.data);
                applySession(res?.data);
            } catch {
                // Fall back to /health for older deployments.
                try {
                    const fallback = await api.get('/health');
                    applySession(fallback?.data?.market_session);
                } catch {
                    // Keep previous market-session state on transient failures.
                }
            }
        };

        refreshMarketSession();
        const id = setInterval(refreshMarketSession, 60_000);
        return () => {
            mounted = false;
            clearInterval(id);
        };
    }, []);

    const fetchQuote = useCallback(async () => {
        if (!symbol || isRateLimited()) return;
        if (!shouldUseRealtimePrices()) {
            const { prefetchSessionClosePrices } = await import('../market/sessionClosePrefetch');
            await prefetchSessionClosePrices([symbol]);
            return;
        }
        try {
            const res = await api.get(`/market/quote/${encodeURIComponent(symbol)}`);
            // Only update if we got a valid quote with a price
            if (res.data && res.data.price != null && !res.data.error) {
                const marketOpen = shouldUseRealtimePrices();
                const src = String(res.data.source || res.data._source || '').toLowerCase();
                const quoteSource = marketOpen
                    ? 'poll'
                    : (src === 'history_snapshot' || src === 'historical' ? 'history_snapshot' : 'eod');
                updateQuote(symbol, res.data, quoteSource);
                if (!marketOpen) {
                    const { setSessionClosePrice } = await import('../market/SessionClosePriceAuthority');
                    setSessionClosePrice(symbol, { ...res.data, _source: quoteSource });
                }
                setHasError(false);
                failCountRef.current = 0;
            }
        } catch {
            // Only show error after 3+ consecutive failures (6+ seconds)
            failCountRef.current += 1;
            if (failCountRef.current >= 3) {
                setHasError(true);
            }
        }
    }, [symbol, updateQuote]);

    const fetchCandles = useCallback(async function fetchCandlesInternal(period = '3mo', interval = '1d', attempt = 0) {
        if (!symbol) return;

        const cacheKey = `${symbol}:${period}:${interval}`;

        // On first attempt, check the module-level cache for an instant render.
        if (attempt === 0) {
            const cached = _candleCache.get(cacheKey);
            const now = Date.now();
            if (cached) {
                const isFresh = now - cached.ts < CANDLE_CACHE_TTL;
                const isIndex = String(symbol || '').trim().startsWith('^');
                const hasEnoughIndexCandles =
                    !isIndex || (cached.candles?.length || 0) >= MIN_INDEX_CANDLES_FOR_CACHE;
                const indexCacheHasVolume =
                    !isIndex || (cached.candles || []).some((c) => Number(c?.volume) > 0);
                // Always show cached candles immediately to avoid blank chart flash
                if (currentSymbolRef.current === symbol) {
                    setCandles(cached.candles);
                    setCandlesSymbol(symbol);
                }
                if (isFresh && hasEnoughIndexCandles && indexCacheHasVolume) {
                    // Cache is fresh — no network call needed
                    setIsLoading(false);
                    return;
                }
                // Stale cache: show old data immediately, then refresh silently in background
                setIsLoading(false);
            }
        }

        // If rate-limited, retry after a short delay instead of leaving chart stale forever.
        if (isRateLimited()) {
            if (attempt <= MAX_CANDLE_RETRIES) {
                if (candleRetryRef.current) clearTimeout(candleRetryRef.current);
                candleRetryRef.current = setTimeout(() => {
                    fetchCandlesInternal(period, interval, attempt + 1);
                }, 800 * (attempt + 1));
            } else {
                setIsLoading(false);
            }
            return;
        }

        // Abort any previous in-flight candle fetch
        if (abortRef.current) {
            abortRef.current.abort();
        }
        const controller = new AbortController();
        abortRef.current = controller;

        const fetchSymbol = symbol;
        // Only show spinner if we have no cached data to display for this symbol
        if (attempt === 0 && !_candleCache.has(cacheKey)) {
            setIsLoading(true);
        } else {
            // Cache exists (possibly stale) — keep isLoading=false so chart stays visible
            setIsLoading(false);
        }

        let queuedRetry = false;
        try {
            const res = await api.get(
                `/market/history/${encodeURIComponent(symbol)}?period=${period}&interval=${interval}`,
                { signal: controller.signal }
            );
            // Only set data if this symbol is still the current one
            if (currentSymbolRef.current === fetchSymbol) {
                if (candleRetryRef.current) {
                    clearTimeout(candleRetryRef.current);
                    candleRetryRef.current = null;
                }
                const normalized = normalizeCandles(res.data?.candles || []);
                // Update module-level cache for future symbol switches
                if (shouldCacheCandles(fetchSymbol, interval, normalized)) {
                    _candleCache.set(cacheKey, { candles: normalized, ts: Date.now() });
                } else {
                    _candleCache.delete(cacheKey);
                }
                setCandles(normalized);
                setCandlesSymbol(fetchSymbol);
            }
        } catch (err) {
            // Don't update state if aborted (symbol changed)
            if (err?.name === 'AbortError' || err?.code === 'ERR_CANCELED') return;

            // Retry transient failures so charts recover after auth/token/bootstrap races.
            if (currentSymbolRef.current === fetchSymbol && attempt < MAX_CANDLE_RETRIES) {
                queuedRetry = true;
                if (candleRetryRef.current) clearTimeout(candleRetryRef.current);
                candleRetryRef.current = setTimeout(() => {
                    fetchCandlesInternal(period, interval, attempt + 1);
                }, 600 * (attempt + 1));
                return;
            }

            // After retries are exhausted, clear candles so chart shows empty state
            // instead of stale data from a previously loaded symbol.
            if (currentSymbolRef.current === fetchSymbol) {
                setHasError(true);
                setCandles([]);
                setCandlesSymbol(null);
            }
        } finally {
            if (currentSymbolRef.current === fetchSymbol && !queuedRetry) {
                setIsLoading(false);
            }
        }
    }, [symbol, normalizeCandles]);

    // On symbol change — clear stale candles immediately and fetch fresh quote.
    // The chart already shows a skeleton while isLoading=true, so clearing is safe.
    // fetchCandles (called by the parent) will restore from cache instantly if available.
    useEffect(() => {
        if (!symbol) return;
        const cachedForSymbol = getLatestCachedCandlesForSymbol(symbol);
        if (cachedForSymbol && cachedForSymbol.length > 0) {
            setCandles(cachedForSymbol);
            setCandlesSymbol(symbol);
            setIsLoading(false);
        } else {
            setCandles([]);
            setCandlesSymbol(null);
            setIsLoading(true);
        }
        setHasError(false);
        fetchQuote();

        // Abort any in-flight candle fetch for the previous symbol
        return () => {
            if (abortRef.current) {
                abortRef.current.abort();
            }
            if (candleRetryRef.current) {
                clearTimeout(candleRetryRef.current);
                candleRetryRef.current = null;
            }
        };
    }, [symbol, fetchQuote]);

    // Poll only during live market — no closed/holiday quote polling (avoids stale/demo drift).
    const intervalRef = useRef(null);
    useEffect(() => {
        if (!symbol || pollInterval <= 0 || !isMarketTrading || !shouldUseRealtimePrices()) {
            return undefined;
        }
        intervalRef.current = setInterval(fetchQuote, pollInterval);
        return () => clearInterval(intervalRef.current);
    }, [symbol, pollInterval, fetchQuote, isMarketTrading]);

    return {
        quote,
        candles,
        candlesSymbol,
        isLoading,
        hasError,
        refetch: fetchQuote,
        fetchCandles,
    };
}
