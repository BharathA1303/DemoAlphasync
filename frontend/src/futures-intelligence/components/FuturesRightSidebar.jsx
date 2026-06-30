import { memo } from 'react';
import { useFuturesAnalytics } from '../hooks/useFuturesAnalytics';
import FuturesAnalyticsPanel from './FuturesAnalyticsPanel';
import FuturesExpiryLadder from './FuturesExpiryLadder';

/**
 * Two-panel right sidebar: Intelligence (top) + Expiry Ladder (bottom).
 * Isolated from chart — analytics hook reads store only.
 */
function FuturesRightSidebar({ onSelectContract }) {
  const { analytics, spotLoading, contractsLoading } = useFuturesAnalytics();

  return (
    <div className="flex flex-col h-full min-h-0 w-full futures-intelligence-sidebar">
      <FuturesAnalyticsPanel analytics={analytics} loading={spotLoading} />
      <FuturesExpiryLadder
        analytics={analytics}
        contractsLoading={contractsLoading}
        onSelectContract={onSelectContract}
      />
    </div>
  );
}

export default memo(FuturesRightSidebar);
