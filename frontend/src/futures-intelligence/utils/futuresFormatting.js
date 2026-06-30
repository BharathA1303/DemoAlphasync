/**
 * Compact formatting for futures analytics — no synthetic values.
 */

export function formatCompactNumber(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(Math.round(n));
}

export function formatPriceINR(value, decimals = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `₹${n.toLocaleString('en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`;
}

export function formatSignedPremium(value, decimals = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  const sign = n > 0 ? '+' : n < 0 ? '' : '';
  return `${sign}${n.toFixed(decimals)}`;
}

export function premiumColorClass(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || Math.abs(n) < 0.005) return 'text-gray-400';
  return n > 0 ? 'text-bull' : 'text-bear';
}

export function trendColorClass(trend) {
  switch (trend) {
    case 'Long Build-up': return 'text-bull bg-bull/10 border-bull/20';
    case 'Short Build-up': return 'text-bear bg-bear/10 border-bear/20';
    case 'Short Covering': return 'text-blue-400 bg-blue-500/10 border-blue-500/20';
    case 'Long Unwinding': return 'text-amber-400 bg-amber-500/10 border-amber-500/20';
    default: return 'text-gray-400 bg-gray-500/10 border-gray-500/20';
  }
}
