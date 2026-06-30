import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ChevronDown, Search } from 'lucide-react';
import { cn } from '../../utils/cn';
import {
  formatZebuOi,
  formatZebuPctParen,
  formatZebuPrice,
  isZebuChainSource,
  oiChangePercent,
} from '../options/formatZebuValue';
import { formatExpiryChip, OPTIONS_UNDERLYINGS } from '../options/constants';
import '../options/options-chain.css';

const ROW_H = 48;
const SPOT_ROW_H = 30;

const UNDERLYING_LABEL = {
  NIFTY: 'Nifty 50',
  BANKNIFTY: 'Bank Nifty',
  FINNIFTY: 'Fin Nifty',
  MIDCPNIFTY: 'Midcap Nifty',
  NIFTYNXT50: 'Nifty Next 50',
  SENSEX: 'Sensex',
};

function formatStrike(strike) {
  const n = Number(strike);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function MetricCell({ label, value, subValue, subUp, onClick, align = 'center', itmClass }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn('oc-metric-btn', itmClass)}
      style={{ textAlign: align }}
    >
      {label && <span className="sr-only">{label}</span>}
      <span className="oc-value tabular-nums">{value}</span>
      {subValue && subValue !== '—' && (
        <span className={cn('oc-sub tabular-nums', subUp ? 'oc-bull' : 'oc-bear')}>{subValue}</span>
      )}
    </button>
  );
}

function CallSide({ data, strike, selected, source, onSelect, spotPrice }) {
  const oiPct = oiChangePercent(data.oi, data.oiChange);
  const ltpPct = data.changePct == null ? null : Number(data.changePct);
  const itm = Number.isFinite(spotPrice) && spotPrice > 0 && strike < spotPrice;
  const itmClass = itm ? 'oc-itm-call' : undefined;

  return (
    <div className={cn('group relative grid grid-cols-2 h-full min-h-0', selected && 'ring-1 ring-inset ring-primary-500/25')}>
      <MetricCell
        value={formatZebuOi(data.oi, { source })}
        subValue={oiPct != null ? formatZebuPctParen(oiPct, { source }) : null}
        subUp={oiPct != null && oiPct >= 0}
        onClick={() => onSelect(strike, 'CE', { ...data, side: 'BUY' })}
        itmClass={itmClass}
      />
      <MetricCell
        value={formatZebuPrice(data.ltp, { source, noFallback: true })}
        subValue={Number.isFinite(ltpPct) ? formatZebuPctParen(ltpPct, { source }) : null}
        subUp={Number.isFinite(ltpPct) && ltpPct >= 0}
        onClick={() => onSelect(strike, 'CE', { ...data, side: 'BUY' })}
        itmClass={itmClass}
      />
      <div className="pointer-events-none absolute inset-0 hidden group-hover:flex items-center justify-center gap-1">
        <button
          type="button"
          onMouseDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onSelect(strike, 'CE', { ...data, side: 'BUY' });
          }}
          className="pointer-events-auto px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-600 text-white"
        >
          B
        </button>
        <button
          type="button"
          onMouseDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onSelect(strike, 'CE', { ...data, side: 'SELL' });
          }}
          className="pointer-events-auto px-2 py-0.5 rounded text-[10px] font-semibold bg-red-600 text-white"
        >
          S
        </button>
      </div>
    </div>
  );
}

