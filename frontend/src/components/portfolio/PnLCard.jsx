import {
  formatCurrency,
  formatPercent,
  pnlColorClass,
} from "../../utils/formatters";
import { cn } from "../../utils/cn";

/**
 * Single P&L display card used in the portfolio summary row.
 *
 * @param {{
 *   label: string,
 *   value: number,
 *   percent?: number,
 *   compact?: boolean,
 * }} props
 */
export default function PnLCard({ label, value, percent, compact = false }) {
  const isPositive = (value ?? 0) >= 0;

  return (
    <div className="kpi-card">
      <span className="metric-label">{label}</span>
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "font-semibold font-price tabular-nums",
            compact ? "text-lg" : "text-xl",
            pnlColorClass(value ?? 0),
          )}
        >
          {value != null
            ? `${isPositive ? "+" : ""}${formatCurrency(value)}`
            : "—"}
        </span>
        <span className={cn("text-sm leading-none", pnlColorClass(value ?? 0))}>
          {isPositive ? "▲" : "▼"}
        </span>
      </div>
      {percent != null && (
        <span
          className={cn(
            "text-xs font-price tabular-nums",
            pnlColorClass(percent),
          )}
        >
          {formatPercent(percent, 2)}
        </span>
      )}
    </div>
  );
}
