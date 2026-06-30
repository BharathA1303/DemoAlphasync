import { memo } from 'react';
import useUnifiedFuturesStore from '../../stores/useUnifiedFuturesStore';
import FuturesExpiryRow from './FuturesExpiryRow';

function FuturesExpiryLadder({ analytics, contractsLoading, onSelectContract }) {
  const selectedContract = useUnifiedFuturesStore((s) => s.contracts.selectedContract);
  const selectedUnderlying = useUnifiedFuturesStore((s) => s.contracts.selectedUnderlying);
  const rows = analytics?.expiryRows ?? [];

  if (!selectedUnderlying) {
    return (
      <div className="flex-1 flex items-center justify-center px-4 text-center text-xs text-gray-500">
        Search or add a symbol to view expiry contracts
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-surface-900/60">
      <div className="px-3 py-2 border-b border-edge/5 flex-shrink-0">
        <div className="text-sm font-semibold text-heading">{selectedUnderlying}</div>
        <div className="text-[10px] text-gray-500 mt-0.5">Futures expiries</div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain">
        {contractsLoading && rows.length === 0 ? (
          <div className="px-3 py-6 text-xs text-gray-500 text-center">Loading contracts…</div>
        ) : rows.length === 0 ? (
          <div className="px-3 py-6 text-xs text-gray-500 text-center">No contracts found</div>
        ) : (
          rows.map((row) => (
            <FuturesExpiryRow
              key={row.contractSymbol}
              row={row}
              isSelected={selectedContract === row.contractSymbol}
              onSelect={onSelectContract}
            />
          ))
        )}
      </div>
    </div>
  );
}

export default memo(FuturesExpiryLadder);