function PutSide({ data, strike, selected, source, onSelect, spotPrice }) {
  const oiPct = oiChangePercent(data.oi, data.oiChange);
  const ltpPct = data.changePct == null ? null : Number(data.changePct);
  const itm = Number.isFinite(spotPrice) && spotPrice > 0 && strike > spotPrice;
  const itmClass = itm ? 'oc-itm-put' : undefined;

  return (
    <div className={cn('group relative grid grid-cols-2 h-full min-h-0', selected && 'ring-1 ring-inset ring-primary-500/25')}>
      <MetricCell
        value={formatZebuPrice(data.ltp, { source, noFallback: true })}
        subValue={Number.isFinite(ltpPct) ? formatZebuPctParen(ltpPct, { source }) : null}
        subUp={Number.isFinite(ltpPct) && ltpPct >= 0}
        onClick={() => onSelect(strike, 'PE', { ...data, side: 'BUY' })}
        itmClass={itmClass}
      />
      <MetricCell
        value={formatZebuOi(data.oi, { source })}
        subValue={oiPct != null ? formatZebuPctParen(oiPct, { source }) : null}
        subUp={oiPct != null && oiPct >= 0}
        onClick={() => onSelect(strike, 'PE', { ...data, side: 'BUY' })}
        itmClass={itmClass}
      />
      <div className="pointer-events-none absolute inset-0 hidden group-hover:flex items-center justify-center gap-1">
        <button
          type="button"
          onMouseDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onSelect(strike, 'PE', { ...data, side: 'BUY' });
          }}
          className="pointer-events-auto px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-600 text-white"
        >
          B
        </button>
        <button
          type="button"
          onMouseDown={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onSelect(strike, 'PE', { ...data, side: 'SELL' });
          }}
          className="pointer-events-auto px-2 py-0.5 rounded text-[10px] font-semibold bg-red-600 text-white"
        >
          S
        </button>
      </div>
    </div>
  );
}

const ChainRow = memo(function ChainRow({
  row,
  spotPrice,
  selectedStrike,
  selectedType,
  source,
  onSelectOption,
  style,
}) {
  const selectedCe = selectedStrike === row.strike && selectedType === 'CE';
  const selectedPe = selectedStrike === row.strike && selectedType === 'PE';
  const rowSelected = selectedStrike === row.strike;

  return (
    <div
      className={cn(
        'grid grid-cols-[1fr_72px_1fr] items-stretch border-b border-edge/[0.06] dark:border-white/[0.05]',
        rowSelected && 'oc-row-selected',
      )}
      style={{ ...style, height: `${ROW_H}px` }}
    >
      <CallSide
        data={row.ce}
        strike={row.strike}
        selected={selectedCe}
        source={source}
        onSelect={onSelectOption}
        spotPrice={spotPrice}
      />
      <div className="flex items-center justify-center border-x border-edge/10 dark:border-white/[0.08] bg-surface-800/20 dark:bg-black/15">
        <span className="oc-strike">{formatStrike(row.strike)}</span>
      </div>
      <PutSide
        data={row.pe}
        strike={row.strike}
        selected={selectedPe}
        source={source}
        onSelect={onSelectOption}
        spotPrice={spotPrice}
      />
    </div>
  );
});

function SpotDividerRow({ spotPrice, style }) {
  const label = formatZebuPrice(spotPrice, { source: 'zebu', allowZero: true });
  return (
    <div
      className="relative flex items-center justify-center border-b border-edge/[0.06]"
      style={{ ...style, height: `${SPOT_ROW_H}px` }}
    >
      <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 oc-spot-line" aria-hidden />
      <span className="relative z-[1] oc-spot-pill">{label}</span>
    </div>
  );
}

function buildVirtualItems(chain, spotPrice) {
  const sorted = [...chain].sort((a, b) => a.strike - b.strike);
  const items = [];
  const spot = Number(spotPrice);
  const hasSpot = Number.isFinite(spot) && spot > 0;

  for (let i = 0; i < sorted.length; i++) {
    const row = sorted[i];
    const next = sorted[i + 1];
    items.push({ type: 'row', key: `row-${row.strike}`, row });
    if (hasSpot && spot > row.strike && (next == null || spot < next.strike)) {
      items.push({ type: 'spot', key: `spot-${row.strike}` });
    }
  }
  return items;
}

