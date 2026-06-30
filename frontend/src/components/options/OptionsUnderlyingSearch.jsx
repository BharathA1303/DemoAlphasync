import { memo, useState, useCallback, useEffect } from 'react';
import { Search } from 'lucide-react';
import { cn } from '../../utils/cn';
import { OPTIONS_UNDERLYINGS } from './constants';

/**
 * Underlying search for options desk — replaces index chip row (NIFTY/BANKNIFTY…).
 * Expiry is auto-selected server-side (nearest); no expiry chips here.
 */
function OptionsUnderlyingSearch({ selectedUnderlying, onSelectUnderlying, onCenterAtm }) {
  const [query, setQuery] = useState(selectedUnderlying || '');

  useEffect(() => {
    setQuery(selectedUnderlying || '');
  }, [selectedUnderlying]);

  const commitSearch = useCallback(() => {
    const raw = String(query || '').trim().toUpperCase();
    if (!raw) return;
    const match = OPTIONS_UNDERLYINGS.find((u) => u.startsWith(raw) || u === raw);
    onSelectUnderlying(match || raw.replace(/\.(NS|NSE)$/i, ''));
  }, [query, onSelectUnderlying]);

  return (
    <div className="flex-shrink-0 border-b border-edge/10 bg-surface-900/90 px-2 py-2 space-y-2">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500 pointer-events-none" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitSearch();
          }}
          onBlur={commitSearch}
          placeholder="Search underlying (NIFTY, RELIANCE…)"
          className="w-full pl-8 pr-3 py-2 text-xs rounded-lg bg-surface-800 border border-edge/15 text-heading placeholder:text-gray-500 focus:outline-none focus:border-primary-500/40"
          aria-label="Search options underlying"
        />
      </div>
      <button
        type="button"
        onClick={onCenterAtm}
        className={cn(
          'w-full py-1.5 text-[10px] font-semibold rounded-md border border-edge/20',
          'text-gray-400 hover:text-heading hover:bg-overlay/[0.06] transition-colors',
        )}
      >
        Center ATM
      </button>
    </div>
  );
}

export default memo(OptionsUnderlyingSearch);
