import { useMemo } from 'react';
import useUnifiedFuturesStore from '../../stores/useUnifiedFuturesStore';
import { cn } from '../../utils/cn';
import { formatPrice } from '../../utils/formatters';

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

function isColdQuote(q) {
  return q?._tier === 'cold' || q?._tier === 'cold-near' || q?._tier === 'cold-far';
}

function isIlliquid(q) {
  return q?._illiquid === true;
}

function formatExpiry(date) {
  if (!date) return '—';
  const parsed = new Date(date);
  if (Number.isNaN(parsed.getTime())) return date;
  return parsed.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}

/**
 * Shows Near / Mid / Far contracts for the selected underlying (e.g. NIFTY).
 */
export default function FuturesContractsPanel({ onSelectContract }) {
  const selectedUnderlying = useUnifiedFuturesStore((s) => s.contracts.selectedUnderlying);
  const selectedContract = useUnifiedFuturesStore((s) => s.contracts.selectedContract);
  const bySymbol = useUnifiedFuturesStore((s) => s.contracts.bySymbol);
  const byUnderlying = useUnifiedFuturesStore((s) => s.contracts.byUnderlying);
  const quotes = useUnifiedFuturesStore((s) => s.quotes);
  const lastQuoteUpdate = useUnifiedFuturesStore((s) => s._lastQuoteUpdate);
  const loading = useUnifiedFuturesStore((s) => s.contracts.loading);

  const contracts = useMemo(() => {
    if (!selectedUnderlying) return [];
    const symbols = byUnderlying[selectedUnderlying] || [];
    return symbols
      .map((sym) => bySymbol[sym])
      .filter(Boolean)
      .sort((a, b) => {
        const da = new Date(a.expiry_date || 0).getTime();
        const db = new Date(b.expiry_date || 0).getTime();
        return da - db;
      });
  }, [selectedUnderlying, byUnderlying, bySymbol]);

  if (!selectedUnderlying) {
    return (
      <div className="flex flex-col h-full border-l border-edge/5 bg-surface-900/60">
        <div className="px-3 py-2.5 border-b border-edge/5 text-sm font-semibold text-heading">Contracts</div>
        <div className="flex-1 flex items-center justify-center px-4 text-center text-xs text-gray-500">
          Search or add a symbol to view expiry contracts
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full border-l border-edge/5 bg-surface-900/60 min-w-0">
      <div className="px-3 py-2.5 border-b border-edge/5 flex-shrink-0">
        <div className="text-sm font-semibold text-heading">{selectedUnderlying}</div>
        <div className="text-[10px] text-gray-500 mt-0.5">Futures expiries</div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {loading && contracts.length === 0 ? (
          <div className="px-3 py-6 text-xs text-gray-500 text-center">Loading contracts…</div>
        ) : contracts.length === 0 ? (
          <div className="px-3 py-6 text-xs text-gray-500 text-center">No contracts found</div>
        ) : (
          contracts.map((contract) => {
            const sym = contract.contract_symbol;
            const quote = quotes[sym];
            void lastQuoteUpdate;
            const ltp = quotePrice(quote);
            const change = quoteChange(quote);
            const changePct = quoteChangePct(quote);
            const isSelected = selectedContract === sym;
            const label = contract.expiry_label || '—';
            const isCold = isColdQuote(quote);
            const isPositive = (change ?? 0) >= 0;

            return (
              <button
                key={sym}
                type="button"
                onClick={() => onSelectContract?.(sym)}
                className={cn(
                  'w-full text-left px-3 py-2 border-b border-edge/[0.03] transition-colors',
                  isSelected
                    ? 'bg-primary-500/10 border-l-[3px] border-l-primary-500'
                    : 'border-l-[3px] border-l-transparent hover:bg-surface-800/40',
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className={cn(
                        'text-[9px] font-bold uppercase px-1 py-0.5 rounded',
                        label === 'Near' ? 'bg-emerald-500/15 text-emerald-500' :
                        label === 'Mid' ? 'bg-amber-500/15 text-amber-500' :
                        'bg-slate-600/30 text-slate-400',
                      )}>{label}</span>
                      <span className="text-[10px] text-gray-500">{formatExpiry(contract.expiry_date)}</span>
                      {contract.days_to_expiry != null && (
                        <span className={cn('text-[9px] tabular-nums',
                          contract.days_to_expiry <= 2 ? 'text-red-400' :
                          contract.days_to_expiry <= 7 ? 'text-amber-400' : 'text-gray-600'
                        )}>{contract.days_to_expiry}d</span>
                      )}
                      {isCold && (
                        <span className={cn('text-[8px] uppercase tracking-wider px-1 rounded',
                          isIlliquid(quote) ? 'text-amber-500 bg-amber-900/20' : 'text-gray-600 bg-gray-800/50'
                        )}>{isIlliquid(quote) ? 'illiquid' : 'delayed'}</span>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-col items-end flex-shrink-0 gap-0.5">
                    <span className="text-[11px] font-semibold font-mono text-heading tabular-nums">
                      {ltp != null ? formatPrice(ltp) : '—'}
                    </span>
                    {changePct != null && (
                      <span className={cn('text-[9px] font-mono tabular-nums', isPositive ? 'text-bull' : 'text-bear')}>
                        {isPositive ? '+' : ''}{changePct.toFixed(2)}%
                      </span>
                    )}
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