function OptionChainCompact({
  chain = [],
  spotPrice = 0,
  selectedStrike,
  selectedType,
  onSelectOption,
  scrollToStrike,
  loading,
  source = 'zebu',
  selectedUnderlying = 'NIFTY',
  onSelectUnderlying,
  expiryList = [],
  selectedExpiry,
  onSelectExpiry,
}) {
  const parentRef = useRef(null);
  const [underlyingQuery, setUnderlyingQuery] = useState(selectedUnderlying || '');
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [expiryOpen, setExpiryOpen] = useState(false);
  const expiryRef = useRef(null);
  const zebuLive = true;

  const virtualItems = useMemo(() => buildVirtualItems(chain, spotPrice), [chain, spotPrice]);

  const rowVirtualizer = useVirtualizer({
    count: virtualItems.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => (virtualItems[index]?.type === 'spot' ? SPOT_ROW_H : ROW_H),
    overscan: 8,
    paddingEnd: 14,
  });

  useEffect(() => {
    const key = String(selectedUnderlying || '').toUpperCase();
    setUnderlyingQuery(UNDERLYING_LABEL[key] || selectedUnderlying || '');
  }, [selectedUnderlying]);

  useEffect(() => {
    if (!expiryOpen) return;
    const close = (e) => {
      if (expiryRef.current && !expiryRef.current.contains(e.target)) setExpiryOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [expiryOpen]);

  useEffect(() => {
    if (scrollToStrike == null || !chain.length) return;
    const idx = virtualItems.findIndex((it) => it.type === 'row' && it.row?.strike === scrollToStrike);
    if (idx >= 0) rowVirtualizer.scrollToIndex(idx, { align: 'center' });
  }, [scrollToStrike, virtualItems, rowVirtualizer, chain.length]);

  const commitUnderlying = () => {
    const raw = String(underlyingQuery || '').trim().toUpperCase();
    if (!raw) return;
    const match = OPTIONS_UNDERLYINGS.find((u) => u.startsWith(raw) || u === raw);
    onSelectUnderlying?.(match || raw.replace(/\.(NS|NSE)$/i, ''));
    setSuggestOpen(false);
  };

  const suggestionList = useMemo(() => {
    const q = String(underlyingQuery || '').trim().toUpperCase();
    if (!q) return OPTIONS_UNDERLYINGS;
    return OPTIONS_UNDERLYINGS.filter((u) => u.includes(q));
  }, [underlyingQuery]);

  const expiryLabel = selectedExpiry
    ? new Date(selectedExpiry).toLocaleDateString('en-GB', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
      }).replace(/ /g, '-').toUpperCase()
    : 'Expiry';

  if (loading && !chain.length) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-gray-500 animate-pulse p-4">
        Loading chain…
      </div>
    );
  }

  if (!zebuLive) {
    return (
      <div className="h-full flex items-center justify-center text-center p-4 text-xs text-gray-500">
        Option chain not available for this underlying
      </div>
    );
  }

  if (!chain.length) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-gray-500 p-4">
        No strikes available
      </div>
    );
  }

  return (
    <div className="option-chain-broker flex flex-col h-full min-h-0 bg-surface-900 dark:bg-surface-950">
      <div className="flex-shrink-0 flex items-center gap-2 px-2 py-2 border-b border-edge/10">
        <div className="relative flex-1 min-w-0">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500 pointer-events-none" />
          <input
            type="text"
            value={underlyingQuery}
            onChange={(e) => setUnderlyingQuery(e.target.value)}
            onFocus={() => setSuggestOpen(true)}
            onKeyDown={(e) => e.key === 'Enter' && commitUnderlying()}
            onBlur={() => setTimeout(() => setSuggestOpen(false), 120)}
            className="w-full pl-7 pr-2 py-1.5 text-[11px] rounded-md bg-surface-800 border border-edge/15 text-heading placeholder:text-gray-500 focus:outline-none focus:border-primary-500/40"
            aria-label="Underlying"
          />
          {suggestOpen && suggestionList.length > 0 && (
            <div className="absolute left-0 right-0 top-full mt-1 z-40 rounded-md border border-edge/15 bg-white dark:bg-surface-900 shadow-lg max-h-56 overflow-y-auto">
              {suggestionList.map((u) => (
                <button
                  key={u}
                  type="button"
                  onMouseDown={() => {
                    setUnderlyingQuery(UNDERLYING_LABEL[u] || u);
                    onSelectUnderlying?.(u);
                    setSuggestOpen(false);
                  }}
                  className="w-full px-3 py-2 text-left text-[12px] text-slate-800 dark:text-slate-100 hover:bg-slate-100 dark:hover:bg-white/10"
                >
                  {UNDERLYING_LABEL[u] || u}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="relative flex-shrink-0" ref={expiryRef}>
          <button
            type="button"
            onClick={() => setExpiryOpen((v) => !v)}
            className="flex items-center gap-1 px-2 py-1.5 text-[11px] rounded-md border border-edge/15 bg-surface-800 text-slate-900 dark:text-slate-100 min-w-[108px] justify-between"
          >
            <span className="truncate tabular-nums">{expiryLabel}</span>
            <ChevronDown className={cn('w-3.5 h-3.5 flex-shrink-0 transition-transform', expiryOpen && 'rotate-180')} />
          </button>
          {expiryOpen && expiryList.length > 0 && (
            <div className="absolute right-0 top-full mt-1 z-30 min-w-[140px] max-h-48 overflow-y-auto rounded-md border border-edge/15 bg-white dark:bg-surface-900 shadow-lg py-1">
              {expiryList.map((exp) => (
                <button
                  key={exp}
                  type="button"
                  onClick={() => {
                    onSelectExpiry?.(exp);
                    setExpiryOpen(false);
                  }}
                  className={cn(
                    'w-full text-left px-3 py-1.5 text-[12px] text-slate-800 dark:text-slate-100 hover:bg-slate-100 dark:hover:bg-white/10',
                    exp === selectedExpiry && 'bg-primary-600/15 text-primary-500',
                  )}
                >
                  {formatExpiryChip(exp)}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="flex-shrink-0 grid grid-cols-[1fr_72px_1fr] border-b border-edge/10 bg-surface-800/30">
        <div className="py-2 text-center border-r border-edge/10">
          <div className="oc-label text-emerald-600 dark:text-emerald-400">Calls</div>
          <div className="grid grid-cols-2 mt-1 gap-0">
            <span className="oc-label">OI (OI ch)</span>
            <span className="oc-label">LTP (CH)</span>
          </div>
        </div>
        <div className="py-2 flex items-center justify-center border-x border-edge/10">
          <span className="oc-label">Strikes</span>
        </div>
        <div className="py-2 text-center border-l border-edge/10">
          <div className="oc-label text-red-600 dark:text-red-400">Puts</div>
          <div className="grid grid-cols-2 mt-1 gap-0">
            <span className="oc-label">LTP (CH)</span>
            <span className="oc-label">OI (OI ch)</span>
          </div>
        </div>
      </div>

      <div
        ref={parentRef}
        className="flex-1 min-h-0 overflow-y-auto oc-scroll overscroll-y-contain touch-pan-y"
        style={{ WebkitOverflowScrolling: 'touch' }}
      >
        <div style={{ height: rowVirtualizer.getTotalSize() + 14, position: 'relative' }}>
          {rowVirtualizer.getVirtualItems().map((vRow) => {
            const item = virtualItems[vRow.index];
            if (item.type === 'spot') {
              return (
                <SpotDividerRow
                  key={item.key}
                  spotPrice={spotPrice}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    transform: `translateY(${vRow.start}px)`,
                  }}
                />
              );
            }
            return (
              <ChainRow
                key={item.key}
                row={item.row}
                spotPrice={spotPrice}
                selectedStrike={selectedStrike}
                selectedType={selectedType}
                source={source}
                onSelectOption={onSelectOption}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${vRow.start}px)`,
                }}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default memo(OptionChainCompact);
