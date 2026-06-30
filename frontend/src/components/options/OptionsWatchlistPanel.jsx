import { memo, useState, useCallback } from 'react';
import { Search, Pin } from 'lucide-react';
import { cn } from '../../utils/cn';
import { OPTIONS_UNDERLYINGS, formatExpiryChip } from './constants';

function OptionsWatchlistPanel({
  selectedUnderlying,
  onSelectUnderlying,
  expiryList,
  selectedExpiry,
  onSelectExpiry,
  recentSymbols = [],
  pinnedStrike,
  onPinStrike,
  onScrollToAtm,
  optionType,
  onOptionTypeChange,
}) {
  const [search, setSearch] = useState('');

  const filtered = OPTIONS_UNDERLYINGS.filter((u) =>
    u.toLowerCase().includes(search.trim().toLowerCase()),
  );

  return (
    <div className="flex flex-col h-full min-h-0 bg-surface-900 border-r border-edge/5">
      <div className="px-3 py-2.5 border-b border-edge/5 flex-shrink-0">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-500 mb-2">
          Options Desk
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search underlying…"
            className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg bg-surface-800/60 border border-edge/10 text-heading placeholder-gray-600 focus:outline-none focus:border-primary-500/30"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0 px-2 py-2 space-y-3">
        <section>
          <div className="text-[9px] font-semibold uppercase tracking-wider text-gray-500 px-1 mb-1.5">
            Index Underlyings
          </div>
          <div className="space-y-0.5">
            {filtered.map((u) => (
              <button
                key={u}
                type="button"
                onClick={() => onSelectUnderlying(u)}
                className={cn(
                  'w-full text-left px-2.5 py-2 rounded-lg text-xs font-semibold transition-colors',
                  selectedUnderlying === u
                    ? 'bg-primary-600/15 text-primary-600 border border-primary-500/25'
                    : 'text-gray-400 hover:text-heading hover:bg-overlay/[0.04] border border-transparent',
                )}
              >
                {u}
              </button>
            ))}
          </div>
        </section>

        {expiryList?.length > 0 && (
          <section>
            <div className="text-[9px] font-semibold uppercase tracking-wider text-gray-500 px-1 mb-1.5">
              Expiry
            </div>
            <div className="flex flex-wrap gap-1">
              {expiryList.map((date) => (
                <button
                  key={date}
                  type="button"
                  onClick={() => onSelectExpiry(date)}
                  className={cn(
                    'px-2 py-1 rounded-md text-[10px] font-semibold border transition-colors',
                    selectedExpiry === date
                      ? 'bg-primary-600/20 border-primary-500/35 text-primary-600'
                      : 'bg-surface-800/60 border-edge/15 text-gray-500 hover:text-heading',
                  )}
                >
                  {formatExpiryChip(date)}
                </button>
              ))}
            </div>
          </section>
        )}

        <section>
          <div className="text-[9px] font-semibold uppercase tracking-wider text-gray-500 px-1 mb-1.5">
            CE / PE
          </div>
          <div className="flex rounded-lg overflow-hidden border border-edge/10 bg-surface-800/60 p-0.5">
            {['CE', 'PE'].map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => onOptionTypeChange(t)}
                className={cn(
                  'flex-1 py-1.5 text-xs font-bold rounded-md transition-all',
                  optionType === t
                    ? t === 'CE'
                      ? 'bg-emerald-500/20 text-emerald-500'
                      : 'bg-red-500/20 text-red-500'
                    : 'text-gray-500',
                )}
              >
                {t}
              </button>
            ))}
          </div>
        </section>

        <section className="flex gap-1">
          <button
            type="button"
            onClick={onScrollToAtm}
            className="flex-1 py-1.5 text-[10px] font-semibold rounded-md border border-edge/15 text-gray-500 hover:text-heading hover:bg-overlay/[0.04]"
          >
            Center ATM
          </button>
          <button
            type="button"
            onClick={() => onPinStrike?.(pinnedStrike ? null : 'atm')}
            className={cn(
              'px-2 py-1.5 rounded-md border text-gray-500 hover:text-heading',
              pinnedStrike && 'text-primary-600 border-primary-500/30 bg-primary-600/10',
            )}
            title="Pin ATM row"
          >
            <Pin className="w-3.5 h-3.5" />
          </button>
        </section>

        {recentSymbols.length > 0 && (
          <section>
            <div className="text-[9px] font-semibold uppercase tracking-wider text-gray-500 px-1 mb-1.5">
              Recent
            </div>
            {recentSymbols.slice(0, 6).map((sym) => (
              <div key={sym} className="px-2 py-1 text-[10px] text-gray-400 truncate">
                {sym}
              </div>
            ))}
          </section>
        )}
      </div>
    </div>
  );
}

export default memo(OptionsWatchlistPanel);
