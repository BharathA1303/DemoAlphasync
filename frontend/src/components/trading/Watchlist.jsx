import { useState, useCallback, useRef, useEffect, useMemo, useSyncExternalStore } from 'react';
import WatchlistItem from './WatchlistItem';
import AddSymbolModal from './AddSymbolModal';
import WatchlistSidebar from './WatchlistSidebar';
import Modal from '../ui/Modal';
import Skeleton from '../ui/Skeleton';
import { cn } from '../../utils/cn';
import { isCommoditySymbol } from '../../utils/constants';
import {
    Search, Plus,
    CheckCircle2, Menu, ChevronLeft, ChevronRight,
} from 'lucide-react';
import { useWatchlistStore } from '../../stores/useWatchlistStore';
import { useMarketStore } from '../../store/useMarketStore';
import { mergeWatchlistPrices } from '../../utils/liveQuote';
import {
    getSessionCloseCache,
    getSessionClosePrice,
    subscribeSessionClosePrices,
} from '../../market/SessionClosePriceAuthority';
import { shouldUseRealtimePrices } from '../../market/utils/marketSessionUtils';

const getPriceForSymbol = (primaryPrices, symbol) => {
    const raw = String(symbol || '').trim();
    if (!raw) return {};

    const upper = raw.toUpperCase();
    const isExplicitExchange = upper.endsWith('.NS') || upper.endsWith('.BO') || upper.startsWith('^');
    const withNs = isExplicitExchange ? upper : `${upper}.NS`;
    const withoutNs = upper.replace(/\.(NS|BO)$/i, '');

    const candidates = isExplicitExchange
        ? [upper, withoutNs]
        : [withNs, upper, withoutNs];

    if (!shouldUseRealtimePrices()) {
        const session = getSessionClosePrice(raw);
        if (session?.price != null) return session;
        return {};
    }

    for (const key of candidates) {
        const quote = primaryPrices[key];
        if (quote?.price != null) return quote;
    }

    return {};
};

const normalizeSymbolKey = (symbol = '') =>
    String(symbol || '')
        .trim()
        .toUpperCase()
        .replace(/\.(NS|BO)$/i, '');

