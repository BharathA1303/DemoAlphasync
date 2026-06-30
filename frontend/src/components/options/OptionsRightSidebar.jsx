import { memo } from 'react';
import OptionsAnalyticsPanel from './OptionsAnalyticsPanel';
import OptionsIntelligenceStrip from './OptionsIntelligenceStrip';
import OptionsStrikeDetailsPanel from './OptionsStrikeDetailsPanel';

/** Right column: chain analytics + selected strike details (no order panel). */
function OptionsRightSidebar({
  underlying,
  analytics,
  loading,
  source,
  expiry,
  daysToExpiry,
  strike,
  optionType,
  sideData,
  oppositeSideData,
  displaySymbol,
}) {
  return (
    <div className="flex flex-col h-full min-h-0 w-full options-terminal-sidebar">
      <OptionsAnalyticsPanel
        underlying={underlying}
        analytics={analytics}
        loading={loading}
        expiry={expiry}
        daysToExpiry={daysToExpiry}
        source={source}
      />
      <OptionsIntelligenceStrip analytics={analytics} />
      <div className="flex-1 min-h-0 border-t border-edge/5 overflow-hidden">
        <OptionsStrikeDetailsPanel
          underlying={underlying}
          expiry={expiry}
          strike={strike}
          optionType={optionType}
          sideData={sideData}
          oppositeSideData={oppositeSideData}
          source={source}
          displaySymbol={displaySymbol}
        />
      </div>
    </div>
  );
}

export default memo(OptionsRightSidebar);
