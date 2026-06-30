import { useEffect, useRef } from 'react';
import { usePortfolioStore } from '../store/usePortfolioStore';
import { useMarketStore } from '../store/useMarketStore';
import api, { isRateLimited } from '../services/api';
import { shouldUseRealtimePrices } from '../market/utils/marketSessionUtils';

/**
 * Global polling hook — keeps portfolio P&L updated in real-time.
 *
 * Runs at AppShell level so it's always active regardless of which page
 * the user is on.
 *
 * - When WebSocket is connected: relies on WS ticks (already calls applyLiveQuote),
 *   only polls HTTP every 15s as a safety net.
 * - When WebSocket is disconnected: polls holding prices every 5s via HTTP.
 * - Full portfolio refresh (orders, summary) every 30s always.
 */
export function useLivePortfolio() {
    const intervalRef = useRef(null);
    const refreshTimerRef = useRef(null);

    useEffect(() => {
        // Initial portfolio load to seed the store
        usePortfolioStore.getState().refreshPortfolio();

        const pollHoldingPrices = async () => {
            if (isRateLimited()) return;

            const { holdings, applyLiveQuote } = usePortfolioStore.getState();
            const { updateQuote, wsStatus } = useMarketStore.getState();

            if (!holdings || holdings.length === 0) return;

            // When WS is connected during market hours, WS ticks update P&L in real-time.
            // After close, keep polling so EOD prices replace stale live cache.
            if (wsStatus === 'connected' && shouldUseRealtimePrices()) return;

            const symbols = [...new Set(holdings.map((h) => h.symbol).filter(Boolean))];
            if (symbols.length === 0) return;

            try {
                const res = await api.get(`/market/batch?symbols=${encodeURIComponent(symbols.join(','))}`);
                const quotes = res.data?.quotes || {};

                const source = shouldUseRealtimePrices() ? 'poll' : 'eod';
                Object.entries(quotes).forEach(([symbol, quote]) => {
                    if (quote) {
                        updateQuote(symbol, quote, source);
                        applyLiveQuote(symbol, quote);
                    }
                });
            } catch {
                // Silently ignore — will retry on next interval
            }
        };

        // Poll immediately then every 5s (skips when WS connected)
        pollHoldingPrices();
        intervalRef.current = setInterval(pollHoldingPrices, 5_000);

        // Full portfolio refresh every 30s (always runs — syncs orders, realized P&L, etc.)
        refreshTimerRef.current = setInterval(() => {
            usePortfolioStore.getState().refreshPortfolio();
        }, 30_000);

        return () => {
            if (intervalRef.current) clearInterval(intervalRef.current);
            if (refreshTimerRef.current) clearInterval(refreshTimerRef.current);
        };
    }, []);
}
