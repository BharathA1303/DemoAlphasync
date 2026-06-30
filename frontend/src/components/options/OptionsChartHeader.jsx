import { memo, useState, useRef, useEffect } from 'react';
import { cn } from '../../utils/cn';
import { formatPrice } from '../../utils/formatters';
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react';

const CHART_INTERVALS = [
  { key: '1m', label: '1m' },
  { key: '5m', label: '5m' },
  { key: '15m', label: '15m' },
  { key: '1H', label: '1H' },
  { key: '1D', label: '1D' },
];

function OptionsChartHeader({
  displaySymbol,
  metaLine,
  ltp,
  change,
  changePct,
  optionType,
  interval,
  onIntervalChange,
  chainPanelVisible,
  onToggleChainPanel,
  rightPanelVisible,
  onToggleRightPanel,
  showRightToggle,
  orderPanelVisible,
  onToggleOrderPanel,
  greeksMini,
}) {
  const [periodOpen, setPeriodOpen] = useState(false);
  const periodRef = useRef(null);

  useEffect(() => {
    if (!periodOpen) return;
    const h = (e) => {
      if (periodRef.current && !periodRef.current.contains(e.target)) setPeriodOpen(false);
    };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [periodOpen]);

  const currentLabel = CHART_INTERVALS.find((i) => i.key === interval)?.label ?? interval;
  const isCe = optionType === 'CE';

  return (
    <div className="flex items-center w-full h-11 px-2 md:px-3 border-b border-edge/5 bg-surface-900/30 min-w-0">
      <button
        type="button"
        onClick={onToggleChainPanel}
        className={cn(
          'flex-shrink-0 p-1.5 mr-1 rounded-md transition-all options-chain-chip hover:bg-overlay/[0.06]',
          !chainPanelVisible && 'text-primary-600 bg-primary-600/10',
        )}
        title={chainPanelVisible ? 'Hide option chain' : 'Show option chain'}
      >
        {chainPanelVisible ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeftOpen className="w-4 h-4" />}
      </button>

      <div className="flex items-center gap-3 flex-shrink-0 min-w-0">
        <div className="flex flex-col leading-none min-w-0">
          <span
            className={cn(
              'text-sm font-semibold truncate max-w-[200px] md:max-w-[280px]',
              isCe ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400',
            )}
          >
            {displaySymbol || 'Select strike'}
          </span>
          <span className="text-[10px] options-chain-muted mt-0.5 truncate max-w-[280px]">{metaLine}</span>
        </div>
        {ltp != null && ltp !== '—' && (
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="text-base font-semibold font-mono text-heading tabular-nums">
              ₹{typeof ltp === 'number' ? formatPrice(ltp) : ltp}
            </span>
            {change != null && Number.isFinite(change) && (
              <span
                className={cn(
                  'text-xs font-mono font-medium tabular-nums whitespace-nowrap',
                  change >= 0 ? 'text-bull' : 'text-bear',
                )}
              >
                {change >= 0 ? '+' : ''}
                {change.toFixed(2)}
                {changePct != null && Number.isFinite(changePct)
                  ? ` (${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%)`
                  : ''}
              </span>
            )}
          </div>
        )}
      </div>

      {greeksMini && (
        <div className="hidden md:flex items-center gap-2 ml-2 text-[10px] options-chain-muted font-mono tabular-nums">
          <span>Δ {greeksMini.delta ?? '—'}</span>
          <span>IV {greeksMini.iv != null && greeksMini.iv > 0 ? `${formatPrice(greeksMini.iv)}%` : '—'}</span>
        </div>
      )}

      <div className="flex-1" />

      <div className="flex items-center gap-2 flex-shrink-0">
        <div className="relative" ref={periodRef}>
          <button
            type="button"
            onClick={() => setPeriodOpen((v) => !v)}
            className={cn(
              'h-7 px-2.5 rounded-md border text-xs font-semibold inline-flex items-center gap-1.5',
              periodOpen
                ? 'bg-primary-600/20 border-primary-500/40 text-primary-600'
                : 'options-chain-chip border-edge/20',
            )}
          >
            <span className="font-mono">{currentLabel}</span>
          </button>
          {periodOpen && (
            <div className="absolute top-full right-0 mt-1.5 z-50 min-w-[100px] rounded-lg border border-edge/10 bg-surface-900/95 shadow-xl py-1">
              {CHART_INTERVALS.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => {
                    onIntervalChange(key);
                    setPeriodOpen(false);
                  }}
                  className={cn(
                    'w-full text-left px-3 py-1.5 text-xs font-medium',
                    interval === key ? 'text-primary-600 bg-primary-600/10' : 'options-chain-chip hover:bg-overlay/[0.04]',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={onToggleOrderPanel}
          className={cn(
            'h-7 px-2.5 rounded-md border text-[11px] font-semibold transition-colors',
            orderPanelVisible
              ? 'bg-primary-600/20 border-primary-500/40 text-primary-600'
              : 'options-chain-chip border-edge/20',
          )}
          title={orderPanelVisible ? 'Hide order panel' : 'Show order panel'}
        >
          Order Panel
        </button>

        {showRightToggle && (
          <button
            type="button"
            onClick={onToggleRightPanel}
            className={cn(
              'hidden lg:flex p-1.5 rounded-md options-chain-chip hover:bg-overlay/[0.06]',
              !rightPanelVisible && 'text-primary-600 bg-primary-600/10',
            )}
            title={rightPanelVisible ? 'Hide details' : 'Show details'}
          >
            {rightPanelVisible ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
          </button>
        )}
      </div>
    </div>
  );
}

export default memo(OptionsChartHeader);
