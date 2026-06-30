import { memo, useMemo } from 'react';
import { formatZebuPrice, formatZebuOi } from './formatZebuValue';
import OptionsAnalyticsCard from './OptionsAnalyticsCard';

function OptionsAnalyticsPanel({ underlying, analytics, loading, expiry, daysToExpiry, source }) {
  const pcrLabel = useMemo(() => {
    if (analytics?.pcr == null) return '—';
    return analytics.pcr.toFixed(2);
  }, [analytics?.pcr]);

  const showAtmIv = analytics?.atmIv != null && analytics.atmIv > 0;

  return (
    <div className="flex-shrink-0 border-b border-edge/5 bg-surface-900/80 min-h-0">
      <div className="px-3 py-2 border-b border-edge/[0.03]">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-xs font-semibold text-heading truncate">Chain Analytics</div>
            <div className="text-[10px] options-chain-muted uppercase tracking-wider truncate">
              {underlying || '—'}
              {expiry ? ` · ${expiry}` : ''}
            </div>
          </div>
          <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border text-primary-600 bg-primary-600/10 border-primary-500/20">
            Zebu
          </span>
        </div>
      </div>

      <div className="px-3 py-2 space-y-0.5 max-h-[280px] overflow-y-auto overscroll-contain">
        {loading && (
          <div className="text-[10px] options-chain-muted py-1 text-center">Loading snapshot…</div>
        )}
        <OptionsAnalyticsCard
          label="Spot"
          value={
            analytics?.spotPrice != null
              ? `₹${formatZebuPrice(analytics.spotPrice, { source, allowZero: true })}`
              : '—'
          }
        />
        <OptionsAnalyticsCard label="PCR" value={pcrLabel} />
        <OptionsAnalyticsCard label="Max Pain" value={analytics?.maxPain ?? '—'} />
        <OptionsAnalyticsCard label="ATM" value={analytics?.atmStrike ?? '—'} />
        {showAtmIv && (
          <OptionsAnalyticsCard
            label="IV (ATM)"
            value={`${formatZebuPrice(analytics.atmIv, { source })}%`}
          />
        )}
        <OptionsAnalyticsCard label="Total CE OI" value={formatZebuOi(analytics?.totalCeOi, { source })} />
        <OptionsAnalyticsCard label="Total PE OI" value={formatZebuOi(analytics?.totalPeOi, { source })} />
        <OptionsAnalyticsCard
          label="Expiry"
          value={daysToExpiry != null ? `${daysToExpiry}d` : expiry || '—'}
        />
        <div className="flex items-center justify-between gap-2 py-1 min-h-[26px]">
          <span className="text-[10px] options-chain-label uppercase tracking-wide">Regime</span>
          <span className="text-[9px] font-semibold px-2 py-0.5 rounded border options-chain-chip border-edge/20 bg-surface-800/60">
            {analytics?.dominance || '—'}
          </span>
        </div>
      </div>
    </div>
  );
}

export default memo(OptionsAnalyticsPanel);
