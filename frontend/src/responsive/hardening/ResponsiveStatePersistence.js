/**
 * Persists responsive UI state across navigation / refresh / rotation.
 */

const KEYS = {
  mobileTab: 'alphasync:responsive:mobile-tab',
  orderSnap: 'alphasync:responsive:order-snap',
  watchlistScroll: 'alphasync:responsive:watchlist-scroll',
  terminalMode: 'alphasync:responsive:terminal-mode',
};

let ctxRef = null;
let cleanup = null;

function read(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key, value) {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

export function initResponsiveStatePersistence(responsiveContext) {
  ctxRef = responsiveContext;
  if (!ctxRef?.setMobileTradingTab) return () => {};

  const savedTab = read(KEYS.mobileTab);
  if (savedTab && ['chart', 'watchlist', 'order'].includes(savedTab)) {
    ctxRef.setMobileTradingTab(savedTab);
  }

  const persistTab = () => {
    if (ctxRef?.mobileTradingTab) write(KEYS.mobileTab, ctxRef.mobileTradingTab);
  };

  const interval = setInterval(persistTab, 2000);
  window.addEventListener('beforeunload', persistTab);

  cleanup = () => {
    clearInterval(interval);
    window.removeEventListener('beforeunload', persistTab);
    persistTab();
  };

  return cleanup;
}

export function persistOrderSnapState(state) {
  write(KEYS.orderSnap, state);
}

export function readOrderSnapState() {
  return read(KEYS.orderSnap);
}

export function persistWatchlistScroll(top) {
  write(KEYS.watchlistScroll, String(top));
}

export function readWatchlistScroll() {
  const v = read(KEYS.watchlistScroll);
  return v ? Number(v) : 0;
}

export function persistTerminalMode(mode) {
  write(KEYS.terminalMode, mode);
}

export function readTerminalMode() {
  return read(KEYS.terminalMode);
}

export function disposeResponsiveStatePersistence() {
  cleanup?.();
  cleanup = null;
  ctxRef = null;
}
