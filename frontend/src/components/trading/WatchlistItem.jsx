import { memo, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '../../utils/cn';
import { formatPrice, formatPercent } from '../../utils/formatters';
import { getConstituents } from '../../utils/indexConstituents';
import api from '../../services/api';

const formatSignedNumber = (value, decimals = 2) => {
    if (value == null || Number.isNaN(Number(value))) return '—';
    const num = Number(value);
    const sign = num > 0 ? '+' : '';
    return `${sign}${num.toFixed(decimals)}`;
};

/**
 * Single watchlist row.
 * — Default state : symbol name (left) + price & change% (right)
 * — Hover state   : prices stay visible, action buttons appear as overlay
 * — Index items   : expand chevron reveals constituent stocks with live prices
 */
const WatchlistItem = memo(function WatchlistItem({
    item,
    price = {},
    isSelected,
    onSelect,
    onRemove,
    onBuy,
    onSell,
}) {
    const navigate = useNavigate();
    const [hovered, setHovered] = useState(false);
    const [isExpanded, setIsExpanded] = useState(false);
    const [constituentPrices, setConstituentPrices] = useState({});
    const [loadingConstituents, setLoadingConstituents] = useState(false);

    const constituents = getConstituents(item.symbol);
    const isIndex = constituents !== null;

    // ── Fetch constituent prices when expanded ────────────────────────────────
    const constituentSuffix = (item.exchange || '').toUpperCase() === 'BSE' ? '.BO' : '.NS';
    const fetchConstituentPrices = useCallback(async () => {
        if (!constituents || constituents.length === 0) return;
        setLoadingConstituents(true);
        try {
            const symbols = constituents.map(s => `${s}${constituentSuffix}`).join(',');
            const res = await api.get(`/market/batch?symbols=${encodeURIComponent(symbols)}`);
            const quotes = res.data?.quotes ?? {};
            // Normalize: store under both RELIANCE.NS and RELIANCE so lookup always works
            const normalized = {};
            Object.entries(quotes).forEach(([k, v]) => {
                const upper = k.toUpperCase();
                normalized[upper] = v;
                normalized[upper.replace(/\.(NS|BO)$/i, '')] = v;
            });
            setConstituentPrices(normalized);
        } catch {
            // silently ignore — prices stay empty
        } finally {
            setLoadingConstituents(false);
        }
    }, [constituents]);

    const handleExpandToggle = useCallback((e) => {
        e.stopPropagation();
        setIsExpanded(prev => {
            const next = !prev;
            if (next) fetchConstituentPrices();
            return next;
        });
    }, [fetchConstituentPrices]);

    const changePositive = (price?.change ?? price?.change_percent ?? 0) >= 0;
    const rawSymbol = item.symbol || '';
    const symbol = rawSymbol.replace('.NS', '').replace('.BO', '').replace(/^\^/, '');
    const exchange = item.exchange || (rawSymbol.endsWith('.BO') ? 'BSE' : 'NSE');
    const chartSymbol = rawSymbol.startsWith('^') || rawSymbol.endsWith('.NS') || rawSymbol.endsWith('.BO')
        ? rawSymbol
        : exchange === 'BSE' ? `${rawSymbol}.BO` : `${rawSymbol}.NS`;

    return (
        <div className="border-b border-edge/[0.03]">
            {/* ── Main row ─────────────────────────────────────────────────────── */}
            <div
                onClick={onSelect}
                onMouseEnter={() => setHovered(true)}
                onMouseLeave={() => setHovered(false)}
                className={cn(
                    'relative flex items-center justify-between px-3 py-2 cursor-pointer',
                    'transition-colors duration-150',
                    isSelected
                        ? 'bg-primary-500/10 border-l-[3px] border-l-primary-500 hover:bg-primary-500/15 dark:bg-slate-700/60 dark:hover:bg-slate-700/80'
                        : 'border-l-[3px] border-l-transparent hover:bg-slate-100 dark:hover:bg-slate-800/50',
                )}
            >
                {/* ── Left: symbol + exchange badge + expand chevron ──────────── */}
                <div className="flex-1 min-w-0 flex items-center gap-1">
                    {isIndex && (
                        <button
                            onClick={handleExpandToggle}
                            className="flex-shrink-0 p-0.5 rounded text-slate-400 hover:text-primary-500 transition-colors"
                            title={isExpanded ? 'Collapse stocks' : 'Expand stocks'}
                        >
                            <svg
                                className={cn('w-3 h-3 transition-transform duration-200', isExpanded && 'rotate-90')}
                                viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
                                strokeLinecap="round" strokeLinejoin="round"
                            >
                                <path d="M9 18l6-6-6-6" />
                            </svg>
                        </button>
                    )}
                    <div className="min-w-0">
                        <div className="font-semibold text-[13px] text-heading truncate">{symbol}</div>
                        <div className="flex items-center gap-1 mt-0.5">
                            <span className={cn(
                                'inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-medium leading-none tracking-wide',
                                'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300',
                            )}>
                                {exchange}
                            </span>
                            {item.company_name && (
                                <span className="text-[10px] text-slate-500 dark:text-slate-500 truncate leading-tight max-w-[90px]">
                                    {item.company_name}
                                </span>
                            )}
                        </div>
                    </div>
                </div>

                {/* ── Right: action buttons (hover) + price always visible ─────── */}
                <div className="flex-shrink-0 ml-1 flex items-center gap-1.5">
                    {hovered && (
                        <div className="flex items-center gap-0.5 animate-fade-in">
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    navigate(`/terminal?symbol=${encodeURIComponent(chartSymbol)}`);
                                }}
                                className="p-1 rounded text-gray-400 hover:text-primary-600 hover:bg-primary-500/10 transition-colors"
                                title="Open chart"
                            >
                                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M3 3v18h18" /><path d="M7 16l4-8 4 5 5-9" />
                                </svg>
                            </button>
                            <button
                                onClick={(e) => { e.stopPropagation(); onBuy?.(item.symbol); }}
                                className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-500/90 hover:bg-emerald-400 text-white transition-colors leading-none"
                            >
                                B
                            </button>
                            <button
                                onClick={(e) => { e.stopPropagation(); onSell?.(item.symbol); }}
                                className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-500/90 hover:bg-red-400 text-white transition-colors leading-none"
                            >
                                S
                            </button>
                            <button
                                onClick={(e) => { e.stopPropagation(); onRemove?.(item.id); }}
                                className="p-0.5 rounded text-gray-400 hover:text-red-500 transition-colors"
                                title="Remove"
                            >
                                <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                                    <path d="M18 6L6 18M6 6l12 12" />
                                </svg>
                            </button>
                        </div>
                    )}

                    <div className="flex flex-col items-end transition-opacity duration-300"
                        style={{ opacity: price?.price != null ? 1 : 0.3 }}
                    >
                        <span className="text-[13px] font-price font-semibold text-heading tabular-nums">
                            {price?.price != null ? formatPrice(price.price) : '—'}
                        </span>
                        <span className={cn(
                            'flex items-center gap-0.5 text-[10px] font-price tabular-nums',
                            changePositive ? 'text-bull' : 'text-bear'
                        )}>
                            {price?.change != null && price?.change_percent != null
                                ? `${formatSignedNumber(price.change, 2)} (${formatPercent(price.change_percent, 2)})`
                                : '—'}
                        </span>
                    </div>
                </div>
            </div>

            {/* ── Constituent stocks sub-list ───────────────────────────────────── */}
            {isIndex && isExpanded && (
                <div className="bg-slate-50 dark:bg-slate-900/60 border-l-[3px] border-l-primary-400/40">
                    {loadingConstituents ? (
                        <div className="flex items-center justify-center py-3 text-[11px] text-slate-400">
                            Loading...
                        </div>
                    ) : (
                        <div className="max-h-64 overflow-y-auto divide-y divide-slate-200/40 dark:divide-slate-700/30">
                            {constituents.map(base => {
                                const sym = `${base}${constituentSuffix}`;
                                const p = constituentPrices[sym] ?? constituentPrices[base] ?? {};
                                const chg = p.change_percent ?? 0;
                                const chgPos = chg >= 0;
                                return (
                                    <div
                                        key={base}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            navigate(`/terminal?symbol=${encodeURIComponent(sym)}`);
                                        }}
                                        className="flex items-center justify-between px-4 py-1.5 cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-800/50 transition-colors"
                                    >
                                        <span className="text-[11px] font-medium text-slate-700 dark:text-slate-300 truncate max-w-[100px]">
                                            {base}
                                        </span>
                                        <div className="flex flex-col items-end ml-2">
                                            <span className="text-[11px] font-semibold text-heading tabular-nums">
                                                {p.price != null ? formatPrice(p.price) : '—'}
                                            </span>
                                            <span className={cn(
                                                'text-[9px] tabular-nums',
                                                chgPos ? 'text-bull' : 'text-bear'
                                            )}>
                                                {p.change_percent != null
                                                    ? `${chgPos ? '+' : ''}${Number(p.change_percent).toFixed(2)}%`
                                                    : '—'}
                                            </span>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}, (prev, next) =>
    prev.price?.price === next.price?.price &&
    prev.price?.change_percent === next.price?.change_percent &&
    prev.isSelected === next.isSelected &&
    prev.item.id === next.item.id &&
    prev.onBuy === next.onBuy &&
    prev.onSell === next.onSell &&
    prev.onRemove === next.onRemove
);

export default WatchlistItem;
