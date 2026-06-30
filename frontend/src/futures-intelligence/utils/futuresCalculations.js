/**
 * Pure calculations from real Zebu quote fields only.
 */

export function quoteLtp(quote) {
  const n = Number(quote?.ltp ?? quote?.price ?? quote?.lp);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export function quoteChange(quote) {
  const v = Number(quote?.change ?? quote?.net_change);
  if (Number.isFinite(v)) return v;
  const ltp = quoteLtp(quote);
  const close = Number(quote?.close ?? quote?.prev_close ?? quote?.c);
  if (ltp != null && Number.isFinite(close) && close > 0) return +(ltp - close).toFixed(2);
  return null;
}

export function quoteChangePct(quote) {
  const v = Number(quote?.change_pct ?? quote?.change_percent ?? quote?.pc);
  if (Number.isFinite(v)) return v;
  const ch = quoteChange(quote);
  const close = Number(quote?.close ?? quote?.prev_close ?? quote?.c);
  if (ch != null && Number.isFinite(close) && close > 0) return +((ch / close) * 100).toFixed(2);
  return null;
}

export function quoteOi(quote) {
  const n = Number(quote?.oi);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

export function quoteVolume(quote) {
  const n = Number(quote?.volume ?? quote?.v);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

export function quoteOiChange(quote) {
  const n = Number(quote?.oi_change);
  return Number.isFinite(n) ? n : null;
}

/** Premium / basis: Future LTP - Spot LTP (only when both are real). */
export function calcPremium(futureLtp, spotLtp) {
  if (futureLtp == null || spotLtp == null) return null;
  return Number((futureLtp - spotLtp).toFixed(2));
}

export function sortContractsByExpiry(contracts = []) {
  return [...contracts].sort((a, b) => {
    const da = new Date(a.expiry_date || 0).getTime();
    const db = new Date(b.expiry_date || 0).getTime();
    return da - db;
  });
}
