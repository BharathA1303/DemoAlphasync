import { useEffect, useState, useMemo, useRef } from 'react';
import useUnifiedFuturesStore from '../../stores/useUnifiedFuturesStore';
import { useMarketStore } from '../../store/useMarketStore';
import { resolveFuturesAnalytics } from '../services/FuturesAnalyticsResolver';
import api from '../../services/api';
import { useMarketSession } from '../../hooks/useMarketSession';
import { shouldUseRealtimePrices } from '../../market/utils/marketSessionUtils';

/**
 * Central hook — reads existing futures store quotes + fetches real Zebu spot.
 * Spot price is augmented with live market store quotes for broker-level speed:
 *   - Market store live quotes (WebSocket-driven, sub-second) used when available
 *   - REST API polled at 5s (open) / 60s (closed) as fallback + consistency sync
 */
export function useFuturesAnalytics() {
  const { marketOpen, marketState } = useMarketSession();
  const sessionKey = `${marketOpen}:${marketState}`;

  const selectedUnderlying = useUnifiedFuturesStore((s) => s.contracts.selectedUnderlying);
  const selectedContract = useUnifiedFuturesStore((s) => s.contracts.selectedContract);
  const bySymbol = useUnifiedFuturesStore((s) => s.contracts.bySymbol);
  const byUnderlying = useUnifiedFuturesStore((s) => s.contracts.byUnderlying);
  const quotes = useUnifiedFuturesStore((s) => s.quotes);
  const loading = useUnifiedFuturesStore((s) => s.contracts.loading);
  const lastQuoteUpdate = useUnifiedFuturesStore((s) => s._lastQuoteUpdate);

  // Live quotes from main market WebSocket — instant updates when underlying is subscribed
  const liveQuotes = useMarketStore((s) => s.symbols);

  const [spotQuote, setSpotQuote] = useState(null);
  const [spotLoading, setSpotLoading] = useState(false);
  const spotInflight = useRef(null);
  const spotLoadedFor = useRef(null);

  useEffect(() => {
    if (!selectedUnderlying) {
      setSpotQuote(null);
      spotLoadedFor.current = null;
      return;
    }

    let cancelled = false;
    const underlying = selectedUnderlying;
    const isNewUnderlying = spotLoadedFor.current !== underlying;
    if (isNewUnderlying) setSpotLoading(true);

    const fetchSpot = async () => {
      if (spotInflight.current) return spotInflight.current;
      spotInflight.current = (async () => {
        try {
          const res = await api.get(`/futures/spot/${encodeURIComponent(underlying)}`);
          if (!cancelled) {
            setSpotQuote(res.data ?? null);
            spotLoadedFor.current = underlying;
          }
        } catch {
          if (!cancelled) setSpotQuote(null);
        } finally {
          if (!cancelled) setSpotLoading(false);
          spotInflight.current = null;
        }
      })();
      return spotInflight.current;
    };

    fetchSpot();
    // 5s during market hours for near-real-time REST sync; 60s when closed (no moving prices)
    const pollMs = shouldUseRealtimePrices() ? 5_000 : 60_000;
    const interval = setInterval(fetchSpot, pollMs);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [selectedUnderlying, sessionKey]);

  // Merge WebSocket live price into spotQuote for broker-level spot price speed.
  // When the underlying is subscribed to the main market WebSocket (e.g. it's in
  // the user's watchlist), we get tick-by-tick LTP without waiting for the REST poll.
  const mergedSpotQuote = useMemo(() => {
    if (!spotQuote || !selectedUnderlying || !shouldUseRealtimePrices()) return spotQuote;

    const under = selectedUnderlying.toUpperCase();
    const live = liveQuotes[under] || liveQuotes[`${under}.NS`] || null;
    if (!live) return spotQuote;

    const livePrice = Number(live.price ?? live.ltp ?? live.lp);
    if (!Number.isFinite(livePrice) || livePrice <= 0) return spotQuote;

    // Only override with live quote when it's strictly newer than the REST snapshot.
    // This prevents a stale market-store entry from clobbering a fresher REST fetch.
    const liveTs = Number(live._updatedAt ?? live.timestamp ?? 0);
    const restTs = Number(spotQuote._updatedAt ?? spotQuote.timestamp ?? 0);
    if (liveTs > 0 && restTs > 0 && liveTs <= restTs) return spotQuote;

    return {
      ...spotQuote,
      ltp: livePrice,
      lp: livePrice,
      price: livePrice,
      change: live.change ?? spotQuote.change ?? null,
      change_pct: live.change_percent ?? live.change_pct ?? spotQuote.change_pct ?? null,
      change_percent: live.change_percent ?? spotQuote.change_percent ?? null,
      prev_close: live.prev_close ?? spotQuote.prev_close ?? null,
    };
  }, [spotQuote, selectedUnderlying, liveQuotes, lastQuoteUpdate]);

  const analytics = useMemo(
    () =>
      resolveFuturesAnalytics({
        underlying: selectedUnderlying,
        selectedContract,
        bySymbol,
        byUnderlying,
        quotes,
        spotQuote: mergedSpotQuote,
      }),
    [
      selectedUnderlying,
      selectedContract,
      bySymbol,
      byUnderlying,
      quotes,
      mergedSpotQuote,
      lastQuoteUpdate,
      sessionKey,
    ],
  );

  return {
    analytics,
    spotLoading,
    contractsLoading: loading,
  };
}

export default useFuturesAnalytics;
