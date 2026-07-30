/**
 * Post-market EOD reconciliation — syncs authoritative REST quotes into all frontend stores.
 * Does NOT touch Redis, WebSocket ingestion, or backend pipelines.
 */
import api from '../services/api';
import { normalizeSymbol } from '../utils/constants';
import { getMarketSessionSnapshot } from './utils/marketSessionUtils';

const DEBUG = import.meta.env?.DEV;
const BATCH_SIZE = 40;
const DEBOUNCE_MS = 400;

let _inflight = null;
let _debounceTimer = null;
let _lastRunAt = 0;
const _eodCache = {};

export function getEODQuoteCache() {
  return _eodCache;
}

async function collectTrackedSymbols() {
  const symbols = new Set();

  const [
    { useMarketStore },
    { useWatchlistStore },
    { usePortfolioStore },
    { useMarketIndicesStore },
  ] = await Promise.all([
    import('../store/useMarketStore'),
    import('../stores/useWatchlistStore'),
    import('../store/usePortfolioStore'),
    import('../stores/useMarketIndicesStore'),
  ]);

  const { symbols: storeSyms, selectedSymbol, watchlist } = useMarketStore.getState();
  if (selectedSymbol) symbols.add(selectedSymbol);
  (watchlist || []).forEach((s) => symbols.add(s));
  Object.keys(storeSyms || {}).forEach((s) => symbols.add(s));

  const { watchlists, activeId } = useWatchlistStore.getState();
  const active = watchlists?.find((w) => w.id === activeId);
  (active?.items || []).forEach((item) => {
    if (item?.symbol) symbols.add(item.symbol);
  });

  const { holdings } = usePortfolioStore.getState();
  (holdings || []).forEach((h) => {
    if (h?.symbol) symbols.add(h.symbol);
  });

  const { tickerItems, indices } = useMarketIndicesStore.getState();
  (tickerItems || []).forEach((i) => i?.symbol && symbols.add(i.symbol));
  (indices || []).forEach((i) => i?.symbol && symbols.add(i.symbol));

  return [...symbols]
    .map((s) => normalizeSymbol(s) || s)
    .filter(Boolean)
    .filter((v, i, arr) => arr.indexOf(v) === i);
}

async function fetchBatchQuotes(symbolList) {
  const results = {};
  let batchMeta = null;
  for (let i = 0; i < symbolList.length; i += BATCH_SIZE) {
    const chunk = symbolList.slice(i, i + BATCH_SIZE);
    if (chunk.length === 0) continue;
    try {
      const res = await api.get(`/market/batch?symbols=${encodeURIComponent(chunk.join(','))}`);
      const quotes = res.data?.quotes ?? {};
      Object.assign(results, quotes);
      if (!batchMeta && res.data) {
        batchMeta = {
          source: res.data.source,
          market_state: res.data.market_state,
          frozen: res.data.frozen,
          official: res.data.official,
        };
      }
    } catch (e) {
      if (DEBUG) console.warn('[RECONCILIATION] batch chunk failed', e?.message);
    }
  }
  if (batchMeta && DEBUG) {
    console.info('[RECONCILIATION] batch metadata', batchMeta);
  }
  return { quotes: results, batchMeta };
}

function isOfficialBackendQuote(q, batchMeta = null) {
  if (!q || typeof q !== 'object') return false;
  if (batchMeta?.official === true && batchMeta?.frozen === true) return true;
  if (batchMeta?.official === true) return true;
  const src = String(q.source || q._source || '').toLowerCase();
  if (src === 'official_eod_close') return true;
  if (src === 'history_snapshot') return true;
  if (q.official === true) return true;
  return false;
}

function stampEODQuotes(quotes, batchMeta = null) {
  const now = Date.now();
  const stamped = {};
  for (const [sym, q] of Object.entries(quotes || {})) {
    if (!q || typeof q !== 'object') continue;
    const price = Number(q.price ?? q.ltp ?? q.lp);
    if (!Number.isFinite(price) || price <= 0) continue;

    const src = String(q.source || q._source || '').toLowerCase();
    const authoritative = isOfficialBackendQuote(q, batchMeta);

    if (!authoritative) {
      if (DEBUG) {
        console.warn(
          '[RECONCILIATION] skipped non-authoritative closed quote',
          sym,
          src,
        );
      }
      continue;
    }

    const resolvedSource =
      src === 'official_eod_close'
        ? 'official_eod_close'
        : (src === 'history_snapshot' ? 'history_snapshot' : 'eod');

    stamped[sym] = {
      ...q,
      price,
      _source: resolvedSource,
      source: resolvedSource,
      official: true,
      frozen: true,
      _updatedAt: now,
      _reconciledAt: now,
    };
    _eodCache[sym] = stamped[sym];
    if (DEBUG) console.info('[RECONCILIATION] closed-market quote synced', sym, price, src);
  }
  return stamped;
}

