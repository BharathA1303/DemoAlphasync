/**
 * Session snapshot helpers — avoids circular imports between stores and session manager.
 */
import { mergeSessionWithLocalTruth, computeLocalNseSession } from '../nseSessionCalendar';

const DEFAULT_SNAPSHOT = {
  state: 'closed',
  isOpen: false,
  isClosed: true,
  canPlaceOrders: false,
  isTradingHours: false,
  label: 'Market Closed',
  fetchedAt: 0,
};

let _snapshot = { ...DEFAULT_SNAPSHOT, ...computeLocalNseSession(), canPlaceOrders: false, isTradingHours: false };

export function setMarketSessionSnapshot(session = {}) {
  const merged = mergeSessionWithLocalTruth(session);
  const state = String(merged.state || 'closed').toLowerCase();
  const isOpen = merged.isOpen === true;
  const stateChanged = _snapshot.state !== state;
  _snapshot = {
    state,
    isOpen,
    isClosed: !isOpen,
    canPlaceOrders: isOpen && !!merged.can_place_orders,
    isTradingHours: isOpen,
    label: merged.label || 'Market Closed',
    fetchedAt: stateChanged ? Date.now() : _snapshot.fetchedAt,
    raw: merged,
  };
}

export function getMarketSessionSnapshot() {
  return _snapshot;
}

export function isMarketSessionOpen() {
  return _snapshot.isOpen;
}

export function shouldUseRealtimePrices() {
  return _snapshot.isOpen;
}

/** True when session is not live trading (holiday, weekend, closed, etc.). */
export function isFrozenMarketSession() {
  return !shouldUseRealtimePrices();
}

/** Sources allowed to update display quotes after the session closes. */
export const CLOSED_AUTH_QUOTE_SOURCES = new Set([
  'official_eod_close',
  'eod',
  'frozen',
  'historical',
  'history_snapshot',
  'snapshot',
]);

export function isAuthoritativeClosedQuoteSource(source) {
  return CLOSED_AUTH_QUOTE_SOURCES.has(String(source || '').toLowerCase());
}

/**
 * When market is closed, block poll/live ticks from overwriting frozen EOD prices.
 */
export function shouldApplyQuoteSource(source, existing = {}) {
  if (shouldUseRealtimePrices()) return true;
  const src = String(source || '').toLowerCase();
  if (isAuthoritativeClosedQuoteSource(src)) return true;
  const existingSrc = String(existing._source || existing.source || '').toLowerCase();
  if (isAuthoritativeClosedQuoteSource(existingSrc)) return false;
  const existingPrice = Number(existing.price ?? existing.ltp ?? existing.lp);
  return !(Number.isFinite(existingPrice) && existingPrice > 0);
}

export function isPreMarketState(state = _snapshot.state) {
  return state === 'preopen' || state === 'pre_open';
}

/**
 * Drop stale live/poll quotes from stores when the session closes so closed UI
 * cannot keep showing pre-close ticks until EOD reconciliation completes.
 */
export function purgeNonAuthoritativeClosedQuotes(quotesMap = {}) {
  if (shouldUseRealtimePrices()) return quotesMap;
  const next = {};
  for (const [key, quote] of Object.entries(quotesMap || {})) {
    const src = String(quote?._source || quote?.source || '').toLowerCase();
    if (isAuthoritativeClosedQuoteSource(src)) {
      next[key] = quote;
    }
  }
  return next;
}
