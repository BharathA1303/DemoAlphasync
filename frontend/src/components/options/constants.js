export const OPTIONS_UNDERLYINGS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'SENSEX'];

export const OPTIONS_LOT_SIZES = {
  NIFTY: 75,
  BANKNIFTY: 30,
  SENSEX: 10,
  FINNIFTY: 40,
  MIDCPNIFTY: 50,
  NIFTYNXT50: 25,
};

/** Index symbols for chart / live quote (underlying). */
export const UNDERLYING_CHART_SYMBOL = {
  NIFTY: '^NSEI',
  BANKNIFTY: '^NSEBANK',
  FINNIFTY: '^CNXFIN',
  MIDCPNIFTY: '^CNXMIDCAP',
  NIFTYNXT50: '^CNXJUNIOR',
  SENSEX: '^BSESN',
};

export function getLotSize(symbol) {
  return OPTIONS_LOT_SIZES[String(symbol || '').toUpperCase()] ?? 75;
}

export function getChartSymbol(underlying) {
  return UNDERLYING_CHART_SYMBOL[String(underlying || '').toUpperCase()] ?? '^NSEI';
}

export function formatExpiryChip(dateStr) {
  const parsed = new Date(dateStr);
  if (Number.isNaN(parsed.getTime())) return dateStr;
  return parsed.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}

export function resolveChainSourceBadge(source) {
  const src = String(source || '').toLowerCase();
  if (src.includes('zebu_cache')) return { variant: 'warning', label: 'ZEBU CACHE' };
  if (src.includes('zebu')) return { variant: 'success', label: 'ZEBU LIVE' };
  return { variant: 'default', label: 'OFFLINE' };
}

/** NSE API chain row → OptionChain row shape */
/** Preserve WS-fresh LTP when a poll returns zeros from a slow GetQuotes batch. */
export function mergeChainRows(prev, next) {
  if (!Array.isArray(prev) || !prev.length || !Array.isArray(next) || !next.length) {
    return next;
  }
  const byStrike = new Map(prev.map((r) => [r.strike, r]));
  const mergeSide = (incoming, existing) => {
    if (!incoming) return incoming;
    if (!existing) return incoming;
    const inLtp = Number(incoming.ltp);
    const exLtp = Number(existing.ltp);
    if (Number.isFinite(inLtp) && inLtp > 0) return incoming;
    if (Number.isFinite(exLtp) && exLtp > 0) {
      return {
        ...incoming,
        ltp: exLtp,
        bid: incoming.bid || existing.bid,
        ask: incoming.ask || existing.ask,
        oi: incoming.oi || existing.oi,
        change: existing.change ?? incoming.change,
        changePct: existing.changePct ?? incoming.changePct,
      };
    }
    return incoming;
  };
  return next.map((row) => {
    const old = byStrike.get(row.strike);
    if (!old) return row;
    return {
      ...row,
      ce: mergeSide(row.ce, old.ce),
      pe: mergeSide(row.pe, old.pe),
    };
  });
}

export function transformChainRow(row) {
  const empty = {
    ltp: 0,
    bid: 0,
    ask: 0,
    iv: 0,
    delta: 0,
    gamma: 0,
    theta: 0,
    vega: 0,
    oi: 0,
    oiChange: null,
    volume: 0,
  };
  const mapSide = (d) =>
    d
      ? {
          ltp: d.ltp ?? d.lp ?? d.price ?? 0,
          bid: d.bid ?? 0,
          ask: d.ask ?? 0,
          iv: d.iv ?? 0,
          delta: d.delta ?? 0,
          gamma: d.gamma ?? 0,
          theta: d.theta ?? 0,
          vega: d.vega ?? 0,
          oi: d.oi ?? 0,
          oiChange: d.oi_change ?? d.oiChange ?? null,
          volume: d.volume ?? 0,
          change: d.change ?? 0,
          changePct: d.change_pct ?? d.changePct ?? null,
          tsym: d.tsym ?? d.symbol ?? '',
          token: d.token ?? '',
        }
      : { ...empty };

  return {
    strike: row.strike,
    ce: mapSide(row.CE ?? row.ce),
    pe: mapSide(row.PE ?? row.pe),
  };
}

export function buildDisplaySymbol(underlying, strike, optionType, expiry) {
  const exp = expiry
    ? new Date(expiry).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }).replace(/ /g, '')
    : '';
  return `${underlying}${exp ? exp : ''}${strike ?? ''}${optionType || 'CE'}`;
}
