import { useCallback, useEffect, useRef } from 'react';
import { useMarketStore } from '../store/useMarketStore';
import useUnifiedFuturesStore from '../stores/useUnifiedFuturesStore';
import { isZebuChainSource } from '../components/options/formatZebuValue';
import { getChartSymbol } from '../components/options/constants';
import { optionsWsSend, optionsWsUnsubscribe } from '../components/options/optionsWsBridge';
import { normalizeSymbol } from '../utils/constants';
import api from '../services/api';

function lookupLiveTick(tsym, liveSymbols, futuresQuotes) {
  const key = String(tsym || '').trim().toUpperCase();
  if (!key) return null;
  const candidates = [key];
  if (!key.endsWith('.NS')) candidates.push(`${key}.NS`);
  else candidates.push(key.replace(/\.NS$/, ''));
  for (const c of candidates) {
    const tick = liveSymbols[c];
    if (tick) return tick;
    const fut = futuresQuotes?.[c];
    if (fut) return normalizeFuturesTick(fut);
  }
  return null;
}

function normalizeFuturesTick(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const ltp = Number(raw.ltp ?? raw.price ?? raw.lp);
  return {
    price: Number.isFinite(ltp) ? ltp : undefined,
    ltp: Number.isFinite(ltp) ? ltp : undefined,
    lp: Number.isFinite(ltp) ? ltp : undefined,
    change: raw.change ?? raw.net_change,
    change_percent: raw.change_percent ?? raw.change_pct ?? raw.percent_change,
    changePct: raw.change_pct ?? raw.change_percent ?? raw.percent_change,
    oi: raw.oi,
    oi_change: raw.oi_change ?? raw.oiChange,
    volume: raw.volume,
    bid: raw.bid ?? raw.bid_price,
    ask: raw.ask ?? raw.ask_price,
    bid_price: raw.bid ?? raw.bid_price,
    ask_price: raw.ask ?? raw.ask_price,
    iv: raw.iv,
    delta: raw.delta,
    gamma: raw.gamma,
    theta: raw.theta,
    vega: raw.vega,
  };
}

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function sideChanged(prev, next) {
  if (!prev || !next) return prev !== next;
  return (
    num(prev.ltp) !== num(next.ltp) ||
    num(prev.oi) !== num(next.oi) ||
    num(prev.oiChange) !== num(next.oiChange) ||
    num(prev.volume) !== num(next.volume) ||
    num(prev.bid) !== num(next.bid) ||
    num(prev.ask) !== num(next.ask) ||
    num(prev.iv) !== num(next.iv) ||
    num(prev.delta) !== num(next.delta) ||
    num(prev.gamma) !== num(next.gamma) ||
    num(prev.theta) !== num(next.theta) ||
    num(prev.vega) !== num(next.vega) ||
    num(prev.change) !== num(next.change) ||
    num(prev.changePct) !== num(next.changePct)
  );
}

function patchSideFromTick(data, tick) {
  if (!tick) return data;

  let ltp = num(tick.price ?? tick.ltp ?? tick.lp);

  const next = {
    ...data,
    ...(ltp != null && ltp > 0 ? { ltp } : {}),
    change: tick.change ?? data.change,
    changePct: tick.change_percent ?? tick.changePct ?? data.changePct,
    oi: tick.oi ?? data.oi,
    oiChange: tick.oi_change ?? tick.oiChange ?? data.oiChange,
    volume: tick.volume ?? data.volume,
    bid: tick.bid_price ?? tick.bid ?? data.bid,
    ask: tick.ask_price ?? tick.ask ?? data.ask,
    iv: tick.iv ?? data.iv,
    delta: tick.delta ?? data.delta,
    gamma: tick.gamma ?? data.gamma,
    theta: tick.theta ?? data.theta,
    vega: tick.vega ?? data.vega,
  };

  return sideChanged(data, next) ? next : data;
}

/**
 * WS-first option chain live updates (shared AppShell socket via optionsWsBridge).
 */
