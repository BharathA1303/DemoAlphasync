/**
 * Options workstation — compact Zebu chain (left), chart (center), details (right),
 * floating order panel (terminal-style).
 */
import { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import toast from 'react-hot-toast';
import ErrorBoundary from '../components/ErrorBoundary';
import ZebuLiveChart from '../components/trading/ZebuLiveChart';
import OptionChainCompact from '../components/trading/OptionChainCompact';
import ResizablePanel from '../components/layout/ResizablePanel';
import {
  OptionsChartHeader,
  OptionsBottomDock,
  OptionsRightSidebar,
  OptionsOrderPanel,
  transformChainRow,
  mergeChainRows,
  getLotSize,
  getChartSymbol,
  formatExpiryChip,
  buildDisplaySymbol,
} from '../components/options';
import { isZebuChainSource } from '../components/options/formatZebuValue';
import { useOptionsStore } from '../stores/useOptionsStore';
import {
  useOptionsChainLive,
} from '../hooks/useOptionsChainLive';
import { useBreakpoint } from '../hooks/useBreakpoint';
import { useResponsive } from '../responsive/hooks/useResponsive';
import { BREAKPOINTS } from '../responsive/constants/breakpoints';
import { computeOptionsAnalytics } from '../utils/optionsAnalytics';
import { CHART_PERIODS } from '../utils/constants';
import { cn } from '../utils/cn';
import api from '../services/api';
import {
  hydrateSnapshot,
  cancelHydration,
  getSnapshot,
  patchRows,
  isProgressiveEnabled,
  isProgressiveDebug,
} from '../core/hydration';

const ORDER_FLOAT_WIDTH = 312;
const SNAPSHOT_STRIKES = 18;
const SNAPSHOT_STALE_MS = 1500;
const RECONCILE_DELAY_MS = 150;
const OPTION_CHART_CACHE_TTL_MS = 60_000;
const optionChartCache = new Map();

export default function OptionsPage() {
  const progressiveEnabled = isProgressiveEnabled('options');
  const progressiveDebug = isProgressiveDebug();
  const { closePosition, placeOptionOrder, positions, orders } = useOptionsStore();
  const { isMobile } = useBreakpoint();
  const { width } = useResponsive();
  const showRightSidebar = width >= BREAKPOINTS.lg;

  const [selectedUnderlying, setSelectedUnderlying] = useState('NIFTY');
  const [selectedExpiry, setSelectedExpiry] = useState(null);
  const [expiryList, setExpiryList] = useState([]);
  const [underlyingPrice, setUnderlyingPrice] = useState(0);
  const [optionChain, setOptionChain] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [chainSource, setChainSource] = useState('');
  const [streamSymbols, setStreamSymbols] = useState([]);

  const [selectedStrike, setSelectedStrike] = useState(null);
  const [optionType, setOptionType] = useState('CE');
  const [side, setSide] = useState('BUY');
  const [orderType, setOrderType] = useState('MARKET');
  const [lots, setLots] = useState(1);
  const [limitPrice, setLimitPrice] = useState('');
  const [premium, setPremium] = useState('');
  const [selectedGreeks, setSelectedGreeks] = useState({ delta: 0, iv: 0 });
  const [orderSheetOpen, setOrderSheetOpen] = useState(false);
  const [chartInterval, setChartInterval] = useState('5m');
  const [chainPanelVisible, setChainPanelVisible] = useState(true);
  const [rightPanelVisible, setRightPanelVisible] = useState(true);
  const [orderPanelVisible, setOrderPanelVisible] = useState(false);
  const [bottomCollapsed, setBottomCollapsed] = useState(false);
  const [scrollToStrike, setScrollToStrike] = useState(null);

  const skipNextExpirySnapshot = useRef(false);

  const orderPanelDrag = useRef({ active: false, sx: 0, sy: 0, ox: 0, oy: 0 });
  const getDefaultOrderPos = useCallback(
    () => ({ x: Math.max(16, window.innerWidth - ORDER_FLOAT_WIDTH - 24), y: 72 }),
    [],
  );
  const [orderPanelPos, setOrderPanelPos] = useState(() => getDefaultOrderPos());

  const selectedRowForChart = useMemo(
    () => optionChain.find((r) => r.strike === selectedStrike),
    [optionChain, selectedStrike],
  );
  const chartLegForType = selectedRowForChart
    ? optionType === 'CE'
      ? selectedRowForChart.ce
      : selectedRowForChart.pe
    : null;

  /** Selected option contract OHLC (Zebu tsym) — not underlying index. */
  const chartContractSymbol = useMemo(() => {
    const tsym = String(chartLegForType?.tsym || '').trim().toUpperCase();
    return tsym || null;
  }, [chartLegForType?.tsym]);

  const [chartCandles, setChartCandles] = useState([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState(null);
  const [chartHydrationReady, setChartHydrationReady] = useState(() => !progressiveEnabled);

  useOptionsChainLive({
    optionChain,
    setOptionChain,
    setUnderlyingPrice,
    selectedUnderlying,
    streamSymbols,
    chainSource,
  });

  useEffect(() => {
    if (progressiveEnabled && !chartHydrationReady) return;
    const tsym = chartContractSymbol;
    const token = String(chartLegForType?.token || '').trim();
    if (!tsym || !token) {
      setChartCandles([]);
      setChartError(null);
      setChartLoading(false);
      return;
    }

    const cfg = CHART_PERIODS[chartInterval] || CHART_PERIODS['5m'];
    const interval = String(cfg?.interval || '5m').toLowerCase();
    const period = String(cfg?.period || '1mo');
    const exchange = selectedUnderlying === 'SENSEX' ? 'BFO' : 'NFO';
    const cacheKey = `${exchange}:${tsym}:${token}:${period}:${interval}`;
    const cached = optionChartCache.get(cacheKey);
    if (cached && Date.now() - cached.ts < OPTION_CHART_CACHE_TTL_MS) {
      setChartCandles(cached.candles);
      setChartError(null);
      setChartLoading(false);
      return;
    }

    let cancelled = false;
    setChartLoading(true);
    setChartError(null);

    api
      .get('/options/history', {
        params: { tsym, token, exchange, period, interval },
        timeout: 18_000,
      })
      .then((res) => {
        if (cancelled) return;
        const rows = res?.data?.candles || [];
        const candles = Array.isArray(rows) ? rows : [];
        optionChartCache.set(cacheKey, { ts: Date.now(), candles });
        setChartCandles(candles);
      })
      .catch((e) => {
        if (cancelled) return;
        const detail = e?.response?.data?.detail;
        setChartCandles([]);
        setChartError(detail || 'Failed to load option candles.');
      })
      .finally(() => {
        if (!cancelled) setChartLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    chartContractSymbol,
    chartInterval,
    chartLegForType?.token,
    selectedUnderlying,
    progressiveEnabled,
    chartHydrationReady,
  ]);

  const logHydration = useCallback((...args) => {
    if (progressiveDebug) console.debug('[options-hydration]', ...args);
  }, [progressiveDebug]);

  useEffect(() => {
    if (!progressiveDebug) return;
    logHydration('progressive enabled', progressiveEnabled);
    if (!progressiveEnabled) logHydration('fallback mode active');
  }, [progressiveDebug, progressiveEnabled, logHydration]);

  const mergeSide = useCallback((nextSide, prevSide) => {
    if (!nextSide) return prevSide || nextSide;
    if (!prevSide) return nextSide;

    const nextLtp = Number(nextSide.ltp);
    const prevLtp = Number(prevSide.ltp);
    const merged = { ...prevSide, ...nextSide };

    if (!(Number.isFinite(nextLtp) && nextLtp > 0) && Number.isFinite(prevLtp) && prevLtp > 0) {
      merged.ltp = prevLtp;
      if (!merged.bid && prevSide.bid) merged.bid = prevSide.bid;
      if (!merged.ask && prevSide.ask) merged.ask = prevSide.ask;
      if (!merged.oi && prevSide.oi) merged.oi = prevSide.oi;
      if (merged.change == null && prevSide.change != null) merged.change = prevSide.change;
      if (merged.changePct == null && prevSide.changePct != null) merged.changePct = prevSide.changePct;
    }

    return merged;
  }, []);

  const isOptionRowEqual = useCallback((prev, next) => {
    if (prev === next) return true;
    if (!prev || !next) return false;
    if (prev.strike !== next.strike) return false;

    const keys = ['ltp', 'bid', 'ask', 'iv', 'delta', 'gamma', 'theta', 'vega', 'oi', 'oiChange', 'volume', 'change', 'changePct', 'tsym', 'token'];
    const sideEqual = (a, b) => {
      if (a === b) return true;
      if (!a || !b) return false;
      return keys.every((k) => {
        const av = a[k];
        const bv = b[k];
        if (typeof av === 'number' || typeof bv === 'number') return Number(av) === Number(bv);
        return av === bv;
      });
    };

    return sideEqual(prev.ce, next.ce) && sideEqual(prev.pe, next.pe);
  }, []);

  const patchChainRows = useCallback((rows, { silent = false } = {}) => {
    if (!Array.isArray(rows)) return;
    setOptionChain((prev) => {
      const patched = patchRows(prev, rows, {
        keyFn: (row) => row?.strike,
        mergeFn: (prevRow, nextRow) => ({
          ...nextRow,
          ce: mergeSide(nextRow.ce, prevRow?.ce),
          pe: mergeSide(nextRow.pe, prevRow?.pe),
        }),
        equalFn: isOptionRowEqual,
      });

      if (progressiveDebug && Array.isArray(prev) && Array.isArray(patched)) {
        const prevByStrike = new Map(prev.map((row) => [row?.strike, row]));
        let changed = 0;
        for (const row of patched) {
          const old = prevByStrike.get(row?.strike);
          if (old !== row) changed += 1;
        }
        logHydration('chain patch', { changed, total: patched.length, silent });
      }

      return patched;
    });
    if (!silent) setLastUpdated(new Date());
  }, [mergeSide, isOptionRowEqual, progressiveDebug, logHydration]);

  const applyChainPayload = useCallback((payload, { silent = false } = {}) => {
    if (!payload || typeof payload !== 'object') return;
    const data = payload.data ?? payload;
    const stream = payload.stream_symbols ?? data.stream_symbols ?? [];


    const src = String(data?.source || '').toLowerCase();
    setChainSource(src || 'zebu_cache');

    const dates = data.expiry_dates ?? [];
    if (Array.isArray(dates)) {
      setExpiryList(dates);
      if (!selectedExpiry && dates.length) {
        skipNextExpirySnapshot.current = true;
        setSelectedExpiry(dates[0]);
      } else if (selectedExpiry && dates.length && !dates.includes(selectedExpiry)) {
        skipNextExpirySnapshot.current = true;
        setSelectedExpiry(dates[0]);
      }
    }

    if (data?.selected_expiry && !selectedExpiry) {
      skipNextExpirySnapshot.current = true;
      setSelectedExpiry(data.selected_expiry);
    }

    const spot = Number(data?.underlying_price);
    if (Number.isFinite(spot) && spot > 0) setUnderlyingPrice(spot);

    const chain = Array.isArray(data?.chain) ? data.chain : (payload?.chain ?? []);
    const rows = chain.map(transformChainRow);
    console.log(
      '[options] chain lengths',
      { dataChain: data?.chain?.length ?? 0, payloadChain: payload?.chain?.length ?? 0, rows: rows.length },
    );
    patchChainRows(rows, { silent });
    setStreamSymbols(stream);

    if (progressiveDebug && Array.isArray(stream)) {
      logHydration('stream symbols', { count: stream.length });
    }

    const ts = payload.snapshot_ts ?? data.timestamp;
    if (ts) {
      const resolved = typeof ts === 'number'
        ? (ts > 1e12 ? ts : ts * 1000)
        : Date.parse(ts);
      if (Number.isFinite(resolved)) setLastUpdated(new Date(resolved));
    }
  }, [patchChainRows, selectedExpiry, progressiveDebug, logHydration]);

  const fetchChain = useCallback(async (symbol, expiry, { silent = false } = {}) => {
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const params = new URLSearchParams({ strikes: 18 });
      if (expiry) params.append('expiry', expiry);
      let data;
      try {
        const primary = await api.get(`/options/chain/${symbol}?${params}`, { timeout: 18_000 });
        data = primary?.data;
      } catch (primaryErr) {
        if (primaryErr?.code !== 'ECONNABORTED') throw primaryErr;
        const retryParams = new URLSearchParams({ strikes: 12 });
        if (expiry) retryParams.append('expiry', expiry);
        const retry = await api.get(`/options/chain/${symbol}?${retryParams}`, { timeout: 12000 });
        data = retry?.data;
      }

      const src = String(data?.source || '').toLowerCase();
      setChainSource(src);

      if (!isZebuChainSource(src)) {
        if (!silent) {
          setOptionChain([]);
          setUnderlyingPrice(0);
          setError('Option chain requires Zebu live data. Connect broker session — no fallback quotes shown.');
        }
        return;
      }

      const dates = data.expiry_dates ?? [];
      setExpiryList(dates);
      if (!expiry && dates.length) setSelectedExpiry(dates[0]);

      const spot = Number(data.underlying_price);
      setUnderlyingPrice(Number.isFinite(spot) && spot > 0 ? spot : 0);
      const rows = (data.chain ?? []).map(transformChainRow);
      setOptionChain((prev) => {
        const finalChain = silent ? mergeChainRows(prev, rows) : rows;
        return finalChain;
      });
      setStreamSymbols(data.stream_symbols ?? []);
      setLastUpdated(new Date());
      if (!silent) setError(null);
    } catch (err) {
      if (!silent) {
        const detail = err?.response?.data?.detail;
        setError(detail ?? 'Failed to fetch Zebu option chain.');
        setOptionChain([]);
      }
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (progressiveEnabled) {
      setSelectedExpiry(null);
      setError(null);
      setLoading(false);
      const key = `options-chain:${selectedUnderlying}:nearest:${SNAPSHOT_STRIKES}`;
      const cached = getSnapshot(key);
      if (cached) {
        applyChainPayload(cached, { silent: false });
        requestAnimationFrame(() => setChartHydrationReady(true));
        if (progressiveDebug) logHydration('progressive warm restore', { key });
      } else {
        setOptionChain([]);
        setExpiryList([]);
        setChartHydrationReady(false);
        if (progressiveDebug) logHydration('progressive mount reset');
      }
      return;
    }
    setSelectedExpiry(null);
    setOptionChain([]);
    setExpiryList([]);
    fetchChain(selectedUnderlying, null);
  }, [selectedUnderlying, fetchChain, progressiveEnabled]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (progressiveEnabled) return;
    if (selectedExpiry) fetchChain(selectedUnderlying, selectedExpiry);
  }, [selectedExpiry, progressiveEnabled]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!progressiveEnabled || !selectedUnderlying) {
      if (progressiveDebug) logHydration('snapshot flow skipped', { progressiveEnabled, selectedUnderlying });
      return undefined;
    }

    if (skipNextExpirySnapshot.current) {
      skipNextExpirySnapshot.current = false;
      if (progressiveDebug) logHydration('snapshot skipped (expiry sync)');
      return undefined;
    }

    const expiry = selectedExpiry;
    const key = `options-chain:${selectedUnderlying}:${expiry || 'nearest'}:${SNAPSHOT_STRIKES}`;
    const params = new URLSearchParams({ snapshot: '1', strikes: String(SNAPSHOT_STRIKES) });
    if (expiry) params.append('expiry', expiry);

    const reconcileParams = new URLSearchParams({ reconcile: '1', strikes: String(SNAPSHOT_STRIKES) });
    if (expiry) reconcileParams.append('expiry', expiry);

    const startedAt = performance.now();
    hydrateSnapshot({
      key,
      enabled: true,
      staleThresholdMs: SNAPSHOT_STALE_MS,
      reconcileDelayMs: RECONCILE_DELAY_MS,
      snapshotFetcher: async () => {
        logHydration('snapshot fetch started', { url: `/options/chain/${selectedUnderlying}?${params.toString()}` });
        const res = await api.get(`/options/chain/${selectedUnderlying}?${params.toString()}`);
        logHydration('snapshot received');
        return res.data;
      },
      reconcileFetcher: async () => {
        logHydration('reconcile fetch started', { url: `/options/chain/${selectedUnderlying}?${reconcileParams.toString()}` });
        const res = await api.get(`/options/chain/${selectedUnderlying}?${reconcileParams.toString()}`);
        logHydration('reconcile received');
        return res.data;
      },
      onSnapshot: (payload) => {
        if (!payload) return;
        applyChainPayload(payload, { silent: false });
        setLoading(false);
        setError(null);
        if (!chartHydrationReady) {
          requestAnimationFrame(() => setChartHydrationReady(true));
        }
        logHydration('snapshot applied', {
          symbol: selectedUnderlying,
          expiry,
          strikes: SNAPSHOT_STRIKES,
          staleMs: payload.stale_ms,
          durationMs: Math.round(performance.now() - startedAt),
        });
      },
      onReconcile: (payload) => {
        if (!payload) return;
        applyChainPayload(payload, { silent: true });
        logHydration('reconcile applied', {
          symbol: selectedUnderlying,
          expiry,
          strikes: SNAPSHOT_STRIKES,
        });
      },
      onError: (err) => {
        logHydration('snapshot error', err);
        if (!chartHydrationReady) setChartHydrationReady(true);
      },
    });

    return () => cancelHydration(key);
  }, [
    progressiveEnabled,
    selectedUnderlying,
    selectedExpiry,
    applyChainPayload,
    logHydration,
    chartHydrationReady,
  ]);

  const nearestRow = useMemo(() => {
    if (!optionChain.length) return null;
    return optionChain.reduce((closest, row) => {
      if (!closest) return row;
      return Math.abs(row.strike - underlyingPrice) < Math.abs(closest.strike - underlyingPrice)
        ? row
        : closest;
    }, null);
  }, [optionChain, underlyingPrice]);

  useEffect(() => {
    if (!nearestRow || !isZebuChainSource(chainSource)) return;
    setSelectedStrike(nearestRow.strike);
    setOptionType('CE');
    const ltp = nearestRow.ce.ltp;
    setPremium(ltp > 0 ? String(ltp) : '');
    setSelectedGreeks({ delta: nearestRow.ce.delta, iv: nearestRow.ce.iv });
    setSide('BUY');
    setOrderType('MARKET');
    setLimitPrice('');
    setLots(1);
  }, [selectedUnderlying, nearestRow?.strike, chainSource]); // eslint-disable-line react-hooks/exhaustive-deps

  const daysToExpiry = useMemo(() => {
    if (!selectedExpiry) return null;
    const d = new Date(selectedExpiry);
    if (Number.isNaN(d.getTime())) return null;
    return Math.max(0, Math.ceil((d - new Date()) / 86400000));
  }, [selectedExpiry]);

  const analytics = useMemo(
    () =>
      isZebuChainSource(chainSource)
        ? computeOptionsAnalytics(optionChain, underlyingPrice, daysToExpiry)
        : null,
    [optionChain, underlyingPrice, chainSource, daysToExpiry],
  );

  const selectedRow = optionChain.find((r) => r.strike === selectedStrike);
  const sideData = selectedRow ? (optionType === 'CE' ? selectedRow.ce : selectedRow.pe) : null;
  const oppositeSideData = selectedRow ? (optionType === 'CE' ? selectedRow.pe : selectedRow.ce) : null;

  const getCurrentLtp = useCallback(
    (strike, type) => {
      const row = optionChain.find((r) => r.strike === strike);
      if (!row) return 0;
      const v = type === 'CE' ? row.ce.ltp : row.pe.ltp;
      return Number(v) > 0 ? v : 0;
    },
    [optionChain],
  );

  const lotSize = getLotSize(selectedUnderlying);
  const premiumValue = Number(premium) || 0;
  const effectivePrice = orderType === 'LIMIT' ? Number(limitPrice || premiumValue) : premiumValue;
  const totalValue = lots * lotSize * effectivePrice;

  const selectedSymbol = useMemo(() => {
    const tsym = String(sideData?.tsym || '').trim();
    if (tsym) return tsym;
    return buildDisplaySymbol(
      selectedUnderlying,
      selectedStrike ?? nearestRow?.strike ?? 0,
      optionType,
      selectedExpiry,
    );
  }, [sideData?.tsym, selectedUnderlying, selectedStrike, nearestRow?.strike, optionType, selectedExpiry]);

  const spread =
    sideData?.ask != null && sideData?.bid != null && Number(sideData.ask) > 0
      ? Number(sideData.ask) - Number(sideData.bid)
      : null;

  const strikeLtp = useMemo(() => {
    if (!sideData) return null;
    const ltp = Number(sideData.ltp);
    if (Number.isFinite(ltp) && ltp > 0) return ltp;
    const bid = Number(sideData.bid);
    const ask = Number(sideData.ask);
    if (Number.isFinite(bid) && bid > 0 && Number.isFinite(ask) && ask > 0) return (bid + ask) / 2;
    if (Number.isFinite(bid) && bid > 0) return bid;
    if (Number.isFinite(ask) && ask > 0) return ask;
    return null;
  }, [sideData]);
  const chartLivePrice = strikeLtp ?? (underlyingPrice > 0 ? underlyingPrice : null);
  const chartChange = sideData?.change != null && Number.isFinite(Number(sideData.change)) ? Number(sideData.change) : null;
  const chartChangePct =
    sideData?.changePct != null && Number.isFinite(Number(sideData.changePct))
      ? Number(sideData.changePct)
      : null;

  const metaLine = `NFO · Lot ${lotSize}${selectedExpiry ? ` · ${formatExpiryChip(selectedExpiry)}` : ''}`;

  const resolveLegPremium = useCallback((leg) => {
    if (!leg) return '';
    const ltp = Number(leg.ltp);
    if (Number.isFinite(ltp) && ltp > 0) return String(ltp);
    const bid = Number(leg.bid);
    const ask = Number(leg.ask);
    if (Number.isFinite(bid) && bid > 0 && Number.isFinite(ask) && ask > 0) {
      return String(((bid + ask) / 2).toFixed(2));
    }
    if (Number.isFinite(bid) && bid > 0) return String(bid);
    if (Number.isFinite(ask) && ask > 0) return String(ask);
    return '';
  }, []);

  const handleSelectOption = useCallback(
    (strike, type, data) => {
      setSelectedStrike(strike);
      setOptionType(type);
      setSide(data?.side || 'BUY');
      setPremium(resolveLegPremium(data));
      setSelectedGreeks({ delta: data?.delta ?? 0, iv: data?.iv ?? 0 });
      if (isMobile) setOrderSheetOpen(true);
    },
    [isMobile, resolveLegPremium],
  );

  useEffect(() => {
    if (!sideData || !isZebuChainSource(chainSource)) return;
    const next = resolveLegPremium(sideData);
    if (next) setPremium(next);
  }, [sideData, chainSource, resolveLegPremium]);

  const handlePlaceOrder = useCallback(() => {
    if (!selectedStrike) {
      toast.error('Select a strike from the option chain');
      return;
    }
    if (!isZebuChainSource(chainSource) || premiumValue <= 0) {
      toast.error('Valid Zebu premium required before placing order');
      return;
    }
    const symLabel = `${selectedUnderlying} ${selectedStrike} ${optionType}`;
    placeOptionOrder({
      symbol: symLabel,
      underlying: selectedUnderlying,
      expiry: selectedExpiry,
      strike: selectedStrike,
      type: optionType,
      orderType,
      side,
      lots,
      lotSize,
      premium: effectivePrice,
    });
    toast.success(`${side} ${orderType} order recorded (paper trade)`);
    setOrderPanelVisible(false);
    if (isMobile) setOrderSheetOpen(false);
  }, [
    selectedStrike,
    chainSource,
    premiumValue,
    selectedUnderlying,
    optionType,
    selectedExpiry,
    side,
    lots,
    lotSize,
    effectivePrice,
    orderType,
    placeOptionOrder,
    isMobile,
  ]);

  const enrichedPositions = useMemo(
    () =>
      positions.map((pos) => {
        const legType = pos.optionType ?? pos.type;
        const ltp = getCurrentLtp(pos.strike, legType);
        const avg = pos.avgPremium ?? pos.premium ?? 0;
        const raw = (ltp - avg) * pos.lots * (pos.lotSize ?? getLotSize(pos.underlying));
        return { ...pos, ltp, pnl: pos.side === 'BUY' ? raw : -raw, optionType: legType };
      }),
    [positions, getCurrentLtp],
  );

  const scrollToAtm = useCallback(() => {
    const atm = analytics?.atmStrike ?? nearestRow?.strike;
    if (atm != null) {
      setScrollToStrike(atm);
      setSelectedStrike(atm);
    }
  }, [analytics?.atmStrike, nearestRow?.strike]);

  const clampPos = useCallback(
    (p) => ({
      x: Math.max(0, Math.min(window.innerWidth - ORDER_FLOAT_WIDTH, p.x)),
      y: Math.max(0, Math.min(window.innerHeight - 120, p.y)),
    }),
    [],
  );

  const handleOrderPanelGrab = useCallback(
    (event) => {
      if (event.target.closest('button') || event.target.closest('input')) return;
      event.preventDefault();
      orderPanelDrag.current = {
        active: true,
        sx: event.clientX,
        sy: event.clientY,
        ox: orderPanelPos.x,
        oy: orderPanelPos.y,
      };
      const onMove = (e) => {
        if (!orderPanelDrag.current.active) return;
        setOrderPanelPos(
          clampPos({
            x: orderPanelDrag.current.ox + (e.clientX - orderPanelDrag.current.sx),
            y: orderPanelDrag.current.oy + (e.clientY - orderPanelDrag.current.sy),
          }),
        );
      };
      const onUp = () => {
        orderPanelDrag.current.active = false;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    },
    [orderPanelPos, clampPos],
  );

  const openOrderPanel = useCallback(() => {
    setOrderPanelPos(clampPos(getDefaultOrderPos()));
    setOrderPanelVisible(true);
  }, [clampPos, getDefaultOrderPos]);

  const rightPanelOpen = rightPanelVisible && showRightSidebar && !isMobile;
  const chainOpen = chainPanelVisible && !isMobile;

  const orderPanelEl = (
    <OptionsOrderPanel
      selectedSymbol={selectedSymbol}
      expiry={selectedExpiry}
      optionType={optionType}
      onOptionTypeChange={setOptionType}
      side={side}
      onSideChange={setSide}
      orderType={orderType}
      onOrderTypeChange={setOrderType}
      lots={lots}
      onLotsChange={setLots}
      lotSize={lotSize}
      limitPrice={limitPrice}
      onLimitPriceChange={setLimitPrice}
      premium={premium}
      onPremiumChange={setPremium}
      totalValue={totalValue}
      maxLoss={side === 'SELL' ? premiumValue * lots * lotSize : null}
      greeks={selectedGreeks}
      spread={spread}
      onPlaceOrder={handlePlaceOrder}
      disabled={!selectedStrike || !isZebuChainSource(chainSource) || premiumValue <= 0}
    />
  );

  return (
    <div className="options-terminal-root flex flex-col h-[calc(100vh-56px)] min-h-0 overflow-hidden bg-surface-950">
      {error && (
        <div className="flex-shrink-0 px-3 py-1.5 border-b border-red-500/20 bg-red-500/10 text-[11px] text-red-500 dark:text-red-400 truncate">
          {error}
        </div>
      )}

      <div
        className={cn(
          'terminal-grid flex-1 min-h-0 options-terminal-grid',
          !rightPanelOpen && 'terminal-grid--no-right',
          !chainOpen && 'terminal-grid--no-watchlist',
        )}
      >
        {chainOpen && (
          <ResizablePanel
            side="left"
            defaultSize={380}
            minSize={320}
            maxSize={480}
            className="terminal-area-watchlist options-chain-panel hidden lg:flex h-full min-h-0 self-stretch overflow-hidden"
          >
            <div className="flex flex-col h-full min-h-0 w-full overflow-hidden options-chain-scroll-host">
              <OptionChainCompact
                chain={optionChain}
                spotPrice={underlyingPrice}
                selectedStrike={selectedStrike}
                selectedType={optionType}
                onSelectOption={handleSelectOption}
                scrollToStrike={scrollToStrike}
                loading={loading}
                source={chainSource}
                selectedUnderlying={selectedUnderlying}
                onSelectUnderlying={setSelectedUnderlying}
                expiryList={expiryList}
                selectedExpiry={selectedExpiry}
                onSelectExpiry={setSelectedExpiry}
              />
            </div>
          </ResizablePanel>
        )}

        <div className="terminal-area-header min-w-0">
          <OptionsChartHeader
            displaySymbol={selectedSymbol}
            metaLine={metaLine}
            ltp={strikeLtp}
            change={chartChange}
            changePct={chartChangePct}
            optionType={optionType}
            interval={chartInterval}
            onIntervalChange={setChartInterval}
            chainPanelVisible={chainPanelVisible}
            onToggleChainPanel={() => {
              setChainPanelVisible((v) => !v);
              setTimeout(() => window.dispatchEvent(new Event('resize')), 250);
            }}
            rightPanelVisible={rightPanelVisible}
            onToggleRightPanel={() => setRightPanelVisible((v) => !v)}
            showRightToggle={showRightSidebar}
            orderPanelVisible={orderPanelVisible}
            onToggleOrderPanel={() => (orderPanelVisible ? setOrderPanelVisible(false) : openOrderPanel())}
            greeksMini={selectedGreeks}
          />
        </div>

        <div className="terminal-area-chart min-w-0 min-h-0 relative overflow-hidden">
          <ErrorBoundary fallback="Chart failed to load.">
            <ZebuLiveChart
              key={`${chartContractSymbol || 'none'}-${chartInterval}`}
              candles={chartCandles}
              isLoading={chartLoading}
              symbol={chartContractSymbol || selectedSymbol}
              period={chartInterval}
              onPeriodChange={setChartInterval}
              livePrice={chartLivePrice}
            />
          </ErrorBoundary>
          {chartError && (
            <div className="absolute top-2 left-2 right-2 text-[10px] px-2 py-1 rounded-md border border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-200">
              {chartError}
            </div>
          )}
        </div>

        <div
          className="terminal-area-bottom min-w-0 transition-all duration-200"
          style={{ height: bottomCollapsed ? '36px' : '200px' }}
        >
          <OptionsBottomDock
            collapsed={bottomCollapsed}
            onToggleCollapse={() => setBottomCollapsed((v) => !v)}
            positions={enrichedPositions}
            orders={orders}
            onClosePosition={closePosition}
          />
        </div>

        {rightPanelOpen && (
          <ResizablePanel
            side="right"
            defaultSize={280}
            minSize={240}
            maxSize={360}
            className="terminal-area-orders hidden lg:flex min-h-0 overflow-hidden"
          >
            <ErrorBoundary fallback="Details panel unavailable.">
              <OptionsRightSidebar
                underlying={selectedUnderlying}
                analytics={analytics}
                loading={loading}
                source={chainSource}
                expiry={selectedExpiry ? formatExpiryChip(selectedExpiry) : null}
                daysToExpiry={daysToExpiry}
                strike={selectedStrike}
                optionType={optionType}
                sideData={sideData}
                oppositeSideData={oppositeSideData}
                displaySymbol={selectedSymbol}
              />
            </ErrorBoundary>
          </ResizablePanel>
        )}
      </div>

      {orderPanelVisible && !isMobile && (
        <div
          className="fixed z-50 hidden lg:flex flex-col rounded-2xl select-none bg-surface-900/95 border border-edge/10 shadow-2xl shadow-black/40"
          style={{
            left: orderPanelPos.x,
            top: orderPanelPos.y,
            width: ORDER_FLOAT_WIDTH,
            maxHeight: 'calc(100vh - 140px)',
            backdropFilter: 'blur(24px)',
          }}
        >
          <div
            onMouseDown={handleOrderPanelGrab}
            className="h-8 px-3 flex items-center justify-between cursor-move border-b border-edge/10 flex-shrink-0"
          >
            <span className="text-[11px] font-semibold text-heading">Order Panel</span>
            <button
              type="button"
              onClick={() => setOrderPanelVisible(false)}
              className="w-5 h-5 rounded-md flex items-center justify-center options-chain-chip hover:text-heading hover:bg-surface-800"
            >
              ✕
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto rounded-b-2xl">{orderPanelEl}</div>
        </div>
      )}

      {isMobile && (
        <>
          <div className="lg:hidden flex-shrink-0 max-h-[42vh] min-h-[200px] border-t border-edge/5 flex flex-col overflow-hidden">
            <OptionChainCompact
              chain={optionChain}
              spotPrice={underlyingPrice}
              selectedStrike={selectedStrike}
              selectedType={optionType}
              onSelectOption={handleSelectOption}
              scrollToStrike={scrollToStrike}
              loading={loading}
              source={chainSource}
              selectedUnderlying={selectedUnderlying}
              onSelectUnderlying={setSelectedUnderlying}
              expiryList={expiryList}
              selectedExpiry={selectedExpiry}
              onSelectExpiry={setSelectedExpiry}
            />
          </div>
          <button
            type="button"
            onClick={() => setOrderSheetOpen(true)}
            className="fixed bottom-5 right-4 z-30 px-4 py-2.5 rounded-full bg-primary-600 text-white text-sm font-semibold shadow-panel lg:hidden"
          >
            Order Panel
          </button>
          {orderSheetOpen && (
            <div className="fixed inset-0 z-40 lg:hidden">
              <div className="absolute inset-0 bg-black/55" onClick={() => setOrderSheetOpen(false)} />
              <div className="absolute left-0 right-0 bottom-0 rounded-t-2xl border-t border-edge/10 bg-surface-900 max-h-[80vh] overflow-hidden flex flex-col">
                <div className="flex items-center justify-between px-4 py-3 border-b border-edge/10">
                  <span className="text-sm font-semibold text-heading">Order Panel</span>
                  <button type="button" onClick={() => setOrderSheetOpen(false)} className="options-chain-chip text-lg">
                    ✕
                  </button>
                </div>
                <div className="overflow-y-auto flex-1 min-h-0">{orderPanelEl}</div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
