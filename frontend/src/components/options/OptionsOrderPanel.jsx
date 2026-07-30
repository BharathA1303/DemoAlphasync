import { memo } from 'react';
import { cn } from '../../utils/cn';
import { formatCurrency, formatPrice } from '../../utils/formatters';
import Badge from '../ui/Badge';

function OptionsOrderPanel({
  selectedSymbol,
  expiry,
  optionType,
  onOptionTypeChange,
  side,
  onSideChange,
  orderType,
  onOrderTypeChange,
  lots,
  onLotsChange,
  lotSize,
  limitPrice,
  onLimitPriceChange,
  premium,
  onPremiumChange,
  totalValue,
  maxLoss,
  greeks,
  spread,
  onPlaceOrder,
  disabled,
}) {
  const isBuy = side === 'BUY';
  const spreadWarn = spread != null && spread > 0.05;

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-surface-900">
      <div className="px-3 py-2 border-b border-edge/5 flex-shrink-0">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-2">
          Strike Execution
        </div>
        <Badge variant="primary" className="text-[10px] font-semibold mb-2 block truncate">
          {selectedSymbol}
        </Badge>
        {expiry && <div className="text-[10px] options-chain-muted mb-2">Expiry: {expiry}</div>}
        <div className="flex rounded-lg overflow-hidden border border-edge/10 bg-surface-800/60 p-0.5 mb-2">
          {['CE', 'PE'].map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => onOptionTypeChange(t)}
              className={cn(
                'flex-1 py-1.5 text-xs font-bold rounded-md',
                optionType === t
                  ? t === 'CE'
                    ? 'bg-emerald-500/20 text-emerald-500'
                    : 'bg-red-500/20 text-red-500'
                  : 'text-gray-500',
              )}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={() => onSideChange('BUY')}
            className={cn(
              'flex-1 py-1.5 text-sm font-bold rounded-lg border',
              isBuy
                ? 'bg-bull text-white border-emerald-500/40'
                : 'bg-surface-800/60 border-edge/10 text-gray-500',
            )}
          >
            BUY
          </button>
          <button
            type="button"
            onClick={() => onSideChange('SELL')}
            className={cn(
              'flex-1 py-1.5 text-sm font-bold rounded-lg border',
              !isBuy
                ? 'bg-bear text-white border-red-500/40'
                : 'bg-surface-800/60 border-edge/10 text-gray-500',
            )}
          >
            SELL
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-2.5 space-y-3 min-h-0">
        <div>
          <label className="metric-label block mb-1">Lots</label>
          <div className="h-10 flex items-center border border-edge/10 rounded-lg bg-surface-800/60">
            <button
              type="button"
              onClick={() => onLotsChange(Math.max(1, lots - 1))}
              className="px-3 text-lg font-bold text-gray-400"
            >
              −
            </button>
            <input
              type="number"
              min={1}
              value={lots}
              onChange={(e) => onLotsChange(Math.max(1, Number(e.target.value) || 1))}
              className="flex-1 text-center bg-transparent text-sm font-mono text-heading focus:outline-none"
            />
            <button
              type="button"
              onClick={() => onLotsChange(lots + 1)}
              className="px-3 text-lg font-bold text-gray-400"
            >
              +
            </button>
          </div>
          <p className="text-[10px] options-chain-muted mt-1">Qty: {lots * lotSize} (1 × {lotSize})</p>
        </div>

        <div>
          <label className="metric-label block mb-1">Order Type</label>
          <div className="grid grid-cols-2 gap-1">
            {['MARKET', 'LIMIT'].map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => onOrderTypeChange(t)}
                className={cn(
                  'py-1.5 text-xs font-semibold rounded-lg',
                  orderType === t ? 'bg-primary-600/20 text-primary-600' : 'bg-surface-800/60 text-gray-500',
                )}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {orderType === 'LIMIT' && (
          <div>
            <label className="metric-label block mb-1">Limit (₹)</label>
            <input
              type="number"
              step="0.05"
              value={limitPrice}
              onChange={(e) => onLimitPriceChange(e.target.value)}
              className="w-full bg-surface-800/60 border border-edge/10 rounded-lg px-3 py-2 text-sm font-mono text-heading focus:outline-none"
            />
          </div>
        )}

        <div>
          <label className="metric-label block mb-1">Premium (₹)</label>
          <input
            type="number"
            step="0.05"
            value={premium}
            onChange={(e) => onPremiumChange(e.target.value)}
            className="w-full bg-surface-800/60 border border-edge/10 rounded-lg px-3 py-2 text-sm font-mono text-heading focus:outline-none"
          />
        </div>

        <div className="rounded-xl bg-surface-800/40 border border-edge/5 p-2.5 space-y-1.5 text-xs">
          <div className="flex justify-between">
            <span className="text-gray-500">Premium preview</span>
            <span className="font-mono text-heading">{formatCurrency(totalValue)}</span>
          </div>
          {side === 'SELL' && maxLoss != null && (
            <div className="flex justify-between">
              <span className="text-gray-500">Max loss est.</span>
              <span className="font-mono text-bear">{formatCurrency(maxLoss)}</span>
            </div>
          )}
          {spread != null && (
            <div className="flex justify-between">
              <span className="text-gray-500">Spread</span>
              <span className={cn('font-mono', spreadWarn && 'text-amber-500')}>
                ₹{formatPrice(spread)}
              </span>
            </div>
          )}
        </div>

        {spreadWarn && (
          <p className="text-[10px] text-amber-500/90">Wide spread — check liquidity before market order.</p>
        )}

        <div className="flex flex-wrap gap-1.5">
          <Badge variant="default" className="text-[10px]">
            Δ {formatPrice(greeks?.delta)}
          </Badge>
          <Badge variant="default" className="text-[10px]">
            IV {greeks?.iv != null ? `${formatPrice(greeks.iv)}%` : '—'}
          </Badge>
        </div>

        <button
          type="button"
          disabled
          className="w-full py-2 text-[11px] font-semibold rounded-lg border border-edge/15 text-gray-500 opacity-60"
          title="Multi-leg basket — structure reserved"
        >
          + Add leg (basket)
        </button>
      </div>

      <div className="sticky bottom-0 px-3 py-3 border-t border-edge/5 bg-surface-900 flex-shrink-0">
        <button
          type="button"
          onClick={onPlaceOrder}
          disabled={disabled}
          className={cn(
            'w-full py-3 text-base font-bold rounded-lg text-white transition-colors',
            isBuy ? 'bg-bull hover:bg-emerald-600' : 'bg-bear hover:bg-red-600',
            disabled && 'opacity-40 cursor-not-allowed',
          )}
        >
          {isBuy ? 'Place Buy Order' : 'Place Sell Order'}
        </button>
      </div>
    </div>
  );
}

export default memo(OptionsOrderPanel);
