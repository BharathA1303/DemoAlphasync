/**
 * Display helpers — never show fake zeros when TickAlpha has no quote.
 */

export function isLiveChainSource(source) {
  if (!source) return true;
  const s = String(source || '').toLowerCase();
  if (s.includes('unavailable') || s.includes('error') || s.includes('disabled')) return false;
  return true;
}


/** Price-like field: show — if missing, not live, or zero without valid quote */
export function formatOptionPrice(value, { source, allowZero = false, bid, ask, noFallback = false } = {}) {
  if (!isLiveChainSource(source)) return '—';
  let n = Number(value);
  if ((!Number.isFinite(n) || n <= 0) && !allowZero && !noFallback) {
    const b = Number(bid);
    const a = Number(ask);
    if (Number.isFinite(b) && b > 0 && Number.isFinite(a) && a > 0) {
      n = (b + a) / 2;
    } else if (Number.isFinite(b) && b > 0) {
      n = b;
    } else if (Number.isFinite(a) && a > 0) {
      n = a;
    } else {
      return '—';
    }
  }
  if (!Number.isFinite(n)) return '—';
  if (!allowZero && n === 0) return '—';
  return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function formatOptionOi(value, { source } = {}) {
  if (!isLiveChainSource(source)) return '—';
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return '—';
  if (n >= 1e7) return `${(n / 1e7).toFixed(2)}Cr`;
  if (n >= 1e5) return `${(n / 1e5).toFixed(2)}L`;
  return n.toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 0 });
}

export function formatOptionPct(value, { source } = {}) {
  if (!isLiveChainSource(source)) return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
}

/** Exchange-style change in parentheses: (12.34%) */
export function formatOptionPctParen(value, { source } = {}) {
  if (!isLiveChainSource(source)) return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `(${n.toFixed(2)}%)`;
}

export function oiChangePercent(oi, oiChange) {
  if (oiChange == null || oiChange === '') return null;
  const total = Number(oi);
  const chg = Number(oiChange);
  if (!Number.isFinite(total) || !Number.isFinite(chg)) return null;
  const prev = total - chg;
  if (!prev || prev <= 0) return null;
  return (chg / prev) * 100;
}
