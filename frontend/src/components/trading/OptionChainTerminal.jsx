import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { cn } from '../../utils/cn';
import { formatPrice } from '../../utils/formatters';
import { computeChainHeatmap, findAtmStrike } from '../../utils/optionsAnalytics';

const ROW_HEIGHT = 38;
const GRID_COLS =
  'minmax(52px,1fr) minmax(48px,1fr) minmax(48px,1fr) minmax(40px,1fr) minmax(40px,1fr) minmax(56px,1fr) minmax(44px,1fr) minmax(44px,1fr) 72px minmax(44px,1fr) minmax(44px,1fr) minmax(56px,1fr) minmax(40px,1fr) minmax(40px,1fr) minmax(48px,1fr) minmax(48px,1fr) minmax(52px,1fr)';

const ChainRow = memo(function ChainRow({
  row,
  spotPrice,
  atmStrike,
  selectedStrike,
  selectedType,
  heat,
  flashCe,
  flashPe,
  onSelectOption,
  onContextMenu,
  style,
}) {
  const ceItm = row.strike < spotPrice;
  const peItm = row.strike > spotPrice;
  const isAtm = row.strike === atmStrike;
  const oiCeBg = heat.maxOi > 0 ? (row.ce.oi || 0) / heat.maxOi : 0;
  const oiPeBg = heat.maxOi > 0 ? (row.pe.oi || 0) / heat.maxOi : 0;

  const ceCells = [
    { k: 'oi', v: (row.ce.oi || 0).toLocaleString('en-IN'), bg: `rgba(16,185,129,${oiCeBg * 0.15})` },
    { k: 'oiChg', v: `${row.ce.oiChange >= 0 ? '+' : ''}${(row.ce.oiChange || 0).toLocaleString('en-IN')}`, cls: row.ce.oiChange >= 0 ? 'text-profit' : 'text-loss' },
    { k: 'vol', v: (row.ce.volume || 0).toLocaleString('en-IN') },
    { k: 'iv', v: formatPrice(row.ce.iv) },
    { k: 'd', v: formatPrice(row.ce.delta) },
    { k: 'ltp', v: formatPrice(row.ce.ltp), ltp: true, side: 'CE' },
    { k: 'bid', v: formatPrice(row.ce.bid) },
    { k: 'ask', v: formatPrice(row.ce.ask) },
  ];

  const peCells = [
    { k: 'bid', v: formatPrice(row.pe.bid) },
    { k: 'ask', v: formatPrice(row.pe.ask) },
    { k: 'ltp', v: formatPrice(row.pe.ltp), ltp: true, side: 'PE' },
    { k: 'd', v: formatPrice(row.pe.delta) },
    { k: 'iv', v: formatPrice(row.pe.iv) },
    { k: 'vol', v: (row.pe.volume || 0).toLocaleString('en-IN') },
    { k: 'oiChg', v: `${row.pe.oiChange >= 0 ? '+' : ''}${(row.pe.oiChange || 0).toLocaleString('en-IN')}`, cls: row.pe.oiChange >= 0 ? 'text-profit' : 'text-loss' },
    { k: 'oi', v: (row.pe.oi || 0).toLocaleString('en-IN'), bg: `rgba(239,68,68,${oiPeBg * 0.15})` },
  ];

  const renderCell = (c, side) => {
    const data = side === 'CE' ? row.ce : row.pe;
    const itm = side === 'CE' ? ceItm : peItm;
    const flash = side === 'CE' ? flashCe : flashPe;
    return (
      <div
        key={`${side}-${c.k}`}
        role="gridcell"
        className={cn(
          'px-1 py-1 text-right font-mono tabular-nums text-[11px] truncate',
          itm && (side === 'CE' ? 'bg-emerald-500/[0.04]' : 'bg-red-500/[0.04]'),
          c.ltp && 'font-semibold text-heading cursor-pointer hover:text-primary-600',
          c.ltp && selectedStrike === row.strike && selectedType === side && 'ring-1 ring-inset ring-primary-500/40 rounded-sm',
          flash && c.ltp && 'bg-primary-500/10',
          c.cls,
        )}
        style={c.bg ? { backgroundColor: c.bg } : undefined}
        onClick={
          c.ltp
            ? () => onSelectOption?.(row.strike, side, { ...data, side: 'BUY' })
            : undefined
        }
        onContextMenu={
          c.ltp
            ? (e) => {
                e.preventDefault();
                onContextMenu?.(e, row.strike, side, data);
              }
            : undefined
        }
      >
        {c.v}
      </div>
    );
  };

  return (
    <div
      role="row"
      className={cn(
        'grid border-b border-edge/[0.02] hover:bg-overlay/[0.02] transition-colors',
        isAtm && 'bg-primary-600/12',
        selectedStrike === row.strike && 'bg-overlay/[0.04]',
      )}
      style={{ ...style, gridTemplateColumns: GRID_COLS }}
    >
      {ceCells.map((c) => renderCell(c, 'CE'))}
      <div
        role="gridcell"
        className={cn(
          'flex flex-col items-center justify-center font-mono font-bold text-[11px] border-x border-primary-500/25',
          isAtm ? 'text-primary-600 bg-primary-600/10' : 'text-heading bg-primary-600/5',
        )}
      >
        {row.strike}
        {isAtm && <span className="text-[7px] uppercase text-primary-500/70">ATM</span>}
      </div>
      {peCells.map((c) => renderCell(c, 'PE'))}
    </div>
  );
});