async function applyToStores(stampedQuotes) {
  if (!stampedQuotes || Object.keys(stampedQuotes).length === 0) return;

  const { hydrateSessionCloseFromBatch } = await import('./SessionClosePriceAuthority');
  hydrateSessionCloseFromBatch(stampedQuotes, { official: true, frozen: true });

  const { useMarketStore } = await import('../store/useMarketStore');
  const { useWatchlistStore } = await import('../stores/useWatchlistStore');
  const { usePortfolioStore } = await import('../store/usePortfolioStore');

  useMarketStore.getState().batchUpdateQuotes(stampedQuotes, 'eod');
  useWatchlistStore.getState().updatePrices(stampedQuotes);

  const { applyLiveQuote } = usePortfolioStore.getState();
  Object.entries(stampedQuotes).forEach(([symbol, quote]) => {
    applyLiveQuote(symbol, quote);
  });
}

async function reconcileTickerAndIndices() {
  try {
    const { useMarketIndicesStore } = await import('../stores/useMarketIndicesStore');
    const store = useMarketIndicesStore.getState();

    const [tickerRes, indicesRes] = await Promise.allSettled([
      api.get('/market/ticker'),
      api.get('/market/indices'),
    ]);

    if (tickerRes.status === 'fulfilled') {
      const payload = tickerRes.value?.data || {};
      const items = payload.items || [];
      if (items.length > 0) {
        const indices = items.filter((i) => i.kind === 'index');
        const stamped = getEODQuoteCache();
        const { resolveTickerItem } = await import('./UnifiedPriceResolver');
        const mergedItems = Object.keys(stamped).length
          ? items.map((item) => resolveTickerItem(item, stamped, stamped))
          : items;
        useMarketIndicesStore.setState({
          tickerItems: mergedItems,
          indices: indices.map((idx) =>
            Object.keys(stamped).length
              ? resolveTickerItem(idx, stamped, stamped)
              : idx,
          ),
          _tickerFailures: 0,
        });
      }
    } else if (indicesRes.status === 'fulfilled') {
      const indices = indicesRes.value?.data?.indices || [];
      if (indices.length > 0) {
        useMarketIndicesStore.setState({ indices });
      }
    }

    const stamped = getEODQuoteCache();
    const { tickerItems } = useMarketIndicesStore.getState();
    if (Object.keys(stamped).length > 0 && tickerItems?.length > 0) {
      const { resolveTickerItem } = await import('./UnifiedPriceResolver');
      const merged = tickerItems.map((item) => resolveTickerItem(item, stamped, stamped));
      useMarketIndicesStore.setState({ tickerItems: merged });
    }
  } catch (e) {
    if (DEBUG) console.warn('[RECONCILIATION] ticker/indices failed', e?.message);
  }
}

async function executeReconciliation(reason) {
  const snap = getMarketSessionSnapshot();
  if (snap.isOpen && reason !== 'manual') {
    if (DEBUG) console.debug('[RECONCILIATION] skipped — market open');
    return;
  }

  const symbols = await collectTrackedSymbols();
  if (symbols.length === 0) {
    await reconcileTickerAndIndices();
    return;
  }

  if (DEBUG) console.info('[RECONCILIATION] start', reason, symbols.length, 'symbols');

  const { quotes, batchMeta } = await fetchBatchQuotes(symbols);
  const stamped = stampEODQuotes(quotes, batchMeta);
  await applyToStores(stamped);
  await reconcileTickerAndIndices();

  _lastRunAt = Date.now();
  if (DEBUG) console.info('[RECONCILIATION] complete', Object.keys(stamped).length, 'quotes');
}

/**
 * Debounced reconciliation entry point.
 */
export function runEODReconciliation({ reason = 'manual' } = {}) {
  if (_debounceTimer) clearTimeout(_debounceTimer);
  _debounceTimer = setTimeout(() => {
    _debounceTimer = null;
    if (_inflight) return _inflight;
    _inflight = executeReconciliation(reason).finally(() => {
      _inflight = null;
    });
    return _inflight;
  }, DEBOUNCE_MS);
}

/** WS idle — no live ticks for extended period while market closed */
let _wsIdleTimer = null;

export function notifyLiveTickReceived() {
  if (_wsIdleTimer) {
    clearTimeout(_wsIdleTimer);
    _wsIdleTimer = null;
  }
}

export function scheduleWsIdleReconciliation(idleMs = 90_000) {
  if (_wsIdleTimer) clearTimeout(_wsIdleTimer);
  const snap = getMarketSessionSnapshot();
  if (snap.isOpen) return;

  _wsIdleTimer = setTimeout(() => {
    _wsIdleTimer = null;
    const age = Date.now() - _lastRunAt;
    if (age > 60_000) {
      runEODReconciliation({ reason: 'ws_idle' });
    }
  }, idleMs);
}
