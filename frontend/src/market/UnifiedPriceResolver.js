/**
 * Session-aware unified price resolver for all equity/index UI surfaces.
 */
import { symbolAliases } from '../utils/liveQuote';
import {
  getMarketSessionSnapshot,
  shouldUseRealtimePrices,
  isAuthoritativeClosedQuoteSource,
} from './utils/marketSessionUtils';
import { getSessionClosePrice } from './SessionClosePriceAuthority';

const DEBUG = import.meta.env?.DEV;

const toFiniteNumber = (value) => {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

const pickPrice = (quote) =>
  toFiniteNumber(quote?.price ?? quote?.ltp ?? quote?.lp ?? quote?.last_price ?? quote?.lastPrice);

function findQuoteForSymbol(symbol, quotesMap = {}) {
  if (!symbol || !quotesMap) return null;
  for (const key of symbolAliases(symbol)) {
    const q = quotesMap[key];
    if (q && pickPrice(q) != null) return q;
  }
  return null;
}

function sourcePriority(source, marketOpen) {
  const src = String(source || '').toLowerCase();
  if (!marketOpen) {
    // Chart-aligned intraday close wins over stale snapshots when market is closed.
    if (src === 'history_snapshot' || src === 'historical') return 10;
    if (src === 'official_eod_close') return 7;
    if (src === 'eod' || src === 'frozen' || src === 'snapshot') return 5;
    if (src === 'poll') return 2;
    if (src === 'live' || src === 'live_ws' || src === 'stale_live_ws') return 0;
    return 1;
  }
  if (src === 'official_eod_close') return 2;
  if (src === 'eod') return 2;
  if (src === 'poll') return 3;
  if (src === 'live' || src === 'live_ws') return 5;
  if (src === 'stale_live_ws') return 0;
  if (src === 'historical' || src === 'history_snapshot') return 1;
  return 1;
}

/**
 * Resolve best quote for a symbol from multiple maps.
 */
export function resolveSymbolPrice(symbol, options = {}) {
  const {
    liveQuotes = {},
    watchlistPrices = {},
    eodQuotes = {},
    candleClose = null,
  } = options;

  const marketOpen = shouldUseRealtimePrices();

  if (!marketOpen) {
    const sessionRow = getSessionClosePrice(symbol);
    if (sessionRow) {
      const price = pickPrice(sessionRow);
      const prevClose = toFiniteNumber(sessionRow.prev_close);
      let change = toFiniteNumber(sessionRow.change);
      let changePercent = toFiniteNumber(sessionRow.change_percent);
      if (change == null && price != null && prevClose != null && prevClose > 0) {
        change = Number((price - prevClose).toFixed(2));
      }
      if (changePercent == null && change != null && prevClose != null && prevClose > 0) {
        changePercent = Number(((change / prevClose) * 100).toFixed(2));
      }
      return {
        symbol,
        price,
        change,
        change_percent: changePercent,
        quote: sessionRow,
        priceSource: 'eod',
      };
    }
    if (candleClose != null && candleClose > 0) {
      const prevFromMaps =
        toFiniteNumber(findQuoteForSymbol(symbol, eodQuotes)?.prev_close) ??
        toFiniteNumber(findQuoteForSymbol(symbol, watchlistPrices)?.prev_close) ??
        toFiniteNumber(findQuoteForSymbol(symbol, liveQuotes)?.prev_close);
      let change = null;
      let changePercent = null;
      if (prevFromMaps != null && prevFromMaps > 0) {
        change = Number((candleClose - prevFromMaps).toFixed(2));
        changePercent = Number(((change / prevFromMaps) * 100).toFixed(2));
      }
      return {
        symbol,
        price: candleClose,
        change,
        change_percent: changePercent,
        quote: { price: candleClose, _source: 'history_snapshot', prev_close: prevFromMaps },
        priceSource: 'eod',
      };
    }
  }

  const candidates = [];

  const live = findQuoteForSymbol(symbol, liveQuotes);
  if (live) {
    const liveSource = live._source || live.source || 'live';
    if (marketOpen || isAuthoritativeClosedQuoteSource(liveSource)) {
      candidates.push({ quote: live, source: liveSource });
    }
  }

  const wl = findQuoteForSymbol(symbol, watchlistPrices);
  if (wl) {
    const wlSource = wl._source || wl.source || 'poll';
    if (marketOpen || isAuthoritativeClosedQuoteSource(wlSource)) {
      candidates.push({ quote: wl, source: wlSource });
    }
  }

  const eod = findQuoteForSymbol(symbol, eodQuotes);
  if (eod) {
    const eodSource = eod._source || eod.source || 'eod';
    if (marketOpen || isAuthoritativeClosedQuoteSource(eodSource)) {
      candidates.push({ quote: eod, source: eodSource });
    }
  }

  if (candleClose != null && candleClose > 0) {
    candidates.push({
      quote: { price: candleClose, _source: 'historical' },
      source: 'historical',
    });
  }

  if (candidates.length === 0) {
    return { symbol, price: null, change: null, change_percent: null, quote: null, priceSource: 'fallback' };
  }

  candidates.sort((a, b) => sourcePriority(b.source, marketOpen) - sourcePriority(a.source, marketOpen));
  const best = candidates[0];
  const price = pickPrice(best.quote);
  const prevClose = toFiniteNumber(best.quote?.prev_close ?? best.quote?.prevClose);
  let change = toFiniteNumber(best.quote?.change ?? best.quote?.net_change);
  let changePercent = toFiniteNumber(
    best.quote?.change_percent ?? best.quote?.changePercent ?? best.quote?.pct_change,
  );

  if (change == null && price != null && prevClose != null && prevClose > 0) {
    change = Number((price - prevClose).toFixed(2));
  }
  if (changePercent == null && change != null && prevClose != null && prevClose > 0) {
    changePercent = Number(((change / prevClose) * 100).toFixed(2));
  }

  const priceSource = marketOpen
    ? (best.source === 'live' ? 'realtime' : best.source)
    : (best.source === 'eod' || best.source === 'historical' ? 'eod' : best.source === 'poll' ? 'eod' : 'fallback');

  if (DEBUG && price != null) {
    console.debug('[PRICE_SOURCE]', symbol, priceSource, price);
  }

  return {
    symbol,
    price,
    change,
    change_percent: changePercent,
    quote: best.quote,
    priceSource,
  };
}

/**
 * Merge watchlist poll map + market store for display (session-aware).
 */
export function mergeResolvedWatchlistPrices(watchlistPrices = {}, liveQuotes = {}, eodQuotes = {}) {
  const marketOpen = shouldUseRealtimePrices();
  const merged = { ...(watchlistPrices || {}) };
  const symbols = new Set([
    ...Object.keys(watchlistPrices || {}),
    ...(marketOpen ? Object.keys(liveQuotes || {}) : []),
    ...Object.keys(eodQuotes || {}),
  ]);

  for (const sym of symbols) {
    const resolved = resolveSymbolPrice(sym, {
      liveQuotes: marketOpen ? liveQuotes : {},
      watchlistPrices,
      eodQuotes,
    });
    if (resolved.price == null || !resolved.quote) continue;

    const patch = {
      ...resolved.quote,
      price: resolved.price,
      change: resolved.change,
      change_percent: resolved.change_percent,
      _source: resolved.priceSource === 'realtime' ? 'live' : (resolved.quote?._source || 'history_snapshot'),
      _resolvedAt: Date.now(),
    };

    for (const key of symbolAliases(sym)) {
      merged[key] = patch;
    }
  }

  return merged;
}

/**
 * Apply resolved fields onto a ticker/index row object.
 */
export function resolveTickerItem(item, liveQuotes = {}, eodQuotes = {}) {
  if (!item) return item;
  const resolved = resolveSymbolPrice(item.symbol, { liveQuotes, eodQuotes });
  if (resolved.price == null) {
    // After close, never show stale baked-in ticker row prices (same fake value daily).
    if (!shouldUseRealtimePrices()) {
      return {
        ...item,
        _priceSource: 'pending_eod',
      };
    }
    return item;
  }

  return {
    ...item,
    price: resolved.price,
    change: resolved.change ?? item.change,
    change_percent: resolved.change_percent ?? item.change_percent,
    _priceSource: resolved.priceSource,
  };
}

export function getResolverSessionLabel() {
  const s = getMarketSessionSnapshot();
  return s.isOpen ? 'open' : s.state || 'closed';
}