// ── Main component ─────────────────────────────────────────────────────────────
export default function Watchlist({
    selectedSymbol,
    onSelectSymbol,
    onBuy,
    onSell,
    onClose,
}) {
    const {
        watchlists,
        activeId,
        prices: watchlistPrices,
        isLoading,
        setActiveWatchlist,
        createWatchlist,
        renameWatchlist,
        deleteWatchlist,
        addItem,
        removeItem,
        reorderItems,
        fetchPrices,
    } = useWatchlistStore();

    const liveQuotes = useMarketStore((s) => s.symbols);
    const sessionCloseKey = useSyncExternalStore(
        subscribeSessionClosePrices,
        () => Object.keys(getSessionCloseCache()).length,
        () => 0,
    );
    const mergedPrices = useMemo(
        () => mergeWatchlistPrices(watchlistPrices, liveQuotes),
        [watchlistPrices, liveQuotes, sessionCloseKey],
    );

    const activeWatchlist = watchlists.find(w => w.id === activeId);
    const items = activeWatchlist?.items ?? [];

    // ── UI state ──────────────────────────────────────────────────────────────
    const [modalOpen, setModalOpen] = useState(false);
    const [createModalOpen, setCreateModalOpen] = useState(false);
    const [sidebarOpen, setSidebarOpen] = useState(false);
    const [newWlName, setNewWlName] = useState('');
    const [tabScroll, setTabScroll] = useState({ left: false, right: false });
    const tabsRef = useRef(null);

    // Drag-and-drop state
    const [dragIndex, setDragIndex] = useState(null);
    const [dragOverIndex, setDragOverIndex] = useState(null);

    const scrollEl = useRef(null);

    // ── Focus helpers ─────────────────────────────────────────────────────────
    const sortedWatchlists = useMemo(() => watchlists, [watchlists]);

    // ── Prefetch closed-session prices for every watchlist row (not only selected) ──
    const itemSymbolsKey = useMemo(
        () => items.map((i) => i.symbol).join('|'),
        [items],
    );
    useEffect(() => {
        if (items.length > 0) fetchPrices();
    }, [activeId, itemSymbolsKey, fetchPrices]);

    const updateTabScroll = useCallback(() => {
        const el = tabsRef.current;
        if (!el) return;
        const canScrollLeft = el.scrollLeft > 4;
        const canScrollRight = el.scrollLeft + el.clientWidth < el.scrollWidth - 4;
        setTabScroll((prev) => (
            prev.left === canScrollLeft && prev.right === canScrollRight
                ? prev
                : { left: canScrollLeft, right: canScrollRight }
        ));
    }, []);

    useEffect(() => {
        updateTabScroll();
        const el = tabsRef.current;
        if (!el) return;
        const onScroll = () => updateTabScroll();
        el.addEventListener('scroll', onScroll, { passive: true });
        window.addEventListener('resize', updateTabScroll);
        return () => {
            el.removeEventListener('scroll', onScroll);
            window.removeEventListener('resize', updateTabScroll);
        };
    }, [sortedWatchlists.length, updateTabScroll]);

    // ── Handlers ──────────────────────────────────────────────────────────────
    const handleAddSymbol = useCallback((symbol, exchange) => {
        addItem(symbol, exchange);
        setModalOpen(false);
    }, [addItem]);

    const handleCreateSubmit = useCallback(async () => {
        const name = newWlName.trim() || `Watchlist ${watchlists.length + 1}`;
        await createWatchlist(name);
        setCreateModalOpen(false);
        setNewWlName('');
    }, [newWlName, createWatchlist, watchlists.length]);

    const handleCreateKeyDown = useCallback((e) => {
        if (e.key === 'Enter') handleCreateSubmit();
        if (e.key === 'Escape') { setCreateModalOpen(false); setNewWlName(''); }
    }, [handleCreateSubmit]);

    return (
        <div className="flex flex-col h-full border-r border-edge/5 bg-surface-900/60">

            {/* ── TOP SEARCH BAR ───────────────────────────────────────── */}
            <div className="flex items-center px-3 py-2 border-b border-edge/5 bg-surface-900/40 flex-shrink-0">
                <button
                    onClick={() => setSidebarOpen(true)}
                    className="flex-shrink-0 h-9 w-9 rounded-lg flex items-center justify-center text-gray-500 hover:text-heading hover:bg-surface-800/60 transition-colors"
                    title="Watchlists"
                >
                    <Menu className="w-4 h-4" />
                </button>

                <button
                    onClick={() => setModalOpen(true)}
                    className="flex-shrink-0 h-9 w-9 rounded-lg flex items-center justify-center text-gray-500 hover:text-heading hover:bg-surface-800/60 transition-colors"
                    title="Search or add symbol"
                >
                    <Search className="w-4 h-4 flex-shrink-0" />
                </button>

                <div className="flex-1 text-center text-sm font-semibold font-sans text-heading tracking-wide select-none">
                    Watchlist
                </div>

                <button
                    onClick={() => setCreateModalOpen(true)}
                    className="flex-shrink-0 h-9 w-9 rounded-lg flex items-center justify-center text-gray-500 hover:text-primary-600 hover:bg-primary-500/10 transition-colors"
                    title="New watchlist"
                >
                    <Plus className="w-4 h-4" />
                </button>
            </div>

            {/* ── TAB ROW WITH OVERFLOW ARROWS ────────────────────────── */}
            <div className="flex items-center border-b border-edge/5 bg-surface-900/35 flex-shrink-0 h-10">
                {tabScroll.left && (
                    <button
                        onClick={() => tabsRef.current?.scrollBy({ left: -180, behavior: 'smooth' })}
                        className="flex-shrink-0 h-full w-8 flex items-center justify-center text-gray-500 hover:text-heading hover:bg-surface-800/50 transition-colors"
                        aria-label="Scroll watchlists left"
                    >
                        <ChevronLeft className="w-4 h-4" />
                    </button>
                )}

                <div
                    ref={tabsRef}
                    className="flex-1 h-full overflow-x-auto overflow-y-hidden no-scrollbar flex items-stretch"
                    style={{ scrollbarWidth: 'none' }}
                    onScroll={updateTabScroll}
                >
                    {watchlists.map((wl) => {
                        const isActive = wl.id === activeId;
                        return (
                            <button
                                key={wl.id}
                                onClick={() => setActiveWatchlist(wl.id)}
                                className={cn(
                                    'px-4 h-full flex items-center justify-center flex-shrink-0 text-sm font-medium font-sans border-b-2 transition-colors whitespace-nowrap',
                                    isActive
                                        ? 'text-primary-600 border-primary-500 bg-primary-500/5'
                                        : 'text-gray-500 border-transparent hover:text-heading hover:bg-surface-800/30'
                                )}
                            >
                                {wl.name}
                            </button>
                        );
                    })}
                </div>

                {tabScroll.right && (
                    <button
                        onClick={() => tabsRef.current?.scrollBy({ left: 180, behavior: 'smooth' })}
                        className="flex-shrink-0 h-full w-8 flex items-center justify-center text-gray-500 hover:text-heading hover:bg-surface-800/50 transition-colors"
                        aria-label="Scroll watchlists right"
                    >
                        <ChevronRight className="w-4 h-4" />
                    </button>
                )}
            </div>

            {/* ── CONTENT AREA ──────────────────────────────────────────── */}
            <div ref={scrollEl} className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden flex flex-col">
                {isLoading ? (
                    // Loading state
                    <div>{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} variant="watchlist-row" />)}</div>
                ) : items.length === 0 ? (
                    // Empty state with centered "Add Symbol" button
                    <div className="flex flex-col items-center justify-center h-full text-gray-600 gap-4 px-4">
                        <div className="text-center">
                            <p className="text-sm font-medium mb-2">Watchlist is empty</p>
                            <p className="text-xs opacity-75">Add stocks to get started</p>
                        </div>
                        <button
                            onClick={() => setModalOpen(true)}
                            className="px-6 py-3 bg-primary-600/20 hover:bg-primary-600/30 text-primary-600 rounded-lg font-semibold text-sm transition-colors flex items-center gap-2"
                        >
                            <Plus className="w-4 h-4" />
                            Add Symbol
                        </button>
                    </div>
                ) : (
                    // Stock list
                    <div className="flex flex-col h-full">
                        <div className="flex-1 min-h-0 overflow-y-auto">
                            {items.map((item, index) => {
                                const price = getPriceForSymbol(mergedPrices, item.symbol);
                                const itemKey = normalizeSymbolKey(item.symbol);
                                const selectedKey = normalizeSymbolKey(selectedSymbol);
                                const isSelectedRow = itemKey && selectedKey && itemKey === selectedKey;
                                const rawSymbol = String(item.symbol || '');
                                const exchange = String(item.exchange || (rawSymbol.endsWith('.BO') ? 'BSE' : 'NSE')).toUpperCase();
                                const chartSymbol = rawSymbol.startsWith('^') || rawSymbol.endsWith('.NS') || rawSymbol.endsWith('.BO') || isCommoditySymbol(rawSymbol)
                                    ? rawSymbol
                                    : exchange === 'BSE' ? `${rawSymbol}.BO` : `${rawSymbol}.NS`;
                                const effectivePrice = price;
                                const isDragging = dragIndex === index;
                                const isDragOver = dragOverIndex === index && dragIndex !== index;

                                return (
                                    <div
                                        key={item.id}
                                        draggable
                                        onDragStart={(e) => {
                                            setDragIndex(index);
                                            e.dataTransfer.effectAllowed = 'move';
                                            e.dataTransfer.setData('text/plain', index.toString());
                                        }}
                                        onDragEnd={() => {
                                            setDragIndex(null);
                                            setDragOverIndex(null);
                                        }}
                                        onDragOver={(e) => {
                                            e.preventDefault();
                                            e.dataTransfer.dropEffect = 'move';
                                            if (dragOverIndex !== index) setDragOverIndex(index);
                                        }}
                                        onDragEnter={(e) => {
                                            e.preventDefault();
                                            setDragOverIndex(index);
                                        }}
                                        onDrop={(e) => {
                                            e.preventDefault();
                                            if (dragIndex !== null && dragIndex !== index) {
                                                reorderItems(dragIndex, index);
                                            }
                                            setDragIndex(null);
                                            setDragOverIndex(null);
                                        }}
                                        className={cn(
                                            isDragging && 'opacity-30',
                                            isDragOver && 'border-t-2 border-t-primary-500',
                                        )}
                                    >
                                        <WatchlistItem
                                            item={item}
                                            price={effectivePrice}
                                            isSelected={isSelectedRow}
                                            onSelect={() => onSelectSymbol?.(chartSymbol)}
                                            onRemove={removeItem}
                                            onBuy={onBuy ? () => onBuy(chartSymbol) : undefined}
                                            onSell={onSell ? () => onSell(chartSymbol) : undefined}
                                        />
                                    </div>
                                );
                            })}
                        </div>

                        <div className="px-3 py-1.5 border-t border-edge/5 text-[11px] text-gray-600 flex-shrink-0">
                            {items.length} symbol{items.length !== 1 ? 's' : ''} in watchlist
                        </div>
                    </div>
                )}
            </div>

            {/* ── ADD SYMBOL MODAL ──────────────────────────────────────── */}
            <AddSymbolModal
                isOpen={modalOpen}
                onClose={() => setModalOpen(false)}
                onAddSymbol={handleAddSymbol}
                watchlistItems={items}
            />

            {/* ── WATCHLIST SIDEBAR ─────────────────────────────────────── */}
            <WatchlistSidebar
                watchlists={watchlists}
                activeId={activeId}
                onSelectWatchlist={setActiveWatchlist}
                onCreateNew={() => setCreateModalOpen(true)}
                onRenameWatchlist={renameWatchlist}
                onDeleteWatchlist={deleteWatchlist}
                isOpen={sidebarOpen}
                onClose={() => setSidebarOpen(false)}
            />

            {/* ── CREATE WATCHLIST MODAL ──────────────────────────────── */}
            <Modal
                isOpen={createModalOpen}
                onClose={() => {
                    setCreateModalOpen(false);
                    setNewWlName('');
                }}
                title="Create Watchlist"
                size="sm"
            >
                <div className="p-5">
                    <p className="text-sm text-gray-500 mb-4">Enter a name for the new watchlist.</p>
                    <input
                        autoFocus
                        value={newWlName}
                        onChange={(e) => setNewWlName(e.target.value)}
                        onKeyDown={handleCreateKeyDown}
                        placeholder={`Watchlist ${watchlists.length + 1}`}
                        maxLength={24}
                        className="w-full h-10 px-3 rounded-lg bg-surface-800/70 border border-edge/10 text-sm text-heading placeholder-gray-500 focus:outline-none focus:border-primary-500/50"
                    />
                    <div className="mt-4 flex items-center justify-end gap-2">
                        <button
                            onClick={() => {
                                setCreateModalOpen(false);
                                setNewWlName('');
                            }}
                            className="px-4 py-2 rounded-lg border border-edge/10 text-sm text-gray-500 hover:text-heading hover:bg-surface-800/50 transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handleCreateSubmit}
                            className="px-4 py-2 rounded-lg bg-primary-600 text-white text-sm font-semibold hover:bg-primary-600/90 transition-colors"
                        >
                            Create
                        </button>
                    </div>
                </div>
            </Modal>
        </div>
    );
}
