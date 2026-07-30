/**
 * Single closed-market price authority — chart-aligned session closes per symbol.
 * Active only when market is closed; open market uses live WS/poll unchanged.
 */
import { symbolAliases } from '../utils/liveQuote';
import { shouldUseRealtimePrices, isAuthoritativeClosedQuoteSource } from './utils/marketSessionUtils';

const _cache = {};
const _listeners = new Set();
const STORAGE_KEY = 'alphasync_session_close_v1';

const CLOSED_BATCH_SOURCES = new Set([
  'history_snapshot',
  'historical',
  'frozen',
  'official_eod_close',
  'eod',
  'snapshot',
  'last_price',
]);

function tradeDateKey() {
  try {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Kolkata',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(new Date());
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

function persistSessionCloseStorage() {
  if (shouldUseRealtimePrices()) return;
  try {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ date: tradeDateKey(), quotes: _cache }),
    );
  } catch {
    /* quota / private mode */
  }
}

/** Instant restore on reload — same trade date only. */
export function restoreSessionCloseFromStorage() {
  if (shouldUseRealtimePrices()) return;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (parsed?.date !== tradeDateKey() || !parsed?.quotes) return;
    let changed = false;
    for (const [key, row] of Object.entries(parsed.quotes)) {
      if (!row || pickPrice(row) == null) continue;
      if (!_cache[key]) changed = true;
      _cache[key] = row;
    }
    if (changed) notify();
  } catch {
    /* ignore */
  }
}

const toFiniteNumber = (value) => {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

const pickPrice = (quote) =>
  toFiniteNumber(quote?.price ?? quote?.ltp ?? quote?.lp ?? quote?.last_price ?? quote?.lastPrice);

function notify() {
  _listeners.forEach((fn) => {
    try {
      fn();
    } catch {
      /* ignore */
    }
  });
}

export function subscribeSessionClosePrices(listener) {
  _listeners.add(listener);
  return () => _listeners.delete(listener);
}

/** Read-only snapshot for resolvers (symbol-keyed). */
export function getSessionCloseCache() {
  return _cache;
}

export function getSessionClosePrice(symbol) {
  if (!symbol || shouldUseRealtimePrices()) return null;
  for (const key of symbolAliases(symbol)) {
    const row = _cache[key];
    if (row && pickPrice(row) != null) return row;
  }
  return null;
}

/**
 * Register chart-aligned close for a symbol (from last candle or authoritative batch).
 */
export function setSessionClosePrice(symbol, quote = {}) {
  if (!symbol || shouldUseRealtimePrices()) return;

  const price = pickPrice(quote);
  if (price == null || price <= 0) return;

  const src = String(quote._source || quote.source || 'history_snapshot').toLowerCase();
  if (!isAuthoritativeClosedQuoteSource(src) && src !== 'historical') return;

  for (const key of symbolAliases(symbol)) {
    const prev = _cache[key];
    if (
      prev?._source === 'history_snapshot' &&
      src !== 'history_snapshot' &&
      src !== 'historical'
    ) {
      return;
    }
  }

  const prevClose = toFiniteNumber(quote.prev_close ?? quote.prevClose);
  let change = toFiniteNumber(quote.change ?? quote.net_change);
  let changePercent = toFiniteNumber(
    quote.change_percent ?? quote.changePercent ?? quote.pct_change,
  );

  if (change == null && prevClose != null && prevClose > 0) {
    change = Number((price - prevClose).toFixed(2));
  }
  if (changePercent == null && change != null && prevClose != null && prevClose > 0) {
    changePercent = Number(((change / prevClose) * 100).toFixed(2));
  }

  const entry = {
    price: Number(price.toFixed(2)),
    change,
    change_percent: changePercent,
    prev_close: prevClose,
    _source: src === 'historical' ? 'history_snapshot' : src,
    _sessionCloseAt: Date.now(),
  };

  let changed = false;
  for (const key of symbolAliases(symbol)) {
    const prev = _cache[key];
    if (!prev || prev.price !== entry.price || prev._source !== entry._source) {
      changed = true;
    }
    _cache[key] = entry;
  }
  if (changed) {
    persistSessionCloseStorage();
    notify();
  }
}

/** Ingest closed-market batch quotes (backend tags source as frozen / history_snapshot). */
export function hydrateSessionCloseFromBatch(quotes = {}, batchMeta = null) {
  if (shouldUseRealtimePrices()) return;

  const closedEnvelope =
    batchMeta?.frozen === true || batchMeta?.official === true;

  for (const [sym, raw] of Object.entries(quotes || {})) {
    if (!raw || typeof raw !== 'object') continue;
    const src = String(raw.source || raw._source || '').toLowerCase();
    if (CLOSED_BATCH_SOURCES.has(src) || (closedEnvelope && pickPrice(raw) != null)) {
      setSessionClosePrice(sym, {
        ...raw,
        _source: src === 'history_snapshot' || src === 'historical' ? src : 'history_snapshot',
      });
    }
  }
}

export function setSessionCloseFromCandle(symbol, close, meta = {}) {
  if (close == null || close <= 0) return;
  setSessionClosePrice(symbol, {
    price: close,
    prev_close: meta.prev_close,
    change: meta.change,
    change_percent: meta.change_percent,
    _source: 'history_snapshot',
  });
}

export function clearSessionClosePrices() {
  if (Object.keys(_cache).length === 0) return;
  for (const key of Object.keys(_cache)) delete _cache[key];
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  notify();
}

export function hasSessionClosePrice(symbol) {
  return getSessionClosePrice(symbol) != null;
}
