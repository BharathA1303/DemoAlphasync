/**
 * FuturesPage — Terminal-grade futures workspace.
 * Layout mirrors TradingWorkspace exactly: Watchlist | (Header + Chart + Dock)
 * Order panel is a floating draggable window, same as terminal.
 */
import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { useFuturesStream } from '../hooks/useFuturesStream';
import { useMarketSession } from '../hooks/useMarketSession';
import { useResponsiveTradeBridge } from '../responsive/hooks/useResponsiveTradeBridge';
import { useResponsive } from '../responsive/hooks/useResponsive';
import { BREAKPOINTS } from '../responsive/constants/breakpoints';
import useUnifiedFuturesStore from '../stores/useUnifiedFuturesStore';
import { useFuturesWatchlistStore } from '../stores/useFuturesWatchlistStore';
import api from '../services/api';
import ErrorBoundary from '../components/ErrorBoundary';
import ZebuLiveChart from '../components/trading/ZebuLiveChart';
import FuturesWatchlist from '../components/trading/FuturesWatchlist';
import { FuturesRightSidebar } from '../futures-intelligence';
import ResizablePanel from '../components/layout/ResizablePanel';
import { cn } from '../utils/cn';
import { formatPrice, formatCurrency } from '../utils/formatters';
import { PanelLeftOpen, PanelLeftClose, PanelRightOpen, PanelRightClose } from 'lucide-react';
import toast from 'react-hot-toast';

const intervalApiMap = { '1m': '1m', '5m': '5m', '15m': '15m', '1H': '1h', '1D': '1d' };
const ORDER_FLOAT_WIDTH = 312;

// Hold last chart candles across closed market / failed refetch (equity terminal parity)
const _futuresCandleCache = new Map();
const FUTURES_CANDLE_CACHE_TTL = 7 * 24 * 60 * 60 * 1000;

function futuresCandleCacheKey(contract, interval) {
  return `${String(contract || '').toUpperCase()}:${interval}`;
}

function getCachedFuturesCandles(contract, interval) {
  const entry = _futuresCandleCache.get(futuresCandleCacheKey(contract, interval));
  if (!entry?.candles?.length) return null;
  if (Date.now() - (entry.ts || 0) > FUTURES_CANDLE_CACHE_TTL) return null;
  return entry.candles;
}

const ORDER_TYPES = ['MARKET', 'LIMIT', 'SL', 'SL-M'];

const CHART_INTERVALS = [
  { key: '1m', label: '1m' },
  { key: '5m', label: '5m' },
  { key: '15m', label: '15m' },
  { key: '1H', label: '1H' },
  { key: '1D', label: '1D' },
];

function quotePrice(q) {
  const n = Number(q?.ltp ?? q?.price ?? q?.lp);
  return Number.isFinite(n) ? n : null;
}
function quoteChange(q) {
  const v = Number(q?.change ?? q?.net_change);
  if (Number.isFinite(v)) return v;
  const ltp = quotePrice(q);
  const close = Number(q?.close ?? q?.prev_close);
  return ltp != null && Number.isFinite(close) && close > 0 ? +(ltp - close).toFixed(2) : null;
}
function quoteChangePct(q) {
  const v = Number(q?.change_pct ?? q?.change_percent ?? q?.percent_change ?? q?.pc);
  if (Number.isFinite(v)) return v;
  const ch = quoteChange(q);
  const close = Number(q?.close ?? q?.prev_close);
  return ch != null && Number.isFinite(close) && close > 0 ? +((ch / close) * 100).toFixed(2) : null;
}

function normalizeCandles(rows = []) {
  const seen = new Map();
  const nowSec = Math.floor(Date.now() / 1000);
  for (const row of rows) {
    let time = Number(row?.time ?? row?.timestamp);
    if (!Number.isFinite(time) && typeof row?.timestamp === 'string') {
      const parsed = Date.parse(row.timestamp);
      if (Number.isFinite(parsed)) time = Math.floor(parsed / 1000);
    }
    if (Number.isFinite(time)) {
      if (time > 1e18) time = Math.floor(time / 1e9);
      else if (time > 1e15) time = Math.floor(time / 1e6);
      else if (time > 1e12) time = Math.floor(time / 1e3);
      else time = Math.floor(time);
    }
    const open = Number(row?.open), high = Number(row?.high), low = Number(row?.low), close = Number(row?.close);
    const volume = Number(row?.volume) || 0;
    if (!Number.isFinite(time) || time < 946684800 || time > nowSec + 7 * 86400) continue;
    if (![open, high, low, close].every(v => Number.isFinite(v) && v > 0)) continue;
    const h = Math.max(open, high, low, close), l = Math.min(open, high, low, close);
    seen.set(time, { time, open: +open.toFixed(2), high: +h.toFixed(2), low: +l.toFixed(2), close: +close.toFixed(2), volume: Math.max(0, Math.floor(volume)) });
  }
  return [...seen.values()].sort((a, b) => a.time - b.time);
}

