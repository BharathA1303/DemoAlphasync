import { formatCompactNumber } from '../utils/futuresFormatting';

export default function FuturesOIBadge({ value }) {
  return (
    <span className="font-mono tabular-nums text-[11px] text-heading">
      {formatCompactNumber(value)}
    </span>
  );
}
