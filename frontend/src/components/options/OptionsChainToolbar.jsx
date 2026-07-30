import { memo } from 'react';
import { cn } from '../../utils/cn';
import { OPTIONS_UNDERLYINGS, formatExpiryChip } from './constants';

function OptionsChainToolbar({
  selectedUnderlying,
  onSelectUnderlying,
  expiryList,
  selectedExpiry,
  onSelectExpiry,
  onCenterAtm,
}) {
  return (
    <div className="flex-shrink-0 border-b border-edge/10 bg-surface-900/80 px-2 py-2 space-y-2">
      <div className="flex gap-1 overflow-x-auto overscroll-x-contain pb-0.5">
        {OPTIONS_UNDERLYINGS.map((u) => (
          <button
            key={u}
            type="button"
            onClick={() => onSelectUnderlying(u)}
            className={cn(
              'px-2 py-1 rounded-md text-[10px] font-bold border whitespace-nowrap transition-colors',
              selectedUnderlying === u
                ? 'bg-primary-600/20 border-primary-500/40 text-primary-600'
                : 'options-chain-chip border-edge/20',
            )}
          >
            {u}
          </button>
        ))}
      </div>
      {expiryList?.length > 0 && (
        <div className="flex gap-1 overflow-x-auto">
          {expiryList.map((date) => (
            <button
              key={date}
              type="button"
              onClick={() => onSelectExpiry(date)}
              className={cn(
                'px-2 py-0.5 rounded text-[10px] font-semibold border whitespace-nowrap',
                selectedExpiry === date
                  ? 'bg-primary-600/15 border-primary-500/35 text-primary-600'
                  : 'options-chain-chip border-edge/15',
              )}
            >
              {formatExpiryChip(date)}
            </button>
          ))}
        </div>
      )}
      <button
        type="button"
        onClick={onCenterAtm}
        className="w-full py-1 text-[10px] font-semibold rounded-md border border-edge/15 options-chain-chip hover:bg-overlay/[0.04]"
      >
        Center ATM
      </button>
    </div>
  );
}

export default memo(OptionsChainToolbar);