// ── CHART HEADER — broker-grade futures header with OHLC + OI + Bid/Ask ───────
function FuturesChartHeader({ interval, onIntervalChange, isWatchlisted, onToggleWatchlist, orderPanelVisible, onToggleOrderPanel, hasPositions, onKillSwitch, killSwitchBusy }) {
  const selectedContract = useUnifiedFuturesStore((s) => s.contracts.selectedContract);
  const contractObj = useUnifiedFuturesStore((s) =>
    s.contracts.selectedContract ? s.contracts.bySymbol[s.contracts.selectedContract] ?? null : null);
  const quote = useUnifiedFuturesStore((s) =>
    s.contracts.selectedContract ? s.quotes[s.contracts.selectedContract] ?? null : null);
  const lastQuoteUpdate = useUnifiedFuturesStore((s) => s._lastQuoteUpdate);

  const ltp = useMemo(() => quotePrice(quote), [quote, lastQuoteUpdate]);
  const change = useMemo(() => quoteChange(quote), [quote, lastQuoteUpdate]);
  const changePct = useMemo(() => quoteChangePct(quote), [quote, lastQuoteUpdate]);

  // Full broker-grade fields from Zebu tick
  const open = useMemo(() => { const v = Number(quote?.open); return Number.isFinite(v) && v > 0 ? v : null; }, [quote?.open, lastQuoteUpdate]);
  const high = useMemo(() => { const v = Number(quote?.high); return Number.isFinite(v) && v > 0 ? v : null; }, [quote?.high, lastQuoteUpdate]);
  const low = useMemo(() => { const v = Number(quote?.low); return Number.isFinite(v) && v > 0 ? v : null; }, [quote?.low, lastQuoteUpdate]);
  const volume = useMemo(() => { const v = Number(quote?.volume); return Number.isFinite(v) && v >= 0 ? v : null; }, [quote?.volume, lastQuoteUpdate]);
  const oi = useMemo(() => { const v = Number(quote?.oi); return Number.isFinite(v) && v >= 0 ? v : null; }, [quote?.oi, lastQuoteUpdate]);
  const bid = useMemo(() => { const v = Number(quote?.bid ?? quote?.bid_price); return Number.isFinite(v) && v > 0 ? v : null; }, [quote?.bid, quote?.bid_price, lastQuoteUpdate]);
  const ask = useMemo(() => { const v = Number(quote?.ask ?? quote?.ask_price); return Number.isFinite(v) && v > 0 ? v : null; }, [quote?.ask, quote?.ask_price, lastQuoteUpdate]);
  const prevClose = useMemo(() => { const v = Number(quote?.close ?? quote?.prev_close); return Number.isFinite(v) && v > 0 ? v : null; }, [quote?.close, quote?.prev_close, lastQuoteUpdate]);
  const avgPrice = useMemo(() => { const v = Number(quote?.avg_price); return Number.isFinite(v) && v > 0 ? v : null; }, [quote?.avg_price, lastQuoteUpdate]);

  const [periodOpen, setPeriodOpen] = useState(false);
  const periodRef = useRef(null);

  useEffect(() => {
    if (!periodOpen) return;
    const h = (e) => { if (periodRef.current && !periodRef.current.contains(e.target)) setPeriodOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [periodOpen]);

  const currentLabel = CHART_INTERVALS.find(i => i.key === interval)?.label ?? interval;

  const fmtVol = (v) => {
    if (v == null) return '—';
    if (v >= 1e7) return `${(v / 1e7).toFixed(2)}Cr`;
    if (v >= 1e5) return `${(v / 1e5).toFixed(2)}L`;
    if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
    return v.toLocaleString('en-IN');
  };

  const fmtOI = (v) => {
    if (v == null) return '—';
    if (v >= 1e7) return `${(v / 1e7).toFixed(2)}Cr`;
    if (v >= 1e5) return `${(v / 1e5).toFixed(2)}L`;
    if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
    return v.toLocaleString('en-IN');
  };

  const isUp = change == null ? null : change >= 0;

  return (
    <div className="flex flex-col w-full border-b border-edge/5 bg-surface-900/30">
      {/* ROW 1: Symbol + LTP + Controls */}
      <div className="flex items-center w-full h-11 px-3 gap-2">
        {/* LEFT: Symbol + Price */}
        <div className="flex items-center gap-2.5 flex-shrink-0 min-w-0">
          <div className="flex flex-col leading-none min-w-0">
            <span className="text-sm font-semibold text-heading truncate max-w-[180px]">
              {selectedContract || 'Select Contract'}
            </span>
            <span className="text-[10px] text-gray-500 mt-0.5">
              NFO{contractObj?.lot_size ? ` · Lot: ${contractObj.lot_size}` : ''}
              {contractObj?.expiry_date ? ` · ${new Date(contractObj.expiry_date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' })}` : ''}
            </span>
          </div>

          {ltp != null && (
            <div className="flex items-baseline gap-1.5 flex-shrink-0">
              <span className={cn('text-base font-bold font-mono tabular-nums transition-colors duration-75',
                isUp === true ? 'text-bull' : isUp === false ? 'text-bear' : 'text-heading')}>
                {formatPrice(ltp)}
              </span>
              {change != null && (
                <span className={cn('text-[11px] font-mono font-semibold whitespace-nowrap tabular-nums', isUp ? 'text-bull' : 'text-bear')}>
                  {isUp ? '+' : ''}{change.toFixed(2)}
                  {changePct != null && ` (${isUp ? '+' : ''}${changePct.toFixed(2)}%)`}
                </span>
              )}
            </div>
          )}
        </div>

        <div className="w-px h-4 bg-edge/10 mx-1 flex-shrink-0 hidden lg:block" />

        {/* OHLC + Volume + OI — compact inline row (hidden on small screens) */}
        <div className="hidden lg:flex items-center gap-3 text-[10px] flex-1 min-w-0 overflow-hidden">
          {open != null && (
            <div className="flex items-center gap-1 flex-shrink-0">
              <span className="text-gray-600 uppercase tracking-wide">O</span>
              <span className="font-mono tabular-nums text-gray-400">{formatPrice(open)}</span>
            </div>
          )}
          {high != null && (
            <div className="flex items-center gap-1 flex-shrink-0">
              <span className="text-gray-600 uppercase tracking-wide">H</span>
              <span className="font-mono tabular-nums text-bull">{formatPrice(high)}</span>
            </div>
          )}
          {low != null && (
            <div className="flex items-center gap-1 flex-shrink-0">
              <span className="text-gray-600 uppercase tracking-wide">L</span>
              <span className="font-mono tabular-nums text-bear">{formatPrice(low)}</span>
            </div>
          )}
          {prevClose != null && (
            <div className="flex items-center gap-1 flex-shrink-0">
              <span className="text-gray-600 uppercase tracking-wide">PC</span>
              <span className="font-mono tabular-nums text-gray-400">{formatPrice(prevClose)}</span>
            </div>
          )}
          {volume != null && (
            <div className="flex items-center gap-1 flex-shrink-0 hidden xl:flex">
              <span className="text-gray-600 uppercase tracking-wide">Vol</span>
              <span className="font-mono tabular-nums text-gray-400">{fmtVol(volume)}</span>
            </div>
          )}
          {oi != null && (
            <div className="flex items-center gap-1 flex-shrink-0 hidden xl:flex">
              <span className="text-gray-600 uppercase tracking-wide">OI</span>
              <span className="font-mono tabular-nums text-amber-400/80">{fmtOI(oi)}</span>
            </div>
          )}
          {bid != null && ask != null && (
            <div className="flex items-center gap-1 flex-shrink-0 hidden 2xl:flex">
              <span className="font-mono tabular-nums text-bull">{formatPrice(bid)}</span>
              <span className="text-gray-700">/</span>
              <span className="font-mono tabular-nums text-bear">{formatPrice(ask)}</span>
            </div>
          )}
        </div>

        {/* RIGHT: Interval + buttons */}
        <div className="flex items-center gap-1.5 flex-shrink-0 ml-auto">
          {/* Interval dropdown */}
          <div className="relative" ref={periodRef}>
            <button onClick={() => setPeriodOpen(v => !v)}
              className={cn('h-7 px-2.5 rounded-md border text-xs font-semibold inline-flex items-center gap-1 transition-colors duration-150',
                periodOpen ? 'bg-primary-600/20 border-primary-500/40 text-primary-600' : 'bg-surface-800/80 border-edge/20 text-gray-500 hover:text-heading hover:border-edge/40')}>
              <span className="font-mono tabular-nums">{currentLabel}</span>
              <svg className={cn('w-3 h-3 transition-transform duration-150', periodOpen && 'rotate-180')} viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
              </svg>
            </button>
            {periodOpen && (
              <div className="absolute top-full left-1/2 -translate-x-1/2 mt-1.5 z-50 min-w-[110px] rounded-lg border border-edge/10 bg-surface-900/95 backdrop-blur-xl shadow-xl shadow-black/40 py-1.5">
                {CHART_INTERVALS.map(({ key, label }) => (
                  <button key={key} onClick={() => { onIntervalChange(key); setPeriodOpen(false); }}
                    className={cn('w-full text-left px-3 py-1.5 text-xs font-medium transition-colors flex items-center justify-between',
                      interval === key ? 'bg-primary-600/15 text-primary-600' : 'text-gray-400 hover:text-heading hover:bg-edge/5')}>
                    <span>{label}</span>
                    {interval === key && (
                      <svg className="w-3 h-3 text-primary-600" viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Watchlist star */}
          <button onClick={onToggleWatchlist}
            className={cn('h-7 w-7 rounded-md border inline-flex items-center justify-center transition-colors duration-150 flex-shrink-0',
              isWatchlisted ? 'bg-primary-600/20 border-primary-500/40 text-primary-600' : 'bg-surface-800/80 border-edge/20 text-gray-400 hover:text-gray-700 hover:border-edge/40')}
            title={isWatchlisted ? 'Remove from watchlist' : 'Add to watchlist'}>
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill={isWatchlisted ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2">
              <path d="m12 2 3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.56 5.82 22 7 14.14 2 9.27l6.91-1.01L12 2z" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>

          {/* Order Panel toggle */}
          <button onClick={onToggleOrderPanel}
            className={cn('h-7 px-2.5 rounded-md border text-[11px] font-semibold inline-flex items-center justify-center gap-1 transition-colors duration-150 flex-shrink-0',
              orderPanelVisible ? 'bg-primary-600/20 border-primary-500/40 text-primary-600' : 'bg-surface-800/80 border-edge/20 text-gray-500 hover:text-heading hover:border-edge/40')}
            title={orderPanelVisible ? 'Hide order panel' : 'Show order panel'}>
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 9h6M9 12h6M9 15h4" strokeLinecap="round"/>
            </svg>
            <span className="hidden sm:inline">Order</span>
          </button>

          {hasPositions && (
            <button onClick={onKillSwitch} disabled={killSwitchBusy}
              className={cn('h-7 px-2.5 rounded-md border text-[11px] font-bold inline-flex items-center justify-center gap-1 transition-colors duration-150 flex-shrink-0',
                'bg-red-500/15 border-red-500/30 text-red-500 hover:bg-red-500/25',
                killSwitchBusy && 'opacity-50 cursor-not-allowed')}
              title="Kill Switch — Close all futures positions">
              <span>{killSwitchBusy ? 'CLOSING…' : 'KILL'}</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── FLOATING ORDER PANEL ──────────────────────────────────────────────────────
function FuturesOrderPanel({ onClose }) {
  const selectedContractSym = useUnifiedFuturesStore((s) => s.contracts.selectedContract);
  const contractObj = useUnifiedFuturesStore((s) =>
    s.contracts.selectedContract ? s.contracts.bySymbol[s.contracts.selectedContract] ?? null : null);
  const quote = useUnifiedFuturesStore((s) =>
    s.contracts.selectedContract ? s.quotes[s.contracts.selectedContract] ?? null : null);
  const margin = useUnifiedFuturesStore((s) => s.margin);
  const { marketOpen, closedDetail } = useMarketSession();

  const [side, setSide] = useState('BUY');
  const [orderType, setOrderType] = useState('MARKET');
  const [lots, setLots] = useState(1);
  const [limitPrice, setLimitPrice] = useState('');
  const [triggerPrice, setTriggerPrice] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const ltp = quotePrice(quote);
  const lotSize = Number(contractObj?.lot_size || 1);
  const quantity = Math.max(1, lots) * lotSize;
  const isLimit = orderType === 'LIMIT' || orderType === 'SL';
  const isStop = orderType === 'SL' || orderType === 'SL-M';
  const effectivePrice = isLimit ? Number(limitPrice || 0) : (ltp || 0);
  const contractValue = quantity * effectivePrice;

  // Realistic SPAN-like margin calculation (matches backend)
  const [marginInfo, setMarginInfo] = useState(null);
  useEffect(() => {
    if (!selectedContractSym || !effectivePrice || effectivePrice <= 0) return;
    let cancelled = false;
    const fetchMargin = async () => {
      try {
        const res = await api.get(
          `/futures/margin/calculate/${selectedContractSym}?quantity=${quantity}&price=${effectivePrice}`
        );
        if (!cancelled && res.data) setMarginInfo(res.data);
      } catch { /* fallback to estimate */ }
    };
    const timer = setTimeout(fetchMargin, 300); // debounce
    return () => { cancelled = true; clearTimeout(timer); };
  }, [selectedContractSym, quantity, effectivePrice]);

  const requiredMargin = marginInfo?.total_margin ?? contractValue * 0.12;

  useEffect(() => {
    if (ltp) { setLimitPrice(ltp.toFixed(2)); setTriggerPrice(ltp.toFixed(2)); }
  }, [selectedContractSym]);

  const placeOrder = useCallback(async () => {
    if (!marketOpen) {
      toast.error(closedDetail);
      return;
    }
    if (!selectedContractSym) { toast.error('Select a contract first'); return; }
    if (isLimit && (!effectivePrice || effectivePrice <= 0)) { toast.error('Enter valid limit price'); return; }
    if (isStop && (!Number(triggerPrice) || Number(triggerPrice) <= 0)) { toast.error('Enter valid trigger price'); return; }

    const apiOrderType = orderType === 'SL' ? 'STOP_LOSS_LIMIT' : orderType === 'SL-M' ? 'STOP_LOSS' : orderType;
    const price = isLimit ? effectivePrice : (ltp || 0);

    setSubmitting(true);
    try {
      await api.post('/futures/orders/place', {
        contract_symbol: selectedContractSym, side,
        order_type: apiOrderType, quantity, price: price || 0,
        client_price: price || 0,
        trigger_price: isStop ? Number(triggerPrice) : null,
        tag: 'FUTURES_DAY',
      });
      toast.success(`${side} order placed for ${lots} lot(s)`);
      const store = useUnifiedFuturesStore.getState();
      try {
        const [ordRes, posRes] = await Promise.allSettled([api.get('/futures/orders'), api.get('/futures/positions')]);
        if (ordRes.status === 'fulfilled') store.setOrders(ordRes.value.data?.orders ?? []);
        if (posRes.status === 'fulfilled') {
          store.setPositions(posRes.value.data?.positions ?? []);
          store.recalculateLivePnl();
        }
      } catch { /* best effort refresh */ }
    } catch (err) {
      toast.error(err?.response?.data?.detail || err?.message || 'Order failed');
    } finally {
      setSubmitting(false);
    }
  }, [marketOpen, closedDetail, selectedContractSym, side, orderType, quantity, effectivePrice, triggerPrice, ltp, lots, isLimit, isStop]);

  const isBuy = side === 'BUY';

  return (
    <div className="flex flex-col w-full bg-surface-900 min-h-0">
      <div className="px-3 py-2.5 border-b border-edge/5">
        <div className="flex gap-1.5">
          <button onClick={() => setSide('BUY')}
            className={cn('flex-1 py-1.5 text-sm font-bold rounded-lg border transition-all duration-200',
              isBuy ? 'bg-bull text-white border-emerald-500/40 shadow-lg shadow-emerald-500/20' : 'bg-surface-800/60 border-edge/10 text-gray-500 hover:text-gray-700 hover:bg-surface-800')}>
            BUY
          </button>
          <button onClick={() => setSide('SELL')}
            className={cn('flex-1 py-1.5 text-sm font-bold rounded-lg border transition-all duration-200',
              !isBuy ? 'bg-bear text-white border-red-500/40 shadow-lg shadow-red-500/20' : 'bg-surface-800/60 border-edge/10 text-gray-500 hover:text-gray-700 hover:bg-surface-800')}>
            SELL
          </button>
        </div>
      </div>

      <div className="space-y-3 flex-1 overflow-y-auto min-h-0 px-3 py-2.5">
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="metric-label block mb-1">Contract</label>
            <div className="h-11 bg-surface-800/60 border border-edge/10 rounded-lg px-2.5 text-sm font-semibold text-heading flex items-center justify-between gap-1">
              <span className="min-w-0 truncate">{selectedContractSym || '—'}</span>
              {ltp != null && <span className="text-[11px] text-gray-500 font-mono tabular-nums flex-shrink-0">₹{formatPrice(ltp)}</span>}
            </div>
          </div>
          <div>
            <label className="metric-label block mb-1">Lots</label>
            <div className="h-11 flex items-center border border-edge/10 rounded-lg overflow-hidden bg-surface-800/60">
              <button type="button" onClick={() => setLots(l => Math.max(1, l - 1))} className="px-3 py-2 text-gray-400 hover:text-heading hover:bg-overlay/5 text-lg font-bold">−</button>
              <input type="number" min={1} value={lots} onChange={e => setLots(Math.max(1, parseInt(e.target.value, 10) || 1))}
                className="min-w-0 flex-1 text-center bg-transparent text-heading text-sm py-2 focus:outline-none tabular-nums font-mono" />
              <button type="button" onClick={() => setLots(l => l + 1)} className="px-3 py-2 text-gray-400 hover:text-heading hover:bg-overlay/5 text-lg font-bold flex-shrink-0">+</button>
            </div>
          </div>
        </div>
        <div className="text-[10px] text-gray-500 px-0.5">Qty: {quantity} ({lots} × {lotSize})</div>

        <div>
          <label className="metric-label block mb-1">Order Type</label>
          <div className="grid grid-cols-4 gap-1">
            {ORDER_TYPES.map(t => (
              <button key={t} type="button" onClick={() => setOrderType(t)}
                className={cn('h-9 rounded-lg text-xs font-semibold transition-colors',
                  orderType === t ? 'bg-primary-600/20 text-primary-600' : 'bg-surface-800/60 text-gray-500 hover:text-heading hover:bg-surface-800')}>{t}</button>
            ))}
          </div>
        </div>

        {isLimit && (
          <div>
            <label className="metric-label block mb-1">Limit Price (₹)</label>
            <input type="number" step="0.05" value={limitPrice} onChange={e => setLimitPrice(e.target.value)}
              className="w-full bg-surface-800/60 border border-edge/10 rounded-lg px-3 py-2 text-sm font-mono text-heading placeholder-gray-600 focus:outline-none focus:border-primary-500/30 tabular-nums" />
          </div>
        )}
        {isStop && (
          <div>
            <label className="metric-label block mb-1">Trigger Price (₹)</label>
            <input type="number" step="0.05" value={triggerPrice} onChange={e => setTriggerPrice(e.target.value)}
              className="w-full bg-surface-800/60 border border-edge/10 rounded-lg px-3 py-2 text-sm font-mono text-heading placeholder-gray-600 focus:outline-none focus:border-primary-500/30 tabular-nums" />
          </div>
        )}

        <div className="border-t border-edge/5 pt-2">
          <div className="rounded-xl bg-surface-800/40 border border-edge/5 p-2">
            <div className="h-6 flex items-center justify-between text-xs">
              <span className="text-gray-500">Contract Value</span>
              <span className="font-mono text-heading font-semibold tabular-nums text-right">{formatCurrency(contractValue)}</span>
            </div>
            <div className="h-6 flex items-center justify-between text-xs">
              <span className="text-gray-500">
                Margin{marginInfo ? ` (${marginInfo.margin_percent?.toFixed(1)}%)` : ''}
              </span>
              <span className="font-mono text-heading tabular-nums text-right">{formatCurrency(requiredMargin)}</span>
            </div>
            {marginInfo && (
              <div className="flex items-center gap-2 text-[10px] text-gray-600 mt-0.5 pl-1">
                <span>SPAN: ₹{(marginInfo.span_margin || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
                <span>Exp: ₹{(marginInfo.exposure_margin || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
                {marginInfo.far_expiry_surcharge > 0 && <span className="text-amber-500">+Far</span>}
              </div>
            )}
            <div className="h-6 flex items-center justify-between text-xs">
              <span className="text-gray-500">Available</span>
              <span className="font-mono text-heading tabular-nums text-right">{formatCurrency(margin.availableMargin)}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="px-3 pt-2 pb-2.5 border-t border-edge/5 bg-surface-900 sticky bottom-0">
        <button
          type="button"
          onClick={() => {
            if (!marketOpen) {
              toast.error(closedDetail);
              return;
            }
            placeOrder();
          }}
          disabled={submitting || !selectedContractSym || !marketOpen}
          className={cn('w-full py-2.5 text-base font-bold rounded-lg text-white transition-colors',
            isBuy ? 'bg-bull hover:bg-emerald-600' : 'bg-bear hover:bg-red-600',
            (submitting || !selectedContractSym || !marketOpen) && 'opacity-40 cursor-not-allowed')}>
          {submitting ? 'Placing...' : !marketOpen ? 'Market Closed' : `Place ${side} Order`}
        </button>
        <p className="text-[11px] text-gray-600 text-center mt-2">
          Press <kbd className="bg-surface-700 px-1 rounded text-[10px]">B</kbd> / <kbd className="bg-surface-700 px-1 rounded text-[10px]">S</kbd> to switch
        </p>
      </div>
    </div>
  );
}

// ── BOTTOM DOCK ───────────────────────────────────────────────────────────────
function FuturesBottomDock({ collapsed, onToggleCollapse, onKillSwitch, killSwitchBusy }) {
  const [activeTab, setActiveTab] = useState('positions');
  const positions = useUnifiedFuturesStore((s) => s.positions);
  const orders = useUnifiedFuturesStore((s) => s.orders);
  const quotes = useUnifiedFuturesStore((s) => s.quotes);
  const lastQuoteUpdate = useUnifiedFuturesStore((s) => s._lastQuoteUpdate);

  const totalPnl = useMemo(() => {
    return positions.reduce((sum, pos) => {
      const ltp = quotePrice(quotes[pos.contract_symbol]) ?? Number(pos.ltp);
      if (ltp == null || !Number.isFinite(ltp)) return sum;
      const qty = Number(pos.quantity || 0);
      const avg = Number(pos.avg_entry_price || pos.avg_price || 0);
      return sum + (qty >= 0 ? (ltp - avg) * qty : (avg - ltp) * Math.abs(qty));
    }, 0);
  }, [positions, quotes, lastQuoteUpdate]);

  return (
    <div className="h-full flex flex-col bg-surface-900">
      <div className="flex border-b border-edge/5 flex-shrink-0">
        <button onClick={onToggleCollapse} className="px-2 py-2 text-gray-500 hover:text-heading transition-colors flex-shrink-0" title={collapsed ? 'Expand' : 'Collapse'}>
          <svg className={cn('w-3.5 h-3.5 transition-transform', collapsed ? 'rotate-0' : 'rotate-180')} viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
          </svg>
        </button>
        {[
          { key: 'positions', label: `Positions (${positions.length})` },
          { key: 'orders', label: `Orders (${orders.length})` },
        ].map(({ key, label }) => (
          <button key={key} onClick={() => setActiveTab(key)}
            className={cn('px-4 py-2 text-xs font-semibold uppercase tracking-wider transition-colors',
              activeTab === key ? 'text-primary-600 border-b-2 border-primary-500' : 'text-gray-500 hover:text-gray-700')}>{label}</button>
        ))}
        <div className="ml-auto flex items-center gap-2 px-3">
          {positions.length > 0 && (
            <>
              <button type="button" onClick={onKillSwitch} disabled={killSwitchBusy}
                className={cn('px-2.5 py-1 rounded-md text-[10px] font-bold border border-red-500/30 text-red-500 bg-red-500/10 hover:bg-red-500/20',
                  killSwitchBusy && 'opacity-50 cursor-not-allowed')}
                title="Close all positions and cancel open orders">
                {killSwitchBusy ? 'Closing…' : 'Kill Switch'}
              </button>
              <div className="flex items-center text-xs font-mono tabular-nums">
                <span className="text-gray-500 mr-1">P&L:</span>
                <span className={cn('font-semibold', totalPnl >= 0 ? 'text-bull' : 'text-bear')}>{totalPnl >= 0 ? '+' : ''}{formatCurrency(totalPnl)}</span>
              </div>
            </>
          )}
        </div>
      </div>
      {!collapsed && (
        <div className="overflow-y-auto flex-1 px-3 py-2 bg-surface-900">
          {activeTab === 'positions' && (positions.length > 0 ? (
            <table className="w-full text-xs min-w-[500px]">
              <thead><tr className="text-gray-500 uppercase">
                <th className="text-left pb-2 font-medium metric-label">Contract</th>
                <th className="text-right pb-2 font-medium metric-label">Side</th>
                <th className="text-right pb-2 font-medium metric-label">Qty</th>
                <th className="text-right pb-2 font-medium metric-label">Avg</th>
                <th className="text-right pb-2 font-medium metric-label">LTP</th>
                <th className="text-right pb-2 font-medium metric-label">P&L</th>
              </tr></thead>
              <tbody>{positions.map((pos, i) => {
                const posLtp = quotePrice(quotes[pos.contract_symbol]) ?? Number(pos.ltp);
                const qty = Number(pos.quantity || 0);
                const avg = Number(pos.avg_entry_price || pos.avg_price || 0);
                const pnl = Number.isFinite(posLtp)
                  ? (qty >= 0 ? (posLtp - avg) * qty : (avg - posLtp) * Math.abs(qty))
                  : (pos.unrealized_pnl != null ? Number(pos.unrealized_pnl) : null);
                return (
                  <tr key={pos.id || i} className="border-t border-edge/[0.03] hover:bg-overlay/[0.02]">
                    <td className="py-1.5 font-medium text-heading">{pos.contract_symbol}</td>
                    <td className={cn('py-1.5 text-right font-semibold', qty >= 0 ? 'text-bull' : 'text-bear')}>{qty >= 0 ? 'LONG' : 'SHORT'}</td>
                    <td className="py-1.5 text-right font-mono text-gray-600 tabular-nums">{Math.abs(qty)}</td>
                    <td className="py-1.5 text-right font-mono text-gray-600 tabular-nums">{formatPrice(avg)}</td>
                    <td className="py-1.5 text-right font-mono text-heading tabular-nums">{posLtp != null ? formatPrice(posLtp) : '—'}</td>
                    <td className={cn('py-1.5 text-right font-mono font-medium tabular-nums', pnl == null ? 'text-gray-500' : pnl >= 0 ? 'text-bull' : 'text-bear')}>
                      {pnl != null ? `${pnl >= 0 ? '+' : ''}${formatCurrency(pnl)}` : '—'}</td>
                  </tr>);
              })}</tbody>
            </table>
          ) : <div className="text-center py-6 text-gray-600 text-xs">No open positions.</div>)}

          {activeTab === 'orders' && (orders.length > 0 ? (
            <table className="w-full text-xs min-w-[500px]">
              <thead><tr className="text-gray-500 uppercase">
                <th className="text-left pb-2 font-medium metric-label">Contract</th>
                <th className="text-right pb-2 font-medium metric-label">Side</th>
                <th className="text-right pb-2 font-medium metric-label">Type</th>
                <th className="text-right pb-2 font-medium metric-label">Qty</th>
                <th className="text-right pb-2 font-medium metric-label">Price</th>
                <th className="text-right pb-2 font-medium metric-label">Status</th>
              </tr></thead>
              <tbody>{orders.map((o, i) => (
                <tr key={o.id || i} className="border-t border-edge/[0.03] hover:bg-overlay/[0.02]">
                  <td className="py-1.5 font-medium text-heading">{o.contract_symbol}</td>
                  <td className={cn('py-1.5 text-right font-semibold', o.side === 'BUY' ? 'text-bull' : 'text-bear')}>{o.side}</td>
                  <td className="py-1.5 text-right text-gray-500">{o.order_type}</td>
                  <td className="py-1.5 text-right font-mono text-gray-600 tabular-nums">{o.quantity}</td>
                  <td className="py-1.5 text-right font-mono text-heading tabular-nums">{formatPrice(o.price)}</td>
                  <td className="py-1.5 text-right"><span className={cn('px-1.5 py-0.5 rounded text-[9px] font-bold',
                    o.status === 'FILLED' ? 'bg-emerald-500/15 text-emerald-500' : o.status === 'PENDING' ? 'bg-amber-500/15 text-amber-500' : 'bg-gray-500/15 text-gray-500')}>{o.status}</span></td>
                </tr>))}</tbody>
            </table>
          ) : <div className="text-center py-6 text-gray-600 text-xs">No orders yet.</div>)}
        </div>
      )}
    </div>
  );
}

// ── MAIN PAGE ─────────────────────────────────────────────────────────────────
export default function FuturesPage() {
  const { width } = useResponsive();
  const showIntelligenceSidebar = width >= BREAKPOINTS.xl;

  useFuturesStream();
  const selectContract = useUnifiedFuturesStore((s) => s.selectContract);
  const selectUnderlying = useUnifiedFuturesStore((s) => s.selectUnderlying);
  const setContracts = useUnifiedFuturesStore((s) => s.setContracts);
  const setContractsLoading = useUnifiedFuturesStore((s) => s.setContractsLoading);

  const selectedContract = useUnifiedFuturesStore((s) => s.contracts.selectedContract);
  const positions = useUnifiedFuturesStore((s) => s.positions);
  const contractsLoading = useUnifiedFuturesStore((s) => s.contracts.loading);
  const storedCandles = useUnifiedFuturesStore((s) => s.chart.candles);
  const chartLoading = useUnifiedFuturesStore((s) => s.chart.loading);
  const setCandles = useUnifiedFuturesStore((s) => s.setCandles);
  const setChartLoading = useUnifiedFuturesStore((s) => s.setChartLoading);
  const setChartInterval = useUnifiedFuturesStore((s) => s.setChartInterval);

  const watchlists = useFuturesWatchlistStore((s) => s.watchlists);
  const activeWatchlistId = useFuturesWatchlistStore((s) => s.activeId);
  const addWatchlistItem = useFuturesWatchlistStore((s) => s.addItem);
  const removeWatchlistItem = useFuturesWatchlistStore((s) => s.removeItem);
  const loadFuturesWatchlist = useFuturesWatchlistStore((s) => s.loadWatchlist);

  const liveQuote = useUnifiedFuturesStore((s) =>
    s.contracts.selectedContract ? s.quotes[s.contracts.selectedContract] ?? null : null);

  const [localInterval, setLocalInterval] = useState('5m');
  const [chartLtp, setChartLtp] = useState(null);
  const [watchlistVisible, setWatchlistVisible] = useState(true);
  const [contractsPanelVisible, setContractsPanelVisible] = useState(true);
  const [orderPanelVisible, setOrderPanelVisible] = useState(false);
  const [bottomCollapsed, setBottomCollapsed] = useState(false);
  const [killSwitchBusy, setKillSwitchBusy] = useState(false);
  const [forceOpenAddContract, setForceOpenAddContract] = useState(0);
  const initializedRef = useRef(false);

  const getDefaultOrderPos = useCallback(() => ({
    x: Math.max(16, window.innerWidth - ORDER_FLOAT_WIDTH - 16), y: 72,
  }), []);
  const [orderPanelPos, setOrderPanelPos] = useState(() => getDefaultOrderPos());
  const orderPanelDrag = useRef({ active: false, sx: 0, sy: 0, ox: 0, oy: 0 });

  const clampPos = useCallback((p) => ({
    x: Math.max(0, Math.min(window.innerWidth - ORDER_FLOAT_WIDTH, p.x)),
    y: Math.max(0, Math.min(window.innerHeight - 120, p.y)),
  }), []);

  useEffect(() => {
    const h = () => {
      setOrderPanelPos((p) => {
        const next = clampPos(p);
        if (next.x === p.x && next.y === p.y) return p;
        return next;
      });
    };
    window.addEventListener('resize', h);
    return () => window.removeEventListener('resize', h);
  }, [clampPos]);

  const livePrice = useMemo(() => {
    const n = Number(liveQuote?.ltp ?? liveQuote?.price ?? liveQuote?.lp);
    return Number.isFinite(n) && n > 0 ? n : null;
  }, [liveQuote?.ltp, liveQuote?.price, liveQuote?.lp]);

  // Cumulative session volume from Zebu tick — passed to chart for live candle volume bars
  const liveVolume = useMemo(() => {
    const v = Number(liveQuote?.volume);
    return Number.isFinite(v) && v >= 0 ? v : null;
  }, [liveQuote?.volume]);

  // onPriceUpdate from chart: keeps chartLtp in sync (mirrors terminal page pattern)
  const handleChartPriceUpdate = useCallback((payload) => {
    const source = payload && typeof payload === 'object' ? String(payload.source || 'history').toLowerCase() : 'history';
    const rawPrice = payload && typeof payload === 'object' ? payload.price : payload;
    const priceNum = Number(rawPrice);
    if (!Number.isFinite(priceNum) || priceNum <= 0) {
      if (source === 'reset') setChartLtp(null);
      return;
    }
    if (source === 'live') {
      setChartLtp((prev) => (prev === priceNum ? prev : priceNum));
    }
  }, []);

  // Reset chartLtp when contract changes
  useEffect(() => {
    setChartLtp(null);
  }, [selectedContract]);

  const activeWatchlistItems = useMemo(() => {
    const active = watchlists.find((w) => w.id === activeWatchlistId);
    return active?.items ?? [];
  }, [watchlists, activeWatchlistId]);

  const isCurrentWatchlisted = useMemo(() =>
    selectedContract && activeWatchlistItems.some((w) => w.contract_symbol === selectedContract),
    [selectedContract, activeWatchlistItems]);

  const hasOpenPositions = positions.some((p) => Number(p.quantity) !== 0);

  useEffect(() => {
    loadFuturesWatchlist();
  }, [loadFuturesWatchlist]);

  const refreshOrdersAndPositions = useCallback(async () => {
    const store = useUnifiedFuturesStore.getState();
    try {
      const [ordRes, posRes] = await Promise.allSettled([
        api.get('/futures/orders'),
        api.get('/futures/positions'),
      ]);
      if (ordRes.status === 'fulfilled') store.setOrders(ordRes.value.data?.orders ?? []);
      if (posRes.status === 'fulfilled') store.setPositions(posRes.value.data?.positions ?? []);
    } catch { /* ignore */ }
  }, []);

  const handleKillSwitch = useCallback(async () => {
    if (!confirm('Kill Switch: Close ALL futures positions and cancel open orders?')) return;
    setKillSwitchBusy(true);
    try {
      const res = await api.post('/futures/positions/close-all');
      toast.success(res.data?.message || 'All positions closed');
      await refreshOrdersAndPositions();
    } catch (err) {
      toast.error(err?.response?.data?.detail || err?.message || 'Kill switch failed');
    } finally {
      setKillSwitchBusy(false);
    }
  }, [refreshOrdersAndPositions]);

  const handleSelectUnderlying = useCallback(async (symbol) => {
    const sym = String(symbol || '').toUpperCase().trim();
    if (!sym) return;
    selectUnderlying(sym);
    setContractsLoading(true);
    try {
      const res = await api.get(`/futures/contracts/${sym}`);
      const contracts = res.data?.contracts || [];
      setContracts(sym, contracts);
      if (contracts.length > 0) {
        const first = String(contracts[0].contract_symbol || '').trim().toUpperCase();
        if (first) {
          selectContract(first);
          try {
            await addWatchlistItem(first);
          } catch (watchErr) {
            console.warn('Watchlist add skipped:', watchErr);
          }
        }
      }
    } catch (err) { console.error('Failed to load contracts:', err); }
    finally { setContractsLoading(false); }
  }, [selectUnderlying, setContracts, selectContract, setContractsLoading, addWatchlistItem]);

  // Sorted longest-first so "NIFTYNXT50" matches before "NIFTY" — strict prefix matching
  const KNOWN_UNDERLYINGS = ['NIFTYNXT50', 'MIDCPNIFTY', 'BANKNIFTY', 'FINNIFTY', 'NIFTY', 'SENSEX', 'BANKEX', 'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'SBIN', 'LT', 'ITC', 'BHARTIARTL', 'TATAMOTORS', 'MARUTI', 'BAJFINANCE', 'AXISBANK', 'KOTAKBANK', 'SUNPHARMA'];

  const handleSelectContract = useCallback(async (contractSym) => {
    const sym = String(contractSym || '').trim().toUpperCase();
    if (!sym) return;
    selectContract(sym);

    // Strict prefix match: ensure the character after the underlying is a digit (expiry start)
    const underlying = KNOWN_UNDERLYINGS.find((b) => {
      if (!sym.startsWith(b)) return false;
      const nextChar = sym[b.length];
      return nextChar && nextChar >= '0' && nextChar <= '9';
    });
    if (!underlying) return;

    selectUnderlying(underlying);
    const state = useUnifiedFuturesStore.getState();
    if (state.contracts.byUnderlying[underlying]?.length) return;

    try {
      setContractsLoading(true);
      const res = await api.get(`/futures/contracts/${encodeURIComponent(underlying)}`);
      setContracts(underlying, res.data?.contracts || []);
    } catch {
      // non-fatal
    } finally {
      setContractsLoading(false);
    }
  }, [selectContract, selectUnderlying, setContracts, setContractsLoading]);

  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    handleSelectUnderlying('NIFTY');
  }, []);

  const fetchHistory = useCallback(async (contractSym, interval) => {
    if (!contractSym) return;
    const apiInterval = intervalApiMap[interval] || '5m';
    const cacheKey = futuresCandleCacheKey(contractSym, apiInterval);
    const cached = getCachedFuturesCandles(contractSym, apiInterval);
    if (cached?.length) {
      setCandles(cached);
      setChartLoading(false);
    } else {
      setChartLoading(true);
    }
    try {
      const res = await api.get(`/futures/history/${encodeURIComponent(contractSym)}`, {
        params: { interval: apiInterval, limit: 500 },
      });
      const rows = res.data?.candles || res.data?.data || res.data || [];
      const normalized = normalizeCandles(rows);
      if (normalized.length > 0) {
        _futuresCandleCache.set(cacheKey, { candles: normalized, ts: Date.now() });
        setCandles(normalized);
      } else if (!cached?.length) {
        const stale = _futuresCandleCache.get(cacheKey)?.candles;
        if (stale?.length) setCandles(stale);
      }
    } catch {
      const stale = getCachedFuturesCandles(contractSym, apiInterval)
        ?? _futuresCandleCache.get(cacheKey)?.candles;
      if (stale?.length) setCandles(stale);
    } finally {
      setChartLoading(false);
    }
  }, [setCandles, setChartLoading]);

  useEffect(() => {
    if (selectedContract) fetchHistory(selectedContract, localInterval);
  }, [selectedContract, localInterval, fetchHistory]);

  const handleIntervalChange = useCallback((key) => {
    setLocalInterval(key);
    setChartInterval(intervalApiMap[key] || '5m');
  }, [setChartInterval]);

  const handleToggleWatchlist = useCallback(async () => {
    if (!selectedContract) return;
    if (isCurrentWatchlisted) {
      const item = activeWatchlistItems.find((w) => w.contract_symbol === selectedContract);
      if (item?.id) await removeWatchlistItem(item.id);
    } else {
      await addWatchlistItem(selectedContract);
    }
  }, [selectedContract, isCurrentWatchlisted, activeWatchlistItems, addWatchlistItem, removeWatchlistItem]);

  const handleOrderPanelGrab = useCallback((event) => {
    if (event.target.closest('button') || event.target.closest('input') || event.target.closest('select')) return;
    event.preventDefault();
    orderPanelDrag.current = { active: true, sx: event.clientX, sy: event.clientY, ox: orderPanelPos.x, oy: orderPanelPos.y };
    const onMove = (e) => {
      if (!orderPanelDrag.current.active) return;
      setOrderPanelPos(clampPos({ x: orderPanelDrag.current.ox + (e.clientX - orderPanelDrag.current.sx), y: orderPanelDrag.current.oy + (e.clientY - orderPanelDrag.current.sy) }));
    };
    const onUp = () => { orderPanelDrag.current.active = false; document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }, [orderPanelPos, clampPos]);

  const openOrderPanel = useCallback(() => {
    setOrderPanelPos(clampPos(getDefaultOrderPos()));
    setOrderPanelVisible(true);
  }, [clampPos, getDefaultOrderPos]);

  const closeOrderPanel = useCallback(() => {
    setOrderPanelVisible(false);
  }, []);

  useResponsiveTradeBridge({ onOpenOrderPanel: openOrderPanel });

  const toggleContractsPanel = useCallback(() => {
    setContractsPanelVisible((v) => !v);
    setTimeout(() => window.dispatchEvent(new Event('resize')), 250);
  }, []);

  const rightPanelOpen = contractsPanelVisible && showIntelligenceSidebar;

  return (
    <div
      className={cn(
        'terminal-grid h-[calc(100vh-56px-36px)]',
        !rightPanelOpen && 'terminal-grid--no-right',
        !watchlistVisible && 'terminal-grid--no-watchlist',
      )}
    >
      {/* WATCHLIST */}
      {watchlistVisible && (
        <ResizablePanel side="left" defaultSize={320} minSize={260} maxSize={480}
          className="terminal-area-watchlist hidden lg:flex min-h-0 overflow-hidden">
          <FuturesWatchlist
            selectedContractSymbol={selectedContract}
            onSelectContract={handleSelectContract}
            onUnderlyingSelected={handleSelectUnderlying}
            forceOpenAddContractToken={forceOpenAddContract}
          />
        </ResizablePanel>
      )}

      {/* CHART HEADER */}
      <div className="terminal-area-header min-w-0 flex items-center">
        {/* Watchlist toggle button — exactly like terminal */}
        <button
          onClick={() => { setWatchlistVisible(v => !v); setTimeout(() => window.dispatchEvent(new Event('resize')), 250); }}
          className={cn('flex-shrink-0 p-1.5 ml-1 rounded-md transition-all duration-200 text-slate-400 hover:text-heading hover:bg-overlay/[0.06]',
            !watchlistVisible && 'text-primary-500 bg-primary-500/10')}
          title={watchlistVisible ? 'Hide watchlist' : 'Show watchlist'}>
          {watchlistVisible ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeftOpen className="w-4 h-4" />}
        </button>
        <div className="flex-1 min-w-0">
          <FuturesChartHeader
            interval={localInterval}
            onIntervalChange={handleIntervalChange}
            isWatchlisted={isCurrentWatchlisted}
            onToggleWatchlist={handleToggleWatchlist}
            orderPanelVisible={orderPanelVisible}
            onToggleOrderPanel={() => orderPanelVisible ? closeOrderPanel() : openOrderPanel()}
            hasPositions={hasOpenPositions}
            onKillSwitch={handleKillSwitch}
            killSwitchBusy={killSwitchBusy}
          />
        </div>
        {/* Analytics / expiry ladder toggle — mirrors watchlist (desktop xl+) */}
        {showIntelligenceSidebar && (
          <button
            type="button"
            onClick={toggleContractsPanel}
            className={cn(
              'flex-shrink-0 p-1.5 mr-1 rounded-md transition-all duration-200 text-slate-400 hover:text-heading hover:bg-overlay/[0.06]',
              !contractsPanelVisible && 'text-primary-500 bg-primary-500/10',
            )}
            title={contractsPanelVisible ? 'Hide analytics panel' : 'Show analytics panel'}
            aria-expanded={contractsPanelVisible}
            aria-label={contractsPanelVisible ? 'Hide analytics panel' : 'Show analytics panel'}
          >
            {contractsPanelVisible ? (
              <PanelRightClose className="w-4 h-4" />
            ) : (
              <PanelRightOpen className="w-4 h-4" />
            )}
          </button>
        )}
      </div>

      {/* CHART */}
      <div className="terminal-area-chart min-w-0 min-h-0 relative overflow-hidden">
        <ErrorBoundary fallback="Chart failed to load. Please refresh.">
          {selectedContract ? (
            <ZebuLiveChart
              key={selectedContract}
              candles={storedCandles}
              isLoading={chartLoading || contractsLoading}
              symbol={selectedContract}
              period={localInterval}
              onPeriodChange={handleIntervalChange}
              livePrice={livePrice}
              liveVolume={liveVolume}
              isolateLivePrice
              onPriceUpdate={handleChartPriceUpdate}
            />
          ) : (
            <div className="h-full flex items-center justify-center text-sm text-gray-500">
              {contractsLoading ? 'Loading contracts…' : 'Select a futures contract to begin'}
            </div>
          )}
        </ErrorBoundary>
      </div>

      {/* BOTTOM DOCK */}
      <div className="terminal-area-bottom min-w-0 transition-all duration-200"
        style={{ height: bottomCollapsed ? '32px' : '200px' }}>
        <FuturesBottomDock
          collapsed={bottomCollapsed}
          onToggleCollapse={() => setBottomCollapsed((v) => !v)}
          onKillSwitch={handleKillSwitch}
          killSwitchBusy={killSwitchBusy}
        />
      </div>

      {/* RIGHT SIDEBAR — Futures Intelligence + Expiry Ladder (desktop xl+ only) */}
      {rightPanelOpen && (
        <ResizablePanel side="right" defaultSize={300} minSize={240} maxSize={420}
          className="terminal-area-orders hidden xl:flex min-h-0 overflow-hidden">
          <ErrorBoundary fallback="Analytics panel unavailable. Chart and trading still work.">
            <FuturesRightSidebar onSelectContract={handleSelectContract} />
          </ErrorBoundary>
        </ResizablePanel>
      )}

      {/* FLOATING ORDER PANEL — same as terminal */}
      {orderPanelVisible && (
        <div
          className="fixed z-50 hidden lg:flex flex-col rounded-2xl select-none bg-surface-900/95 border border-edge/10 shadow-2xl shadow-black/40 overflow-visible"
          style={{ left: orderPanelPos.x, top: orderPanelPos.y, width: ORDER_FLOAT_WIDTH, maxHeight: 'calc(100vh - 140px)', backdropFilter: 'blur(24px)' }}>
          <div onMouseDown={handleOrderPanelGrab}
            className="h-8 px-3 flex items-center justify-between cursor-move border-b border-edge/10 flex-shrink-0">
            <span className="text-[11px] font-semibold text-heading">Order Panel</span>
            <button onClick={closeOrderPanel}
              className="w-5 h-5 rounded-md flex items-center justify-center text-gray-500 hover:text-heading hover:bg-surface-800 transition-all duration-150" title="Close">
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto rounded-b-2xl">
            <FuturesOrderPanel onClose={closeOrderPanel} />
          </div>
        </div>
      )}
    </div>
  );
}
