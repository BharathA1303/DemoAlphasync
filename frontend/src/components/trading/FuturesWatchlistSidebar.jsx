import { useState } from 'react';
import { X, Trash2, Edit2, Plus } from 'lucide-react';
import { cn } from '../../utils/cn';
import Modal from '../ui/Modal';

export default function FuturesWatchlistSidebar({
    watchlists,
    activeId,
    onSelectWatchlist,
    onCreateNew,
    onRenameWatchlist,
    onDeleteWatchlist,
    isOpen,
    onClose,
}) {
    const [renameId, setRenameId] = useState(null);
    const [newName, setNewName] = useState('');

    const handleRenameStart = (watchlist) => {
        setRenameId(watchlist.id);
        setNewName(watchlist.name);
    };

    const handleRenameSave = async () => {
        if (newName.trim() && renameId) {
            await onRenameWatchlist(renameId, newName);
            setRenameId(null);
            setNewName('');
        }
    };

    const handleRenameCancel = () => {
        setRenameId(null);
        setNewName('');
    };

    const handleDeleteConfirm = async (id) => {
        await onDeleteWatchlist(id);
    };

    return (
        <>
            {/* Overlay */}
            {isOpen && (
                <div
                    className="fixed inset-0 bg-black/30 z-40"
                    onClick={onClose}
                />
            )}

            {/* Sidebar */}
            <div
                className={cn(
                    'fixed right-0 top-0 h-screen w-80 bg-surface-900 border-l border-edge/10 shadow-2xl z-50 transition-transform duration-300 flex flex-col',
                    isOpen ? 'translate-x-0' : 'translate-x-full'
                )}
            >
                {/* Header */}
                <div className="flex-shrink-0 h-14 flex items-center justify-between px-4 border-b border-edge/5">
                    <h2 className="text-sm font-bold text-heading">Watchlists</h2>
                    <button
                        onClick={onClose}
                        className="p-1.5 rounded-lg hover:bg-surface-800/60 text-gray-500 hover:text-heading transition-colors"
                    >
                        <X className="w-4 h-4" />
                    </button>
                </div>

                {/* Watchlists list */}
                <div className="flex-1 min-h-0 overflow-y-auto space-y-1 p-3">
                    {watchlists.map((watchlist) => {
                        const isActive = watchlist.id === activeId;
                        const isRenaming = renameId === watchlist.id;

                        return (
                            <div
                                key={watchlist.id}
                                className={cn(
                                    'group rounded-lg border transition-all',
                                    isActive
                                        ? 'bg-primary-500/10 border-primary-500/30'
                                        : 'border-edge/10 hover:border-edge/20 hover:bg-surface-800/30'
                                )}
                            >
                                <div className="flex items-center justify-between px-3 py-2.5">
                                    {isRenaming ? (
                                        <input
                                            autoFocus
                                            value={newName}
                                            onChange={(e) => setNewName(e.target.value)}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter') handleRenameSave();
                                                if (e.key === 'Escape') handleRenameCancel();
                                            }}
                                            className="flex-1 text-sm bg-surface-800/60 border border-edge/10 rounded px-2 py-1 text-heading focus:outline-none focus:border-primary-500/30"
                                        />
                                    ) : (
                                        <button
                                            onClick={() => onSelectWatchlist(watchlist.id)}
                                            className="flex-1 text-left"
                                        >
                                            <p className={cn('text-sm font-medium truncate', isActive ? 'text-primary-600' : 'text-heading')}>
                                                {watchlist.name}
                                            </p>
                                            <p className="text-xs text-gray-500 mt-0.5">
                                                {watchlist.items?.length ?? 0} contract{(watchlist.items?.length ?? 0) !== 1 ? 's' : ''}
                                            </p>
                                        </button>
                                    )}

                                    {isRenaming ? (
                                        <div className="flex gap-1 flex-shrink-0 ml-2">
                                            <button
                                                onClick={handleRenameSave}
                                                className="px-2 py-1 rounded text-xs font-medium bg-primary-600 text-white hover:bg-primary-600/90"
                                            >
                                                Save
                                            </button>
                                            <button
                                                onClick={handleRenameCancel}
                                                className="px-2 py-1 rounded text-xs text-gray-500 hover:bg-surface-800/60"
                                            >
                                                Cancel
                                            </button>
                                        </div>
                                    ) : (
                                        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 ml-2">
                                            <button
                                                onClick={() => handleRenameStart(watchlist)}
                                                className="p-1 rounded-md text-gray-500 hover:text-heading hover:bg-surface-800/60 transition-colors"
                                                title="Rename"
                                            >
                                                <Edit2 className="w-3.5 h-3.5" />
                                            </button>
                                            <button
                                                onClick={() => handleDeleteConfirm(watchlist.id)}
                                                className="p-1 rounded-md text-gray-500 hover:text-red-500 hover:bg-red-500/10 transition-colors"
                                                title="Delete"
                                            >
                                                <Trash2 className="w-3.5 h-3.5" />
                                            </button>
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>

                {/* Create new button */}
                <div className="flex-shrink-0 border-t border-edge/5 p-3">
                    <button
                        onClick={() => {
                            onCreateNew?.();
                            onClose();
                        }}
                        className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-primary-600/20 hover:bg-primary-600/30 text-primary-600 transition-colors font-semibold text-sm"
                    >
                        <Plus className="w-4 h-4" />
                        Create Watchlist
                    </button>
                </div>
            </div>
        </>
    );
}
