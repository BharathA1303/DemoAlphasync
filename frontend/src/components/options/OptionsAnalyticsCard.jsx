import { memo } from 'react';
import { cn } from '../../utils/cn';

function OptionsAnalyticsCard({ label, value, valueClassName }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1 min-h-[26px]">
      <span className="text-[10px] text-gray-500 dark:text-gray-400 uppercase tracking-wide">{label}</span>
      <span className={cn('text-[11px] font-mono font-semibold text-heading tabular-nums text-right', valueClassName)}>
        {value ?? '—'}
      </span>
    </div>
  );
}

export default memo(OptionsAnalyticsCard);
