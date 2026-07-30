/**
 * Single in-memory equity quote authority (Phase 2 frontend layer).
 */
import { shouldUseRealtimePrices } from '../market/utils/marketSessionUtils';
import { resolveFreshness } from './QuoteFreshnessResolver';
import { quotePriorityEngine } from './QuotePriorityEngine';

const SOURCE_RANK_OPEN = {
  live_ws: 5,
  live: 5,
  market_data_worker: 4,
  poll: 3,
  worker: 3,
  rest: 2,
  eod: 6,
};

const SOURCE_RANK_CLOSED = {
  official_eod_close: 11,
  history_snapshot: 10,
  historical: 10,
  eod: 9,
  frozen: 8,
  snapshot: 8,
  live_ws: 0,
  live: 0,
  poll: 2,
};

const parseTs = (quote) => {
  const raw = quote?.exchange_timestamp ?? quote?.timestamp ?? quote?.last_trade_time;
  if (!raw) return Date.now() / 1000;
  const n = Number(raw);
  if (Number.isFinite(n) && n > 1e9) return n > 1e12 ? n / 1000 : n;
  const d = Date.parse(raw);
  return Number.isFinite(d) ? d / 1000 : Date.now() / 1000;
};

const sourceRank = (source, marketOpen) => {
  const table = marketOpen ? SOURCE_RANK_OPEN : SOURCE_RANK_CLOSED;
  return table[String(source || '').toLowerCase()] ?? 2;
};

const normalizePrice = (quote) => {
  const price = quote?.price ?? quote?.ltp ?? quote?.lp ?? quote?.last_price;
  if (price == null) return quote;
  const n = Number(price);
  return Number.isFinite(n) ? { ...quote, price: n } : quote;
};

function shouldAccept(existing, incoming, source, marketOpen) {
  if (!existing) return true;
  const incTs = parseTs(incoming);
  const exTs = parseTs(existing);
  if (incTs > exTs + 0.001) return true;
  if (incTs < exTs - 0.001) return false;

  const incSeq = Number(incoming.sequence || 0);
  const exSeq = Number(existing.sequence || 0);
  if (incSeq > exSeq) return true;
  if (incSeq < exSeq) return false;

  const incRank = sourceRank(source, marketOpen);
  const exRank = sourceRank(existing.source || existing._source, marketOpen);
  if (incRank > exRank) return true;
  if (incRank < exRank) return false;

  const incPrice = incoming.price ?? incoming.ltp;
  const exPrice = existing.price ?? existing.ltp;
  return incPrice != null && incPrice !== exPrice && incRank >= exRank;
}

class UnifiedQuoteAuthority {
  constructor() {
    this._quotes = new Map();
    this._sequences = new Map();
    this._listeners = new Set();
    this._lastHeartbeat = Date.now();
  }

  subscribe(listener) {
    this._listeners.add(listener);
    return () => this._listeners.delete(listener);
  }

  _notify(symbol, quote) {
    for (const fn of this._listeners) {
      try {
        fn(symbol, quote);
      } catch {
        /* ignore listener errors */
      }
    }
  }

  ingest(symbol, rawQuote = {}, source = 'live') {
    const sym = String(symbol || rawQuote.symbol || '').trim().toUpperCase();
    if (!sym) return null;

    const marketOpen = shouldUseRealtimePrices();
    const existing = this._quotes.get(sym);
    const seq = (this._sequences.get(sym) || 0) + 1;
    const incoming = normalizePrice({
      ...rawQuote,
      symbol: sym,
      source,
      _source: source,
      sequence: rawQuote.sequence ?? seq,
      priority_tier: rawQuote.priority_tier || quotePriorityEngine.getTier(sym),
    });

    if (!shouldAccept(existing, incoming, source, marketOpen)) {
      return null;
    }

    const enriched = {
      ...incoming,
      freshness_state: rawQuote.freshness_state || resolveFreshness(sym, incoming),
      _authorityAt: Date.now(),
    };

    this._sequences.set(sym, seq);
    this._quotes.set(sym, enriched);
    this._lastHeartbeat = Date.now();
    this._notify(sym, enriched);
    return enriched;
  }

  get(symbol) {
    const sym = String(symbol || '').trim().toUpperCase();
    return this._quotes.get(sym) || null;
  }

  getAll() {
    return Object.fromEntries(this._quotes);
  }

  getLastHeartbeat() {
    return this._lastHeartbeat;
  }

  hydrateBatch(quotesMap = {}, source = 'poll') {
    let count = 0;
    for (const [sym, q] of Object.entries(quotesMap || {})) {
      if (this.ingest(sym, q, source)) count += 1;
    }
    return count;
  }
}

export const unifiedQuoteAuthority = new UnifiedQuoteAuthority();
