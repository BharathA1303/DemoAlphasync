import { memo } from 'react';
import { cn } from '../../utils/cn';
import FuturesAnalyticsCard from './FuturesAnalyticsCard';
import FuturesBasisBadge from './FuturesBasisBadge';
import FuturesOIBadge from './FuturesOIBadge';
import FuturesVolumeBadge from './FuturesVolumeBadge';
import { formatPriceINR, trendColorClass } from '../utils/futuresFormatting';

function FuturesAnalyticsPanel({ analytics, loading }) {
  const underlying = analytics?.underlying;

  if (!underlying) {
    return (
      <div className="flex-shrink-0 border-b border-edge/5 bg-surface-900/80 px-3 py-3">
        <div className="text-[10px] text-gray-500 text-center">Select underlying for analytics</div>
      </div>
    );
  }

  const session = analytics.session || '—';
  const isLive = session === 'LIVE';

  return (
    <div className="flex-shrink-0 border-b border-edge/5 bg-surface-900/80 min-h-0">
      <div className="px-3 py-2 border-b border-edge/[0.03]">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-xs font-semibold text-heading truncate">
              {underlying} FUTURES
            </div>
            <div className="text-[9px] text-gray-500 uppercase tracking-wider">Analytics</div>
          </div>
          <span
            className={cn(
              'text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border',
              isLive
                ? 'text-bull bg-bull/10 border-bull/20'
                : 'text-gray-400 bg-gray-500/10 border-gray-500/20',
            )}
          >
            {session}
          </span>
        </div>
      </div>

      <div className="px-3 py-2 space-y-0.5 max-h-[220px] overflow-y-auto overscroll-contain">
        {loading && (
          <div className="text-[10px] text-gray-600 py-2 text-center">Updating…</div>
        )}
        <FuturesAnalyticsCard
          label="Spot Price"
          value={analytics.spot ? formatPriceINR(analytics.spot.ltp) : '—'}
        />
        <FuturesAnalyticsCard
          label="ATM Future"
          value={analytics.atmFuture ? formatPriceINR(analytics.atmFuture.ltp) : '—'}
        />
        <div className="flex items-center justify-between gap-2 py-1 min-h-[28px]">
          <span className="text-[10px] text-gray-500 uppercase tracking-wide">Premium</span>
          <FuturesBasisBadge value={analytics.premium} />
        </div>
        <div className="flex items-center justify-between gap-2 py-1 min-h-[28px]">
          <span className="text-[10px] text-gray-500 uppercase tracking-wide">Basis</span>
          <FuturesBasisBadge value={analytics.basis} />
        </div>
        <div className="flex items-center justify-between gap-2 py-1 min-h-[28px]">
          <span className="text-[10px] text-gray-500 uppercase tracking-wide">Total OI</span>
          <FuturesOIBadge value={analytics.totalOI} />
        </div>
        <div className="flex items-center justify-between gap-2 py-1 min-h-[28px]">
          <span className="text-[10px] text-gray-500 uppercase tracking-wide">Total Volume</span>
          <FuturesVolumeBadge value={analytics.totalVolume} />
        </div>
        <div className="flex items-center justify-between gap-2 py-1.5 min-h-[32px]">
          <span className="text-[10px] text-gray-500 uppercase tracking-wide">Trend</span>
          <span
            className={cn(
              'text-[9px] font-semibold px-2 py-0.5 rounded border',
              trendColorClass(analytics.trend),
            )}
          >
            {analytics.trend || 'Neutral'}
          </span>
        </div>
      </div>
    </div>
  );
}

export default memo(FuturesAnalyticsPanel);
