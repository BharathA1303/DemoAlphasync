import { formatSignedPremium, premiumColorClass } from '../utils/futuresFormatting';
import { cn } from '../../utils/cn';

export default function FuturesBasisBadge({ value, className }) {
  if (value == null) return <span className="text-gray-500">—</span>;
  return (
    <span className={cn('font-mono tabular-nums text-[11px] font-semibold', premiumColorClass(value), className)}>
      {formatSignedPremium(value)}
    </span>
  );
}
