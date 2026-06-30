/**
 * Prefetch chart-aligned closed-session prices for many symbols at once (no per-click).
 */
import api, { isRateLimited } from '../services/api';
import { normalizeSymbol } from '../utils/constants';
import { shouldUseRealtimePrices } from './utils/marketSessionUtils';
import {
  getSessionClosePrice,
  hydrateSessionCloseFromBatch,
  restoreSessionCloseFromStorage,
} from './SessionClosePriceAuthority';

const BATCH_SIZE = 40;
let _inflight = null;

function uniqueSymbols(symbols = []) {
  return [...new Set(
    symbols
      .map((s) => normalizeSymbol(s) || String(s || '').trim().toUpperCase())
      .filter(Boolean),
  )];
}

/**
 * Batch-load session closes for watchlist + ticker symbols when market is closed.
 */
export async function prefetchSessionClosePrices(symbols = []) {
  if (shouldUseRealtimePrices()) return;

  restoreSessionCloseFromStorage();

  const list = uniqueSymbols(symbols);
  const missing = list.filter((sym) => !getSessionClosePrice(sym));
  if (missing.length === 0) return;

  if (_inflight) {
    await _inflight;
    const stillMissing = list.filter((sym) => !getSessionClosePrice(sym));
    if (stillMissing.length === 0) return;
  }

  _inflight = (async () => {
    for (let i = 0; i < missing.length; i += BATCH_SIZE) {
      if (isRateLimited()) break;
      const chunk = missing.slice(i, i + BATCH_SIZE);
      if (chunk.length === 0) continue;
      try {
        const res = await api.get('/market/batch', {
          params: { symbols: chunk.join(',') },
        });
        hydrateSessionCloseFromBatch(res.data?.quotes || {}, res.data || null);
      } catch {
        /* keep partial cache */
      }
    }
  })().finally(() => {
    _inflight = null;
  });

  return _inflight;
}

export function collectWatchlistSymbols(watchlists = []) {
  const out = [];
  for (const wl of watchlists || []) {
    for (const item of wl?.items || []) {
      if (item?.symbol) out.push(item.symbol);
    }
  }
  return out;
}