export function useOptionsChainLive({
  optionChain,
  setOptionChain,
  setUnderlyingPrice,
  selectedUnderlying,
  streamSymbols,
  chainSource,
}) {
  const liveSymbols = useMarketStore((s) => s.symbols);
  const lastQuoteAt = useMarketStore((s) => s.lastQuoteAt);
  const futuresQuotes = useUnifiedFuturesStore((s) => s.quotes);
  const lastFuturesUpdate = useUnifiedFuturesStore((s) => s._lastQuoteUpdate);
  const chainRef = useRef([]);
  const lastSubscribeKey = useRef('');
  const subscribedRef = useRef([]);

  useEffect(() => {
    if (Array.isArray(optionChain) && optionChain.length) {
      chainRef.current = optionChain;
    }
  }, [optionChain]);

  useEffect(() => {
    chainRef.current = [];
  }, [selectedUnderlying, chainSource]);

  useEffect(() => {
    if (!isZebuChainSource(chainSource)) return;

    const syms = [
      ...(streamSymbols || []),
      getChartSymbol(selectedUnderlying),
    ]
      .map((s) => String(s || '').trim().toUpperCase())
      .filter(Boolean)
      .filter((s, i, arr) => arr.indexOf(s) === i);

    const normalized = syms.map((s) => normalizeSymbol(s) || s);
    const key = normalized.sort().join(',');
    if (!key || key === lastSubscribeKey.current) return;

    const prev = subscribedRef.current;
    if (prev.length) optionsWsUnsubscribe(prev);

    lastSubscribeKey.current = key;
    subscribedRef.current = normalized;
    optionsWsSend(normalized);

    api
      .post('/options/promote-hot', { symbols: normalized })
      .catch(() => {
        /* backend may be older; WS still works at WARM */
      });
  }, [streamSymbols, selectedUnderlying, chainSource]);

  useEffect(() => {
    return () => {
      if (subscribedRef.current.length) {
        optionsWsUnsubscribe(subscribedRef.current);
        subscribedRef.current = [];
      }
      lastSubscribeKey.current = '';
    };
  }, []);

  useEffect(() => {
    if (!isZebuChainSource(chainSource) || !chainRef.current.length) return;

    const spotSym = getChartSymbol(selectedUnderlying);
    const spotQuote =
      lookupLiveTick(spotSym, liveSymbols, futuresQuotes)
      || lookupLiveTick(selectedUnderlying, liveSymbols, futuresQuotes);
    if (spotQuote) {
      const spot = num(spotQuote.price ?? spotQuote.ltp ?? spotQuote.lp);
      if (spot != null && spot > 0) setUnderlyingPrice(spot);
    }

    let anyChanged = false;
    const next = chainRef.current.map((row) => {
      let ce = row.ce;
      let pe = row.pe;
      const ceTsym = String(ce?.tsym || '').toUpperCase();
      const peTsym = String(pe?.tsym || '').toUpperCase();
      if (ceTsym) {
        const patched = patchSideFromTick(ce, lookupLiveTick(ceTsym, liveSymbols, futuresQuotes));
        if (patched !== ce) {
          ce = patched;
          anyChanged = true;
        }
      }
      if (peTsym) {
        const patched = patchSideFromTick(pe, lookupLiveTick(peTsym, liveSymbols, futuresQuotes));
        if (patched !== pe) {
          pe = patched;
          anyChanged = true;
        }
      }
      if (ce === row.ce && pe === row.pe) return row;
      return { ...row, ce, pe };
    });

    if (anyChanged) {
      chainRef.current = next;
      setOptionChain(next);
    }
  }, [liveSymbols, lastQuoteAt, futuresQuotes, lastFuturesUpdate, chainSource, selectedUnderlying, setOptionChain, setUnderlyingPrice]);

}

/** OI/volume reconciliation via batch quotes — not full chain rebuild. */
export const OPTIONS_OI_RECONCILE_MS = 45_000;

export async function reconcileChainOiFromBatch(streamSymbols, chain, mergeFn) {
  const syms = (streamSymbols || [])
    .map((s) => String(s || '').trim().toUpperCase())
    .filter(Boolean);
  if (!syms.length || !chain?.length) return chain;

  try {
    const res = await api.get('/market/batch', {
      params: { symbols: syms.join(',') },
    });
    const quotes = res.data?.quotes || res.data || {};
    let changed = false;
    const next = chain.map((row) => {
      const patchLeg = (leg) => {
        if (!leg?.tsym) return leg;
        const tick =
          quotes[leg.tsym] ||
          quotes[`${leg.tsym}.NS`] ||
          quotes[leg.tsym.replace(/\.NS$/, '')];
        if (!tick) return leg;
        const updated = patchSideFromTick(leg, tick);
        if (updated !== leg) changed = true;
        return updated;
      };
      const ce = patchLeg(row.ce);
      const pe = patchLeg(row.pe);
      if (ce === row.ce && pe === row.pe) return row;
      return { ...row, ce, pe };
    });
    if (!changed) return chain;
    return next;
  } catch {
    return chain;
  }
}
