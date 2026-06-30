import { memo } from 'react';
import { cn } from '../../utils/cn';

function IntelChip({ label, value, tone = 'neutral' }) {
  return (
    <div
      className={cn(
        'flex-shrink-0 rounded-lg border px-2 py-1 min-w-[88px]',
        tone === 'bull' && 'border-emerald-500/25 bg-emerald-500/10',
        tone === 'bear' && 'border-red-500/25 bg-red-500/10',
        tone === 'neutral' && 'border-edge/10 bg-surface-800/50 dark:bg-black/20',
      )}
    >
      <div className="text-[8px] options-chain-label uppercase tracking-wider">{label}</div>
      <div className="text-[10px] font-semibold text-heading truncate tabular-nums">{value ?? '—'}</div>
    </div>
  );
}

function OptionsIntelligenceStrip({ analytics }) {
  if (!analytics) {
    return (
      <div className="px-3 py-1.5 border-b border-edge/5 bg-surface-900/50 text-[10px] options-chain-muted">
        Analytics load with chain snapshot
      </div>
    );
  }

  const pcrTone =
    analytics.pcr > 1.1 ? 'bear' : analytics.pcr < 0.9 ? 'bull' : 'neutral';

  return (
    <div className="flex gap-1.5 px-2 py-1.5 border-b border-edge/5 bg-surface-900/50 overflow-x-auto overscroll-x-contain">
      <IntelChip label="Max Pain" value={analytics.maxPain} />
      <IntelChip label="PCR" value={analytics.pcr != null ? analytics.pcr.toFixed(2) : '—'} tone={pcrTone} />
      {analytics.atmIv != null && analytics.atmIv > 0 && (
        <IntelChip label="ATM IV" value={`${analytics.atmIv.toFixed(1)}%`} />
      )}
      {analytics.chainBuildup && analytics.chainBuildup !== '—' && (
        <IntelChip label="Flow" value={analytics.chainBuildup || analytics.buildupLabel} />
      )}
    </div>
  );
}

export default memo(OptionsIntelligenceStrip);
