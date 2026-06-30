import { useState, useCallback, useRef, useEffect } from 'react';
import FuturesWatchlistItem from './FuturesWatchlistItem';
import AddFuturesContractModal from './AddFuturesContractModal';
import FuturesWatchlistSidebar from './FuturesWatchlistSidebar';
import Modal from '../ui/Modal';
import Skeleton from '../ui/Skeleton';
import { cn } from '../../utils/cn';
import {
    Plus, Menu, Search, ChevronLeft, ChevronRight,
} from 'lucide-react';
import { useFuturesWatchlistStore } from '../../stores/useFuturesWatchlistStore';
import useUnifiedFuturesStore from '../../stores/useUnifiedFuturesStore';

// ── Main Futures Watchlist Component ──────────────────────────────────────────
export default function FuturesWatchlist({
    selectedContractSymbol,
    selectedContractPrice = null,
    suppressSelectedPrice = false,
    onSelectContract,
    onUnderlyingSelected,
    onClose,
    forceOpenAddContractToken = 0,
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
    } = useFuturesWatchlistStore();

    const liveQuotes = useUnifiedFuturesStore((s) => s.quotes);
    const lastQuoteUpdate = useUnifiedFuturesStore((s) => s._lastQuoteUpdate);

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

    // ── Update tab scroll visibility ─────────────────────────────────────────
    const updateTabScroll = useCallback(() => {
        if (!tabsRef.current) return;
        const el = tabsRef.current;
        setTabScroll({
            left: el.scrollLeft > 0,
            right: el.scrollLeft < el.scrollWidth - el.clientWidth - 5,
        });
    }, []);

    useEffect(() => {
        updateTabScroll();
        if (tabsRef.current) {
            tabsRef.current.addEventListener('scroll', updateTabScroll);
            return () => tabsRef.current?.removeEventListener('scroll', updateTabScroll);
        }
    }, [updateTabScroll]);

    useEffect(() => {
        if (!forceOpenAddContractToken) return;
        setModalOpen(true);
    }, [forceOpenAddContractToken]);

    // Fetch prices when active watchlist changes or on interval
    useEffect(() => {
        fetchPrices();
        // Fallback REST refresh only — live ticks come from Zebu WebSocket
        const interval = setInterval(() => fetchPrices(), 60_000);
        return () => clearInterval(interval);
    }, [activeId, fetchPrices]);

    const handleAddContract = async (contractSymbol, underlying) => {
        await addItem(contractSymbol);
        onSelectContract?.(contractSymbol);
        if (underlying) onUnderlyingSelected?.(underlying);
        setModalOpen(false);
    };

    const handleRemoveItem = async (itemId) => {
        await removeItem(itemId);
    };

    const handleCreateKeyDown = (e) => {
        if (e.key === 'Enter') handleCreateSubmit();
        if (e.key === 'Escape') {
            setCreateModalOpen(false);
            setNewWlName('');
        }
    };

    const handleCreateSubmit = async () => {
        if (newWlName.trim()) {
            await createWatchlist(newWlName);
            setCreateModalOpen(false);
            setNewWlName('');
        }
    };

    const reorderItemsHandler = (fromIndex, toIndex) => {
        if (fromIndex === toIndex) return;
        const newItems = [...items];
        const [removed] = newItems.splice(fromIndex, 1);
        newItems.splice(toIndex, 0, removed);
        reorderItems(newItems);
    };

    return (
        <div className="flex flex-col h-full bg-surface-900/60 border-r border-edge/10">
            {/* ── HEADER with watchlist controls ─────────────────────────────────── */}
            <div className="flex-shrink-0 h-12 flex items-center px-3 border-b border-edge/5 bg-surface-900/40 gap-1.5">
                <button
                    onClick={() => setSidebarOpen(true)}
                    className="flex-shrink-0 h-9 w-9 rounded-lg flex items-center justify-center text-gray-500 hover:text-heading hover:bg-surface-800/60 transition-colors"
                    title="Watchlist menu"
                >
                    <Menu className="w-4 h-4" />
                </button>

                <button
                    onClick={() => setModalOpen(true)}
                    className="flex-shrink-0 h-9 w-9 rounded-lg flex items-center justify-center text-gray-500 hover:text-heading hover:bg-surface-800/60 transition-colors"
                    title="Search or add contract"
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

            {/* ── TABS (watchlist names) ───────────────────────────────────────── */}
            <div className="flex-shrink-0 h-10 flex items-center bg-surface-900/30 border-b border-edge/5 group">
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
                                    'px-4 h-full flex items-center justify-center flex-shrink-0 text-xs font-medium border-b-2 transition-colors whitespace-nowrap',
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

            {/* ── CONTENT AREA ──────────────────────────────────────────────────────── */}
            <div ref={scrollEl} className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden flex flex-col">
                {isLoading ? (
                    // Loading state
                    <div>{Array.from({ length: 8 }, (_, i) => <Skeleton key={i} variant="watchlist-row" />)}</div>
                ) : items.length === 0 ? (
                    // Empty state with centered "Add Contract" button
                    <div className="flex flex-col items-center justify-center h-full text-gray-600 gap-2 px-3">
                        <div className="text-center">
                            <p className="text-sm font-medium mb-1">Watchlist is empty</p>
                            <p className="text-xs opacity-75">Add futures contracts to get started</p>
                        </div>
                        <button
                            onClick={() => setModalOpen(true)}
                            className="px-4 py-2 bg-primary-600/20 hover:bg-primary-600/30 text-primary-600 rounded-lg font-semibold text-xs transition-colors flex items-center gap-2"
                        >
                            <Plus className="w-4 h-4" />
                            Add Contract
                        </button>
                    </div>
                ) : (
                    // Contracts list
                    <div className="flex flex-col h-full">
                        <div className="flex-1 min-h-0 overflow-y-auto">
                            {items.map((item, index) => {
                                const sym = item.contract_symbol;
                                const price = {
                                    ...(watchlistPrices[sym] || {}),
                                    ...(liveQuotes[sym] || {}),
                                };
                                void lastQuoteUpdate;
                                const isSelectedRow = selectedContractSymbol?.toUpperCase() === sym;

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
                                                reorderItemsHandler(dragIndex, index);
                                            }
                                            setDragIndex(null);
                                            setDragOverIndex(null);
                                        }}
                                        className={cn(
                                            dragIndex === index && 'opacity-30',
                                            dragOverIndex === index && dragIndex !== index && 'border-t-2 border-t-primary-500',
                                        )}
                                    >
                                        <FuturesWatchlistItem
                                            item={item}
                                            price={price}
                                            isSelected={isSelectedRow}
                                            onSelect={() => onSelectContract?.(item.contract_symbol)}
                                            onRemove={() => handleRemoveItem(item.id)}
                                        />
                                    </div>
                                );
                            })}
                        </div>

                        <div className="px-3 py-1.5 border-t border-edge/5 text-[11px] text-gray-600 flex-shrink-0">
                            {items.length} contract{items.length !== 1 ? 's' : ''} in watchlist
                        </div>
                    </div>
                )}
            </div>

            {/* ── ADD CONTRACT MODAL ────────────────────────────────────────── */}
            <AddFuturesContractModal
                isOpen={modalOpen}
                onClose={() => setModalOpen(false)}
                onAddContract={handleAddContract}
                watchlistItems={items}
            />

            {/* ── WATCHLIST SIDEBAR ─────────────────────────────────────────── */}
            <FuturesWatchlistSidebar
                watchlists={watchlists}
                activeId={activeId}
                onSelectWatchlist={setActiveWatchlist}
                onCreateNew={() => setCreateModalOpen(true)}
                onRenameWatchlist={renameWatchlist}
                onDeleteWatchlist={deleteWatchlist}
                isOpen={sidebarOpen}
                onClose={() => setSidebarOpen(false)}
            />

            {/* ── CREATE WATCHLIST MODAL ────────────────────────────────── */}
            <Modal
                isOpen={createModalOpen}
                onClose={() => {
                    setCreateModalOpen(false);
                    setNewWlName('');
                }}
                title="Create Futures Watchlist"
                size="sm"
            >
                <div className="p-5">
                    <p className="text-sm text-gray-500 mb-4">Enter a name for the new futures watchlist.</p>
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
