import { useEffect, useRef, useCallback } from 'react';
import { useMarketStore } from '../store/useMarketStore';
import { usePortfolioStore } from '../store/usePortfolioStore';
import { useWatchlistStore } from '../stores/useWatchlistStore';
import { useZeroLossStore } from '../stores/useZeroLossStore';
import api from '../services/api';
import { registerFuturesWsSend } from '../services/futuresWsBridge';
import { registerOptionsWsSend } from '../components/options/optionsWsBridge';
import useUnifiedFuturesStore from '../stores/useUnifiedFuturesStore';
import { useFuturesWatchlistStore } from '../stores/useFuturesWatchlistStore';
import {
    WS_MAX_BACKOFF_MS,
    WS_HEARTBEAT_MS,
    normalizeSymbol,
    isCommoditySymbol,
    isDerivativeContractSymbol,
    COMMODITY_SYMBOLS,
} from '../utils/constants';
import { marketSessionManager } from '../market/MarketSessionManager';
import { shouldUseRealtimePrices } from '../market/utils/marketSessionUtils';
import { notifyLiveTickReceived, scheduleWsIdleReconciliation } from '../market/EODReconciliationEngine';
import { quoteSyncEngine } from '../market-v2/QuoteSynchronizationEngine';
import { TICKER_HOT_SYMBOLS } from '../market-v2/tickerHotSymbols';

/**
 * WebSocket hook for real-time market data.
 *
 * FIX: Uses refs for all callbacks to prevent the connect function from being
 * recreated on every render, which was causing a WebSocket reconnect storm
 * ("WebSocket is closed before the connection is established").
 */
