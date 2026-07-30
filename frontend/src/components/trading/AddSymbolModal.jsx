import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { Search, X, Star } from 'lucide-react';
import api from '../../services/api';
import { cleanSymbol } from '../../utils/formatters';
import { cn } from '../../utils/cn';

/**
 * AddSymbolModal — centered modal for searching and adding symbols to watchlist
 * Triggered by:
 * 1. Empty watchlist "Add Symbol" button
 * 2. Search bar in watchlist when user has symbols
 */
export default function AddSymbolModal({ isOpen, onClose, onAddSymbol, watchlistItems = [] }) {
    const [searchQuery, setSearchQuery] = useState('');
    const [results, setResults] = useState([]);
    const [isSearching, setIsSearching] = useState(false);
    const searchInputRef = useRef(null);

    // Auto-focus input when modal opens
    useEffect(() => {
        if (isOpen) {
            setTimeout(() => searchInputRef.current?.focus(), 0);
            setSearchQuery('');
            setResults([]);
        }
    }, [isOpen]);

    // Close on Escape
    useEffect(() => {
        if (!isOpen) return;
        const handleKeyDown = (e) => {
            if (e.key === 'Escape') onClose();
        };
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, onClose]);

    // Search for symbols with debounce
    useEffect(() => {
        if (searchQuery.length < 1) {
            setResults([]);
            return;
        }

        setIsSearching(true);
        const timer = setTimeout(async () => {
            try {
                const res = await api.get(`/market/search?q=${encodeURIComponent(searchQuery)}`);
                setResults(res.data.results || []);
            } catch (err) {
                console.error('Search failed:', err);
                setResults([]);
            } finally {
                setIsSearching(false);
            }
        }, 300);

        return () => clearTimeout(timer);
    }, [searchQuery]);

    // Check if a symbol is already in the watchlist
    const isSymbolAdded = useCallback((symbol) => {
        return watchlistItems.some(
            (item) =>
                cleanSymbol(item.symbol) === cleanSymbol(symbol) ||
                item.symbol === symbol
        );
    }, [watchlistItems]);

    // Handle adding a symbol
    const handleAdd = useCallback(
        (symbol, exchange = 'NSE') => {
            if (!isSymbolAdded(symbol)) {
                onAddSymbol?.(symbol, exchange);
                setSearchQuery('');
                setResults([]);
            }
        },
        [onAddSymbol, isSymbolAdded]
    );

    if (!isOpen) return null;

    return createPortal(
        <div
            className="fixed inset-0 z-[1000] bg-black/40 backdrop-blur-sm flex items-center justify-center p-4 animate-fade-in"
            onClick={onClose}
            onMouseDown={(e) => {
                // Close only if clicking the backdrop, not the modal content
                if (e.currentTarget === e.target) onClose();
            }}
        >
            <div
                className="bg-surface-900 border border-edge/10 rounded-xl shadow-2xl w-full max-w-[500px] max-h-[600px] flex flex-col animate-scale-in"
                onClick={(e) => e.stopPropagation()}
                onMouseDown={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="px-6 py-4 border-b border-edge/5 flex items-center justify-between flex-shrink-0">
                    <h2 className="text-lg font-semibold text-heading">Add to Watchlist</h2>
                    <button
                        onClick={onClose}
                        className="p-1 text-gray-500 hover:text-gray-400 hover:bg-surface-800 rounded-lg transition-colors"
                        aria-label="Close"
                    >
                        <X className="w-5 h-5" />
                    </button>
                </div>

                {/* Search Input */}
                <div className="px-6 py-3 border-b border-edge/5 flex-shrink-0">
                    <div className="relative">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
                        <input
                            ref={searchInputRef}
                            type="text"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            placeholder="Search stocks... (e.g. RELIANCE, TCS)"
                            className="w-full pl-9 pr-6 py-2.5 bg-surface-800/40 border border-edge/10 rounded-lg text-heading placeholder-gray-500 focus:outline-none focus:border-primary-500/30 text-sm transition-colors"
                        />
                        {searchQuery && (
                            <button
                                onClick={() => {
                                    setSearchQuery('');
                                    setResults([]);
                                }}
                                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-400 p-1"
                            >
                                <X className="w-4 h-4" />
                            </button>
                        )}
                    </div>
                </div>

                {/* Results List */}
                <div className="flex-1 min-h-0 overflow-y-auto">
                    {searchQuery.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-40 text-gray-500 text-sm">
                            <Search className="w-8 h-8 mb-2 opacity-50" />
                            <p>Enter a stock symbol to search</p>
                        </div>
                    ) : isSearching ? (
                        <div className="flex items-center justify-center h-40 text-gray-500">
                            <div className="flex flex-col items-center gap-2">
                                <div className="w-5 h-5 border-2 border-primary-500/20 border-t-primary-500 rounded-full animate-spin" />
                                <p className="text-xs">Searching...</p>
                            </div>
                        </div>
                    ) : results.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-40 text-gray-500 text-sm">
                            <p>No results found for "{searchQuery}"</p>
                            <p className="text-xs mt-1 opacity-75">Try a different symbol</p>
                        </div>
                    ) : (
                        <div className="divide-y divide-edge/[0.05]">
                            {results.map((symbol) => {
                                const alreadyAdded = isSymbolAdded(symbol.symbol);
                                return (
                                    <div
                                        key={symbol.symbol}
                                        className={cn(
                                            'px-6 py-3 flex items-center justify-between transition-colors',
                                            alreadyAdded
                                                ? 'bg-surface-800/20 opacity-60'
                                                : 'hover:bg-surface-800/40 cursor-pointer'
                                        )}
                                        onClick={() =>
                                            !alreadyAdded && handleAdd(symbol.symbol, symbol.exchange || 'NSE')
                                        }
                                    >
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2.5">
                                                <span className="text-sm font-semibold text-heading">
                                                    {cleanSymbol(symbol.symbol)}
                                                </span>
                                                <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-gray-200 text-gray-700">
                                                    {symbol.exchange || 'NSE'}
                                                </span>
                                            </div>
                                            <div className="text-xs text-gray-500 truncate mt-0.5">
                                                {symbol.name || 'Company'}
                                            </div>
                                        </div>
                                        {alreadyAdded ? (
                                            <Star className="w-5 h-5 text-sky-400 flex-shrink-0 ml-3" fill="currentColor" />
                                        ) : (
                                            <button
                                                className="ml-3 px-3 py-1.5 rounded-lg bg-primary-600/20 text-primary-600 hover:bg-primary-600/30 text-xs font-semibold transition-colors flex-shrink-0"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    handleAdd(
                                                        symbol.symbol,
                                                        symbol.exchange || 'NSE'
                                                    );
                                                }}
                                            >
                                                Add
                                            </button>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        </div>,
        document.getElementById('portal-root') || document.body
    );
}
