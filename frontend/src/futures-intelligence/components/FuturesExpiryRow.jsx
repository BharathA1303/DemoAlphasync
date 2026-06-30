import { memo } from 'react';
import { cn } from '../../utils/cn';
import FuturesBasisBadge from './FuturesBasisBadge';
import FuturesOIBadge from './FuturesOIBadge';
import FuturesVolumeBadge from './FuturesVolumeBadge';
import { formatPrice } from '../../utils/formatters';

function formatExpiry(date) {
  if (!date) return '—';
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return date;
  return parsed.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}

function FuturesExpiryRow({ row, isSelected, onSelect }) {
  const label = row.label || '—';
  const isPositive = (row.changePct ?? 0) >= 0;
  const isCold = row.tier === 'cold' || row.tier === 'cold-near' || row.tier === 'cold-far';

  return (
    <button
      type="button"
      onClick={() => onSelect?.(row.contractSymbol)}
      className={cn(
        'w-full text-left px-3 py-2.5 border-b border-edge/[0.03] transition-colors',
        isSelected
          ? 'bg-primary-500/10 border-l-[3px] border-l-primary-500'
          : 'border-l-[3px] border-l-transparent hover:bg-surface-800/40',
      )}
    >
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-1.5 flex-wrap min-w-0">
          <span
            className={cn(
              'text-[9px] font-bold uppercase px-1 py-0.5 rounded',
              label === 'Near'
                ? 'bg-emerald-500/15 text-emerald-500'
                : label === 'Mid'
                  ? 'bg-amber-500/15 text-amber-500'
                  : 'bg-slate-600/30 text-slate-400',
            )}
          >
            {label}
          </span>
          <span className="text-[10px] text-gray-500">{formatExpiry(row.expiryDate)}</span>
          {row.daysToExpiry != null && (
            <span
              className={cn(
                'text-[9px] tabular-nums',
                row.daysToExpiry <= 2
                  ? 'text-red-400'
                  : row.daysToExpiry <= 7
                    ? 'text-amber-400'
                    : 'text-gray-600',
              )}
            >
              {row.daysToExpiry}d
            </span>
          )}
          {isCold && (
            <span className="text-[8px] uppercase text-gray-600 bg-gray-800/50 px-1 rounded">
              {row._illiquid ? 'illiquid' : 'delayed'}
            </span>
          )}
        </div>
        {row.ltp != null && (
          <span className="text-[11px] font-semibold font-mono text-heading tabular-nums flex-shrink-0">
            {formatPrice(row.ltp)}
          </span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-x-2 gap-y-1 text-[10px]">
        <div>
          <div className="text-gray-600">Premium</div>
          <FuturesBasisBadge value={row.premium} />
        </div>
        <div>
          <div className="text-gray-600">OI</div>
          <FuturesOIBadge value={row.oi} />
        </div>
        <div>
          <div className="text-gray-600">Volume</div>
          <FuturesVolumeBadge value={row.volume} />
        </div>
      </div>

      {row.changePct != null && (
        <div className={cn('text-[9px] font-mono tabular-nums mt-1', isPositive ? 'text-bull' : 'text-bear')}>
          {isPositive ? '+' : ''}
          {row.changePct.toFixed(2)}%
        </div>
      )}
    </button>
  );
}

export default memo(FuturesExpiryRow);
