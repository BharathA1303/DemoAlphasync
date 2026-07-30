/**
 * Central market session authority — single poll, transition detection, reconciliation triggers.
 */
import api from '../services/api';
import { setMarketSessionSnapshot, getMarketSessionSnapshot } from './utils/marketSessionUtils';

const POLL_OPEN_MS = 30_000;
const POLL_CLOSED_MS = 60_000;
const DEBUG = import.meta.env?.DEV;

let _intervalId = null;
let _started = false;
let _lastState = null;
const _listeners = new Set();

function logSession(state, prev) {
  if (!DEBUG) return;
  console.info('[MARKET_SESSION]', state, prev != null ? `(was ${prev})` : '');
}

function notifyListeners(snapshot) {
  _listeners.forEach((fn) => {
    try {
      fn(snapshot);
    } catch (e) {
      console.warn('[MARKET_SESSION] listener error', e);
    }
  });
}

async function fetchSession() {
  try {
    const res = await api.get('/market/session');
    return res?.data ?? {};
  } catch {
    try {
      const fallback = await api.get('/health');
      return fallback?.data?.market_session ?? {};
    } catch {
      return null;
    }
  }
}

async function refreshSession() {
  const data = await fetchSession();
  if (!data) return getMarketSessionSnapshot();

  const prev = _lastState;
  const state = String(data.state || 'closed').toLowerCase();
  _lastState = state;
  setMarketSessionSnapshot(data);

  if (prev !== state) {
    logSession(state, prev);
    notifyListeners(getMarketSessionSnapshot());

    if (state === 'open' && prev !== 'open') {
      const { clearSessionClosePrices } = await import('./SessionClosePriceAuthority');
      clearSessionClosePrices();
    }

    if (state !== 'open' && prev === 'open') {
      const { purgeNonAuthoritativeClosedQuotes } = await import('./utils/marketSessionUtils');
      const { useMarketStore } = await import('../store/useMarketStore');
      const { useWatchlistStore } = await import('../stores/useWatchlistStore');

      useMarketStore.setState((s) => ({
        symbols: purgeNonAuthoritativeClosedQuotes(s.symbols),
      }));
      useWatchlistStore.setState((s) => ({
        prices: purgeNonAuthoritativeClosedQuotes(s.prices),
      }));

      const { prefetchSessionClosePrices, collectWatchlistSymbols } = await import('./sessionClosePrefetch');
      const { TICKER_HOT_SYMBOLS } = await import('../market-v2/tickerHotSymbols');
      await prefetchSessionClosePrices([
        ...collectWatchlistSymbols(useWatchlistStore.getState().watchlists),
        ...TICKER_HOT_SYMBOLS,
      ]);

      const { runEODReconciliation } = await import('./EODReconciliationEngine');
      runEODReconciliation({ reason: 'session_closed' });
      const { useMarketIndicesStore } = await import('../stores/useMarketIndicesStore');
      setTimeout(() => {
        useMarketIndicesStore.getState().fetchTicker();
        useMarketIndicesStore.getState().fetchIndices();
      }, 2500);
    }
  }

  return getMarketSessionSnapshot();
}

function schedulePoll() {
  if (_intervalId) clearInterval(_intervalId);
  const snap = getMarketSessionSnapshot();
  const ms = snap.isOpen ? POLL_OPEN_MS : POLL_CLOSED_MS;
  _intervalId = setInterval(() => refreshSession(), ms);
}

export const marketSessionManager = {
  start() {
    if (_started) return;
    _started = true;
    import('./utils/marketSessionUtils').then(({ setMarketSessionSnapshot }) => {
      import('./nseSessionCalendar').then(({ computeLocalNseSession }) => {
        setMarketSessionSnapshot(computeLocalNseSession());
      });
    });
    refreshSession().then(() => {
      schedulePoll();
      if (!getMarketSessionSnapshot().isOpen) {
        import('./SessionClosePriceAuthority').then(({ restoreSessionCloseFromStorage }) => {
          restoreSessionCloseFromStorage();
        });
        import('./sessionClosePrefetch').then(async ({ prefetchSessionClosePrices, collectWatchlistSymbols }) => {
          const { useWatchlistStore } = await import('../stores/useWatchlistStore');
          const { TICKER_HOT_SYMBOLS } = await import('../market-v2/tickerHotSymbols');
          const wls = useWatchlistStore.getState().watchlists;
          await prefetchSessionClosePrices([
            ...collectWatchlistSymbols(wls),
            ...TICKER_HOT_SYMBOLS,
          ]);
        });
        import('./EODReconciliationEngine').then(({ runEODReconciliation }) => {
          runEODReconciliation({ reason: 'startup_closed' });
        });
      }
    });
  },

  stop() {
    _started = false;
    if (_intervalId) {
      clearInterval(_intervalId);
      _intervalId = null;
    }
  },

  refresh: refreshSession,

  subscribe(listener) {
    _listeners.add(listener);
    // Defer initial delivery (avoids React #185 sync storms) but still sync imperative
    // listeners (e.g. useWebSocket gates) with the current session on subscribe.
    const snapshot = getMarketSessionSnapshot();
    queueMicrotask(() => {
      if (!_listeners.has(listener)) return;
      try {
        listener(snapshot);
      } catch (e) {
        console.warn('[MARKET_SESSION] listener error', e);
      }
    });
    return () => _listeners.delete(listener);
  },

  getSnapshot: getMarketSessionSnapshot,
};

export default marketSessionManager;
