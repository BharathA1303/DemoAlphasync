/**
 * Routes authoritative quotes into existing stores (no UI redesign).
 */
import api from '../services/api';
import { useMarketStore } from '../store/useMarketStore';
import { useWatchlistStore } from '../stores/useWatchlistStore';
import { usePortfolioStore } from '../store/usePortfolioStore';
import { symbolAliases } from '../utils/liveQuote';
import { unifiedQuoteAuthority } from './UnifiedQuoteAuthority';
import { TICKER_HOT_SYMBOLS } from './tickerHotSymbols';
import { quotePriorityEngine } from './QuotePriorityEngine';
import { shouldUseRealtimePrices } from '../market/utils/marketSessionUtils';

let _hydrating = false;

function buildWatchlistPatch(symbol, quote) {
  const patch = {};
  for (const key of symbolAliases(symbol)) {
    patch[key] = quote;
  }
  return patch;
}

class QuoteSynchronizationEngine {
  constructor() {
    unifiedQuoteAuthority.subscribe((symbol, quote) => {
      this._applyToStores(symbol, quote);
    });
  }

  _applyToStores(symbol, quote) {
    const source = quote._source || quote.source || 'live';
    useMarketStore.getState().updateQuote(symbol, quote, source);
    usePortfolioStore.getState().applyLiveQuote(symbol, quote);

    const patch = buildWatchlistPatch(symbol, quote);
    if (Object.keys(patch).length > 0) {
      useWatchlistStore.getState().updatePrices(patch);
    }
  }

  ingestFromWs(symbol, data) {
    return unifiedQuoteAuthority.ingest(symbol, data, 'live');
  }

  ingestFromPoll(symbol, data) {
    return unifiedQuoteAuthority.ingest(symbol, data, 'poll');
  }

  registerActiveSymbols({ selectedSymbol, watchlistSymbols = [], holdings = [] } = {}) {
    if (selectedSymbol) quotePriorityEngine.registerHot(selectedSymbol);
    for (const sym of watchlistSymbols) quotePriorityEngine.registerWarm(sym);
    for (const sym of holdings) quotePriorityEngine.registerWarm(sym);
    for (const sym of TICKER_HOT_SYMBOLS) quotePriorityEngine.registerHot(sym);
  }

  async hydrateOnReconnect(symbols = []) {
    if (_hydrating) return;
    const unique = [...new Set(
      [...symbols, ...TICKER_HOT_SYMBOLS]
        .map((s) => String(s || '').trim())
        .filter(Boolean),
    )];
    if (unique.length === 0) return;

    _hydrating = true;
    try {
      const res = await api.get('/market/batch', {
        params: { symbols: unique.join(',') },
      });
      const quotes = res.data?.quotes || res.data || {};
      const marketOpen = shouldUseRealtimePrices();
      const closedOfficial =
        !marketOpen && res.data?.official === true && res.data?.frozen === true;
      if (!marketOpen) {
        const { hydrateSessionCloseFromBatch } = await import('../market/SessionClosePriceAuthority');
        hydrateSessionCloseFromBatch(quotes, res.data);
      }
      for (const [sym, q] of Object.entries(quotes)) {
        const src = String(q?.source || q?._source || '').toLowerCase();
        const ingestSource = marketOpen
          ? 'poll'
          : (src === 'history_snapshot' || src === 'official_eod_close'
            ? src
            : (closedOfficial ? 'history_snapshot' : 'eod'));
        unifiedQuoteAuthority.ingest(sym, q, ingestSource);
      }
    } catch {
      /* keep last authority on failure */
    } finally {
      _hydrating = false;
    }
  }
}

export const quoteSyncEngine = new QuoteSynchronizationEngine();
