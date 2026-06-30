/** Shared live-quote helpers — one source for header, watchlist, and chart. */
import { mergeResolvedWatchlistPrices } from '../market/UnifiedPriceResolver';
import { resolveSymbolPrice } from '../market/UnifiedPriceResolver';
import { getEODQuoteCache } from '../market/EODReconciliationEngine';
import { getSessionCloseCache } from '../market/SessionClosePriceAuthority';
import { shouldUseRealtimePrices } from '../market/utils/marketSessionUtils';

export const symbolAliases = (symbol = '') => {
    const raw = String(symbol || '').trim().toUpperCase();
    if (!raw) return [];
    const withSuffix = raw.startsWith('^') || raw.endsWith('.NS') || raw.endsWith('.BO')
        ? raw
        : `${raw}.NS`;
    const withoutSuffix = withSuffix.replace(/\.(NS|BO)$/i, '');
    return [...new Set([raw, withSuffix, withoutSuffix])];
};

const toFiniteNumber = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
};

/**
 * Resolve the best live quote for a symbol from the market store map.
 */
export function getLiveQuoteForSymbol(symbol, quotesMap = {}) {
    if (!shouldUseRealtimePrices()) {
        const resolved = resolveSymbolPrice(symbol, {
            liveQuotes: quotesMap,
            eodQuotes: getEODQuoteCache(),
        });
        if (resolved.price != null && resolved.quote) {
            return resolved.quote;
        }
    }
    for (const key of symbolAliases(symbol)) {
        const quote = quotesMap[key];
        const price = toFiniteNumber(quote?.price);
        if (price != null && price > 0) return quote;
    }
    return null;
}

/**
 * Merge HTTP watchlist poll prices with market-store quotes (session-aware).
 * Delegates to unified resolver when available.
 */
export function mergeWatchlistPrices(watchlistPrices = {}, liveQuotes = {}) {
    if (!shouldUseRealtimePrices()) {
        const sessionCache = getSessionCloseCache();
        // Closed session: never surface stale watchlist poll rows — session cache only.
        return mergeResolvedWatchlistPrices({}, {}, sessionCache);
    }
    return mergeResolvedWatchlistPrices(watchlistPrices, liveQuotes, getEODQuoteCache());
}

/**
 * Apply live price to a quote object (recompute change vs prev_close).
 */
export function buildQuoteWithLivePrice(baseQuote, livePrice) {
    const nextPrice = toFiniteNumber(livePrice);
    if (nextPrice == null || nextPrice <= 0) return baseQuote || {};

    const prevClose = toFiniteNumber(baseQuote?.prev_close);
    const hasPrevClose = prevClose != null && prevClose > 0;
    const nextChange = hasPrevClose ? Number((nextPrice - prevClose).toFixed(2)) : baseQuote?.change ?? null;
    const nextChangePercent = hasPrevClose
        ? Number((((nextPrice - prevClose) / prevClose) * 100).toFixed(2))
        : baseQuote?.change_percent ?? null;

    return {
        ...(baseQuote || {}),
        price: Number(nextPrice.toFixed(2)),
        change: nextChange,
        change_percent: nextChangePercent,
    };
}
