import { useState, useEffect, useRef } from 'react';
import { Circle, CheckCircle2, Plus, Pencil, Trash2 } from 'lucide-react';
import Modal from '../ui/Modal';
import { cn } from '../../utils/cn';

/**
 * Watchlist manager modal — centered, keyboard-friendly, mobile-safe.
 */
export default function WatchlistSidebar({
    watchlists = [],
    activeId = null,
    onSelectWatchlist,
    onCreateNew,
    onRenameWatchlist,
    onDeleteWatchlist,
    isOpen,
    onClose,
}) {
    const [renamingId, setRenamingId] = useState(null);
    const [renameValue, setRenameValue] = useState('');
    const renameInputRef = useRef(null);

    useEffect(() => {
        if (renamingId) {
            setTimeout(() => renameInputRef.current?.select(), 0);
        }
    }, [renamingId]);

    if (!isOpen) return null;

    const startRename = (wl) => {
        setRenamingId(wl.id);
        setRenameValue(wl.name);
    };

    const commitRename = () => {
        const trimmed = renameValue.trim();
        if (renamingId && trimmed && trimmed !== watchlists.find((w) => w.id === renamingId)?.name) {
            onRenameWatchlist?.(renamingId, trimmed);
        }
        setRenamingId(null);
        setRenameValue('');
    };

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title="Select Watchlist"
            size="lg"
            className="max-w-[640px]"
        >
            <div className="p-4 sm:p-5">
                <div className="flex items-center justify-between gap-3 mb-4">
                    <div className="text-sm text-gray-500">
                        Choose a watchlist or create a new one
                    </div>
                    <button
                        onClick={() => {
                            onCreateNew?.();
                            onClose?.();
                        }}
                        className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-primary-600/15 text-primary-600 hover:bg-primary-600/20 text-sm font-semibold transition-colors"
                    >
                        <Plus className="w-4 h-4" />
                        New Watchlist
                    </button>
                </div>

                <div className="max-h-[420px] overflow-y-auto rounded-xl border border-edge/10">
                    {watchlists.length === 0 ? (
                        <div className="p-6 text-center text-gray-500 text-sm">
                            No watchlists yet
                        </div>
                    ) : (
                        <div className="divide-y divide-edge/5">
                            {watchlists.map((wl) => {
                                const isActive = wl.id === activeId;
                                const isRenaming = renamingId === wl.id;

                                return (
                                    <div
                                        key={wl.id}
                                        className={cn(
                                            'px-4 py-3 flex items-center gap-3 transition-colors',
                                            isActive ? 'bg-primary-500/8' : 'hover:bg-surface-800/35'
                                        )}
                                    >
                                        <button
                                            type="button"
                                            onClick={() => {
                                                onSelectWatchlist?.(wl.id);
                                                onClose?.();
                                            }}
                                            className="flex items-center gap-3 flex-1 min-w-0 text-left"
                                        >
                                            {isActive ? (
                                                <CheckCircle2 className="w-5 h-5 text-primary-600 flex-shrink-0" />
                                            ) : (
                                                <Circle className="w-5 h-5 text-gray-500 flex-shrink-0" />
                                            )}

                                            <div className="min-w-0 flex-1">
                                                {isRenaming ? (
                                                    <input
                                                        ref={renameInputRef}
                                                        value={renameValue}
                                                        onChange={(e) => setRenameValue(e.target.value)}
                                                        onKeyDown={(e) => {
                                                            if (e.key === 'Enter') commitRename();
                                                            if (e.key === 'Escape') {
                                                                setRenamingId(null);
                                                                setRenameValue('');
                                                            }
                                                        }}
                                                        onBlur={commitRename}
                                                        onClick={(e) => e.stopPropagation()}
                                                        className="w-full px-2 py-1.5 bg-surface-800 border border-primary-500/30 rounded-lg text-sm text-heading focus:outline-none focus:border-primary-500/50"
                                                    />
                                                ) : (
                                                    <>
                                                        <p className="text-sm font-medium font-sans text-heading truncate">{wl.name}</p>
                                                        <p className="text-xs text-gray-500 mt-0.5">
                                                            {wl.items?.length ?? 0} symbol{(wl.items?.length ?? 0) === 1 ? '' : 's'}
                                                        </p>
                                                    </>
                                                )}
                                            </div>
                                        </button>

                                        <div className="flex items-center gap-1 flex-shrink-0">
                                            {!isRenaming && (
                                                <>
                                                    <button
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            startRename(wl);
                                                        }}
                                                        className="p-2 text-gray-500 hover:text-primary-600 hover:bg-surface-800 rounded-lg transition-colors"
                                                        title="Rename"
                                                    >
                                                        <Pencil className="w-4 h-4" />
                                                    </button>
                                                    <button
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            onDeleteWatchlist?.(wl.id);
                                                        }}
                                                        className="p-2 text-red-500 hover:bg-red-500/10 rounded-lg transition-colors"
                                                        title="Delete"
                                                    >
                                                        <Trash2 className="w-4 h-4" />
                                                    </button>
                                                </>
                                            )}
                                            {isRenaming && (
                                                <button
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        commitRename();
                                                    }}
                                                    className="p-2 text-primary-600 hover:bg-primary-600/10 rounded-lg transition-colors"
                                                    title="Save"
                                                >
                                                    <CheckCircle2 className="w-4 h-4" />
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                <div className="mt-4 flex items-center justify-between text-xs text-gray-500">
                    <span>{watchlists.length} watchlist{watchlists.length === 1 ? '' : 's'}</span>
                    <span>{watchlists.reduce((sum, wl) => sum + (wl.items?.length ?? 0), 0)} total symbols</span>
                </div>
            </div>
        </Modal>
    );
}