function OptionChainTerminal({
  chain = [],
  spotPrice = 0,
  selectedStrike,
  selectedType,
  onSelectOption,
  onContextAction,
  scrollToStrike,
  loading,
}) {
  const parentRef = useRef(null);
  const prevLtpRef = useRef(new Map());
  const [flashKeys, setFlashKeys] = useState(new Set());
  const [menu, setMenu] = useState(null);

  const atmStrike = useMemo(() => findAtmStrike(chain, spotPrice), [chain, spotPrice]);
  const heat = useMemo(() => computeChainHeatmap(chain), [chain]);

  const rowVirtualizer = useVirtualizer({
    count: chain.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 10,
  });

  useEffect(() => {
    const nextFlash = new Set();
    const prev = prevLtpRef.current;
    for (const row of chain) {
      for (const side of ['CE', 'PE']) {
        const key = `${row.strike}-${side}`;
        const ltp = side === 'CE' ? row.ce.ltp : row.pe.ltp;
        const old = prev.get(key);
        if (old != null && old !== ltp) nextFlash.add(key);
        prev.set(key, ltp);
      }
    }
    if (nextFlash.size) {
      setFlashKeys(nextFlash);
      const t = setTimeout(() => setFlashKeys(new Set()), 350);
      return () => clearTimeout(t);
    }
  }, [chain]);

  useEffect(() => {
    if (scrollToStrike == null || !chain.length) return;
    const idx = chain.findIndex((r) => r.strike === scrollToStrike);
    if (idx >= 0) rowVirtualizer.scrollToIndex(idx, { align: 'center' });
  }, [scrollToStrike, chain.length, rowVirtualizer]);

  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, [menu]);

  const openContextMenu = useCallback((event, strike, optionType, data) => {
    setMenu({ x: event.clientX, y: event.clientY, strike, optionType, data });
  }, []);

  const runContextAction = (action) => {
    if (!menu) return;
    if ((action === 'BUY' || action === 'SELL') && menu.optionType) {
      onSelectOption?.(menu.strike, menu.optionType, { ...menu.data, side: action });
    }
    if (action === 'WATCHLIST') onContextAction?.({ action: 'WATCHLIST', strike: menu.strike });
    setMenu(null);
  };

  if (loading && !chain.length) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-gray-500 animate-pulse border-t border-edge/5">
        Loading option chain…
      </div>
    );
  }

  if (!chain.length) {
    return (
      <div className="h-full flex items-center justify-center text-xs text-gray-500 border-t border-edge/5">
        No chain data
      </div>
    );
  }

  const headers = [
    'OI', 'OI Δ', 'Vol', 'IV', 'Δ', 'LTP', 'Bid', 'Ask', 'STRIKE', 'Bid', 'Ask', 'LTP', 'Δ', 'IV', 'Vol', 'OI Δ', 'OI',
  ];

  return (
    <div className="flex flex-col h-full min-h-0 border-t border-edge/5 bg-surface-900/40" role="grid" aria-label="Option chain">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-edge/5 flex-shrink-0 bg-surface-900/60">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-gray-500">Options Chain</span>
        <span className="text-[10px] text-gray-600 font-mono">
          Spot ₹{formatPrice(spotPrice)} · ATM {atmStrike ?? '—'}
        </span>
      </div>

      <div
        className="grid flex-shrink-0 border-b border-edge/5 bg-surface-900/98 text-[10px] font-medium uppercase tracking-wider text-gray-500 sticky top-0 z-10"
        style={{ gridTemplateColumns: GRID_COLS }}
      >
        {headers.map((h) => (
          <div
            key={h}
            className={cn(
              'py-2 px-1',
              h === 'STRIKE' ? 'text-center text-primary-600 border-x border-primary-500/20' : 'text-right',
            )}
          >
            {h}
          </div>
        ))}
      </div>

      <div ref={parentRef} className="flex-1 min-h-0 overflow-auto overscroll-contain min-w-[1280px]">
        <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative', width: '100%' }}>
          {rowVirtualizer.getVirtualItems().map((vRow) => {
            const row = chain[vRow.index];
            return (
              <ChainRow
                key={row.strike}
                row={row}
                spotPrice={spotPrice}
                atmStrike={atmStrike}
                selectedStrike={selectedStrike}
                selectedType={selectedType}
                heat={heat}
                flashCe={flashKeys.has(`${row.strike}-CE`)}
                flashPe={flashKeys.has(`${row.strike}-PE`)}
                onSelectOption={onSelectOption}
                onContextMenu={openContextMenu}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: `${vRow.size}px`,
                  transform: `translateY(${vRow.start}px)`,
                }}
              />
            );
          })}
        </div>
      </div>

      {menu && (
        <div
          className="fixed z-[80] min-w-[140px] rounded-lg border border-edge/10 bg-surface-800 shadow-panel py-1"
          style={{ left: menu.x, top: menu.y }}
        >
          <button type="button" onClick={() => runContextAction('BUY')} className="w-full text-left px-3 py-1.5 text-xs text-bull hover:bg-overlay/[0.06]">
            BUY
          </button>
          <button type="button" onClick={() => runContextAction('SELL')} className="w-full text-left px-3 py-1.5 text-xs text-bear hover:bg-overlay/[0.06]">
            SELL
          </button>
          <button type="button" onClick={() => runContextAction('WATCHLIST')} className="w-full text-left px-3 py-1.5 text-xs text-gray-400 hover:bg-overlay/[0.06]">
            Watchlist
          </button>
        </div>
      )}
    </div>
  );
}

export default memo(OptionChainTerminal);
