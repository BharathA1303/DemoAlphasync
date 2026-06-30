import { memo } from 'react';
import { cn } from '../../utils/cn';
import { formatPrice, cleanSymbol } from '../../utils/formatters';

/**
 * MobileTradeBar — sticky bottom action bar for mobile trading.
 *
 * Shows symbol, current price, and prominent BUY / SELL buttons.
 * Tapping either button opens the order panel as a drawer.
 *
 * Design: 2-tap max trade execution flow.
 *
 * Props:
 *  - symbol: string
 *  - price: number
 *  - onBuy: () => void
 *  - onSell: () => void
 *  - onToggleWatchlist: () => void — opens watchlist drawer
 *  - className
 */
function MobileTradeBar({
    symbol,
    price = 0,
    onBuy,
    onSell,
    onToggleWatchlist,
    className,
}) {
    return (
        <div className={cn(
            'flex items-center gap-2 px-3 py-2 bg-surface-900/95 backdrop-blur-md',
            'border-t border-edge/10 safe-area-bottom',
            className,
        )}>
            {/* Watchlist toggle */}
            <button
                onClick={onToggleWatchlist}
                className="p-2 rounded-lg bg-surface-800/80 border border-edge/10 text-gray-400 hover:text-heading transition-colors"
                title="Watchlist"
            >
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />
                </svg>
            </button>

            {/* Symbol + Price */}
            <div className="flex-1 min-w-0 flex items-center gap-2">
                <span className="text-sm font-semibold text-heading truncate">
                    {cleanSymbol(symbol)}
                </span>
                {price > 0 && (
                    <span className="text-sm font-mono text-gray-400 tabular-nums">
                        ₹{formatPrice(price)}
                    </span>
                )}
            </div>

            {/* BUY / SELL */}
            <button
                onClick={onBuy}
                className={cn(
                    'px-5 py-2.5 rounded-lg text-sm font-bold',
                    'bg-bull text-white shadow-bull',
                    'active:scale-95 transition-all duration-150'
                )}
            >
                BUY
            </button>
            <button
                onClick={onSell}
                className={cn(
                    'px-5 py-2.5 rounded-lg text-sm font-bold',
                    'bg-bear text-white shadow-bear',
                    'active:scale-95 transition-all duration-150'
                )}
            >
                SELL
            </button>
        </div>
    );
}

export default memo(MobileTradeBar);
