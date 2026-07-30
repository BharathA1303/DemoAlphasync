import { X } from 'lucide-react';
import { cn } from '../../utils/cn';
import { formatPrice } from '../../utils/formatters';

export default function FuturesWatchlistItem({
    item,
    price = {},
    isSelected = false,
    onSelect,
    onRemove,
}) {
    const ltp = price.ltp ?? price.price ?? null;
    const prevClose = Number(price.close ?? price.prev_close);
    const change = price.change ?? (
        ltp != null && Number.isFinite(prevClose) && prevClose > 0
            ? Number((Number(ltp) - prevClose).toFixed(2))
            : null
    );
    const changePct = price.change_pct ?? price.change_percent ?? (
        change != null && Number.isFinite(prevClose) && prevClose > 0
            ? Number(((Number(change) / prevClose) * 100).toFixed(2))
            : null
    );
    const isUp = change != null && change >= 0;

    return (
        <div
            onClick={onSelect}
            className={cn(
                'flex items-center justify-between px-3 py-2.5 border-b border-edge/5 hover:bg-surface-800/30 cursor-pointer transition-colors group',
                isSelected && 'bg-primary-500/10 border-l-2 border-l-primary-500'
            )}
        >
            <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-heading truncate">{item.contract_symbol}</p>
                {ltp != null && (
                    <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-xs font-medium text-gray-400">{formatPrice(ltp)}</span>
                        {change != null && (
                            <>
                                <span className={cn('text-xs font-medium', isUp ? 'text-bull' : 'text-bear')}>
                                    {isUp ? '+' : ''}{formatPrice(change)}
                                </span>
                                {changePct != null && (
                                    <span className={cn('text-xs', isUp ? 'text-bull' : 'text-bear')}>
                                        {isUp ? '+' : ''}{Number(changePct).toFixed(2)}%
                                    </span>
                                )}
                            </>
                        )}
                    </div>
                )}
            </div>

            <button
                onClick={(e) => {
                    e.stopPropagation();
                    onRemove?.();
                }}
                className="ml-2 p-1 rounded-md opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-500 hover:bg-red-500/10 transition-all flex-shrink-0"
                title="Remove from watchlist"
            >
                <X className="w-3.5 h-3.5" />
            </button>
        </div>
    );
}