export function useWebSocket() {
    const wsRef = useRef(null);
    const statusRef = useRef('disconnected');
    const backoffRef = useRef(1000);
    const failedAttemptsRef = useRef(0);
    const reconnectTimer = useRef(null);
    const heartbeatTimer = useRef(null);
    const messageQueue = useRef([]);
    const mountedRef = useRef(true);
    const portfolioRefreshTimer = useRef(null);

    // Store selectors — these are stable Zustand selectors
    const updateQuote = useMarketStore((s) => s.updateQuote);
    const setWsStatus = useMarketStore((s) => s.setWsStatus);
    const selectedSymbol = useMarketStore((s) => s.selectedSymbol);
    const holdings = usePortfolioStore((s) => s.holdings);
    const applyLiveQuote = usePortfolioStore((s) => s.applyLiveQuote);
    const refreshPortfolio = usePortfolioStore((s) => s.refreshPortfolio);
    const watchlists = useWatchlistStore((s) => s.watchlists);
    const activeWatchlistId = useWatchlistStore((s) => s.activeId);
    const updateWatchlistPrices = useWatchlistStore((s) => s.updatePrices);
    const handleZeroLoss = useZeroLossStore((s) => s.handleWsMessage);

    // ── Use refs for ALL callback dependencies to keep `connect` stable ─────
    const callbacksRef = useRef({});
    callbacksRef.current = {
        updateQuote, setWsStatus, applyLiveQuote,
        refreshPortfolio, handleZeroLoss, updateWatchlistPrices,
    };

    const trackedRef = useRef([]);
    // Update tracked symbols whenever dependencies change
    useEffect(() => {
        const activeWatchlist = watchlists.find((w) => w.id === activeWatchlistId);
        const watchlistSymbols = (activeWatchlist?.items || []).map((item) => item.symbol);
        const holdingSymbols = (holdings || []).map((h) => h.symbol);

        const symbols = [
            ...(selectedSymbol ? [selectedSymbol] : []),
            ...watchlistSymbols,
            ...holdingSymbols,
            ...TICKER_HOT_SYMBOLS,
        ]
            .map(normalizeSymbol)
            .filter(Boolean)
            .filter((value, index, arr) => arr.indexOf(value) === index);

        trackedRef.current = symbols;
        quoteSyncEngine.registerActiveSymbols({
            selectedSymbol,
            watchlistSymbols,
            holdings: holdingSymbols,
        });
    }, [selectedSymbol, watchlists, activeWatchlistId, holdings]);

    const applyIncomingQuote = useCallback((symbol, data = {}) => {
        if (!symbol) return;
        const normalizedSymbol = normalizeSymbol(symbol);
        // Use live session snapshot (not a stale ref) — equity ticks only when market is open.
        const symKey = normalizedSymbol || symbol;
        if (
            !shouldUseRealtimePrices() &&
            !isCommoditySymbol(symKey) &&
            !isDerivativeContractSymbol(symKey)
        ) {
            return;
        }
        const resolvedPrice = Number(data.price ?? data.lp ?? data.ltp ?? data.last_price);
        const rawUpper = String(symbol || '').toUpperCase().trim();
        const contractUpper = String(data.contract_symbol || '').toUpperCase().trim();
        const commodityRoot =
            [...COMMODITY_SYMBOLS]
                .sort((a, b) => b.length - a.length)
                .find((root) => rawUpper.startsWith(root) || contractUpper.startsWith(root)) || null;

        const quoteData = { ...data };
        if (Number.isFinite(resolvedPrice) && resolvedPrice > 0) {
            quoteData.price = resolvedPrice;
        }

        const key = normalizedSymbol || symbol;
        const resolved = quoteSyncEngine.ingestFromWs(key, quoteData);
        if (!resolved) return;

        const liveSource = quoteData.source || 'live';
        callbacksRef.current.updateQuote(key, quoteData, liveSource);

        if (normalizedSymbol && normalizedSymbol !== symbol) {
            quoteSyncEngine.ingestFromWs(symbol, quoteData);
            callbacksRef.current.updateQuote(symbol, quoteData, liveSource);
        }
        if (commodityRoot) {
            quoteSyncEngine.ingestFromWs(commodityRoot, quoteData);
            callbacksRef.current.updateQuote(commodityRoot, quoteData, liveSource);
        }

        notifyLiveTickReceived();
        if (!shouldUseRealtimePrices()) {
            scheduleWsIdleReconciliation(120_000);
        }
    }, []); // Stable — uses callbacksRef

    const send = useCallback((payload) => {
        const msg = JSON.stringify(payload);
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(msg);
        } else {
            messageQueue.current.push(msg);
        }
    }, []);

    // ── Connect — stable function, no recreations ──────────────────────────
    const connectRef = useRef(null);
    connectRef.current = () => {
        if (!mountedRef.current) return;
        if (wsRef.current?.readyState === WebSocket.OPEN ||
            wsRef.current?.readyState === WebSocket.CONNECTING) return;

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        const token = localStorage.getItem('alphasync_token');
        const clientId = `market_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
        const url = token
            ? `${protocol}//${host}/ws/${clientId}?token=${encodeURIComponent(token)}`
            : `${protocol}//${host}/ws/${clientId}`;

        statusRef.current = 'connecting';
        callbacksRef.current.setWsStatus('connecting');

        const ws = new WebSocket(url);
        wsRef.current = ws;

        ws.onopen = () => {
            if (!mountedRef.current) { ws.close(); return; }
            backoffRef.current = 1000;
            failedAttemptsRef.current = 0;
            statusRef.current = 'connected';
            callbacksRef.current.setWsStatus('connected');

            // Start heartbeat
            if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);
            heartbeatTimer.current = setInterval(() => {
                if (wsRef.current?.readyState === WebSocket.OPEN) {
                    wsRef.current.send(JSON.stringify({ type: 'ping' }));
                }
            }, WS_HEARTBEAT_MS);

            // Flush queued messages
            while (messageQueue.current.length > 0 && wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send(messageQueue.current.shift());
            }

            // Subscribe to tracked symbols + hydrate authority from batch snapshot
            const symbols = trackedRef.current;
            if (symbols.length > 0) {
                const uniqueSyms = [...new Set(symbols)];
                const commodities = uniqueSyms.filter(s => isCommoditySymbol(s));
                console.log(
                    `[WS CONNECTED] subscribing ${uniqueSyms.length} symbols ` +
                    `(${commodities.length} commodities: ${commodities.slice(0, 8).join(', ')})`
                );
                ws.send(JSON.stringify({ type: 'subscribe', symbols: uniqueSyms }));
                quoteSyncEngine.hydrateOnReconnect(uniqueSyms);
            }
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'quote' && data.symbol) {
                    const { type, channel, ...quoteData } = data;
                    if (isCommoditySymbol(data.symbol)) {
                        console.log(
                            `[MCX CLIENT RECEIVED] ${data.symbol} ltp=${quoteData.price} ` +
                            `source=${quoteData.source} bid=${quoteData.bid_price} ` +
                            `ask=${quoteData.ask_price} exchange=${quoteData.exchange}`
                        );
                    }
                    applyIncomingQuote(data.symbol, quoteData);
                }
                if (data.type === 'price_update' && data.data?.symbol) {
                    const { type: _t, channel: _c, ...legacyData } = data.data;
                    applyIncomingQuote(data.data.symbol, legacyData);
                }
                if (data.channel === 'zeroloss') {
                    callbacksRef.current.handleZeroLoss(data);
                }
                if (data.channel === 'orders' || data.channel === 'portfolio' || data.type === 'portfolio_update') {
                    if (portfolioRefreshTimer.current) clearTimeout(portfolioRefreshTimer.current);
                    portfolioRefreshTimer.current = setTimeout(() => callbacksRef.current.refreshPortfolio(), 500);
                }
                // Futures terminal — isolated store updates only (does not touch equity market store)
                if (data.type === 'futures_quote' && data.contract_symbol) {
                    const sym = data.contract_symbol;
                    const quote = data.data || {};
                    const normalizedQuote = {
                        ...quote,
                        ltp: quote.ltp ?? quote.price ?? quote.lp,
                        change_pct: quote.change_pct ?? quote.change_percent ?? quote.percent_change,
                        change_percent: quote.change_percent ?? quote.change_pct ?? quote.percent_change,
                    };
                    const store = useUnifiedFuturesStore.getState();
                    store.updateQuote(sym, normalizedQuote);
                    useFuturesWatchlistStore.getState().updatePrices({ [sym]: normalizedQuote });
                    // Mirror NFO/BFO ticks into market store for options chain live updates.
                    applyIncomingQuote(sym, normalizedQuote);
                    if (statusRef.current === 'connected') {
                        store.setLastHeartbeat(Date.now());
                    }
                    if (store.positions.some((p) => Number(p.quantity) !== 0)) {
                        store.recalculateLivePnl();
                    }
                }
                if (
                    data.channel === 'futures_orders' ||
                    data.type === 'futures_order_placed' ||
                    data.type === 'futures_order_filled' ||
                    data.type === 'futures_order_cancelled'
                ) {
                    Promise.allSettled([
                        api.get('/futures/orders'),
                        api.get('/futures/positions'),
                    ]).then(([ordersRes, posRes]) => {
                        const store = useUnifiedFuturesStore.getState();
                        if (ordersRes.status === 'fulfilled') {
                            store.setOrders(ordersRes.value.data?.orders ?? []);
                        }
                        if (posRes.status === 'fulfilled') {
                            store.setPositions(posRes.value.data?.positions ?? []);
                        }
                    });
                }
            } catch { /* malformed JSON */ }
        };

        ws.onerror = () => {
            statusRef.current = 'error';
            callbacksRef.current.setWsStatus('error');
        };

        ws.onclose = () => {
            if (!mountedRef.current) return;
            statusRef.current = 'disconnected';
            callbacksRef.current.setWsStatus('disconnected');
            if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);

            failedAttemptsRef.current += 1;

            // Exponential backoff reconnect
            const delay = Math.min(backoffRef.current, WS_MAX_BACKOFF_MS);
            backoffRef.current = Math.min(backoffRef.current * 2, WS_MAX_BACKOFF_MS);
            reconnectTimer.current = setTimeout(() => connectRef.current?.(), delay);
        };
    };

    // Register send for futures module (shared socket — no second WS)
    useEffect(() => {
        registerFuturesWsSend(send);
        registerOptionsWsSend(send);
        return () => {
            registerFuturesWsSend(null);
            registerOptionsWsSend(null);
        };
    }, [send]);

    // ── Mount: connect once, clean up on unmount ────────────────────────────
    useEffect(() => {
        mountedRef.current = true;
        connectRef.current?.();
        return () => {
            mountedRef.current = false;
            if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
            if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);
            if (portfolioRefreshTimer.current) clearTimeout(portfolioRefreshTimer.current);
            wsRef.current?.close();
        };
    }, []); // eslint-disable-line react-hooks/exhaustive-deps — intentionally stable

    // ── Re-subscribe when tracked symbols change ────────────────────────────
    useEffect(() => {
        const symbols = trackedRef.current;
        if (symbols.length > 0 && wsRef.current?.readyState === WebSocket.OPEN) {
            send({ type: 'subscribe', symbols: [...new Set(symbols)] });
        }
    }, [selectedSymbol, watchlists, activeWatchlistId, holdings, send]);

    const subscribe = useCallback((symbols) => {
        const commodities = (symbols || []).filter(s => isCommoditySymbol(s));
        if (commodities.length > 0) {
            console.log(`[MCX FRONTEND SUBSCRIBE] sending ${commodities.length} commodity symbols:`, commodities);
        }
        send({ type: 'subscribe', symbols });
    }, [send]);
    const unsubscribe = useCallback((symbols) => send({ type: 'unsubscribe', symbols }), [send]);

    const status = useMarketStore((s) => s.wsStatus);
    return { status, subscribe, unsubscribe };
}
