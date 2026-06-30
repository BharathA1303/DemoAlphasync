/**
 * Display helpers — never show fake zeros when Zebu has no quote.
 */

export function isZebuChainSource(source) {
  const s = String(source || '').toLowerCase();
  return s.includes('zebu');
}

/** Price-like field: show — if missing, non-Zebu, or zero without valid quote */
export function formatZebuPrice(value, { source, allowZero = false, bid, ask, noFallback = false } = {}) {
  if (!isZebuChainSource(source)) return '—';
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

export function formatZebuOi(value, { source } = {}) {
  if (!isZebuChainSource(source)) return '—';
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return '—';
  if (n >= 1e7) return `${(n / 1e7).toFixed(2)}Cr`;
  if (n >= 1e5) return `${(n / 1e5).toFixed(2)}L`;
  return n.toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 0 });
}

export function formatZebuPct(value, { source } = {}) {
  if (!isZebuChainSource(source)) return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
}

/** Broker-style change in parentheses: (12.34%) */
export function formatZebuPctParen(value, { source } = {}) {
  if (!isZebuChainSource(source)) return '—';
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
