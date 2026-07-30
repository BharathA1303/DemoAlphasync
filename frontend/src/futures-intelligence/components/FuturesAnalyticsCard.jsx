import { cn } from '../../utils/cn';

export default function FuturesAnalyticsCard({ label, value, valueClassName, subValue }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1 min-h-[28px]">
      <span className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</span>
      <div className="text-right min-w-0">
        <span className={cn('text-[11px] font-mono font-semibold tabular-nums text-heading', valueClassName)}>
          {value ?? '—'}
        </span>
        {subValue != null && (
          <div className="text-[9px] text-gray-600 font-mono tabular-nums">{subValue}</div>
        )}
      </div>
    </div>
  );
}
