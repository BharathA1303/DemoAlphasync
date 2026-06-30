/**
 * Options analytics derived from live chain rows (Zebu fields + standard formulas).
 */

export function findAtmStrike(chain, spotPrice) {
  if (!chain?.length || !Number.isFinite(spotPrice)) return null;
  return chain.reduce((closest, row) => {
    if (!closest) return row.strike;
    return Math.abs(row.strike - spotPrice) < Math.abs(closest - spotPrice)
      ? row.strike
      : closest;
  }, null);
}

export function computeMaxPain(chain) {
  if (!chain?.length) return null;
  const strikes = chain.map((r) => r.strike).sort((a, b) => a - b);
  let minPain = Infinity;
  let maxPainStrike = null;

  for (const settlement of strikes) {
    let pain = 0;
    for (const row of chain) {
      const k = row.strike;
      const ceOi = Number(row.ce?.oi) || 0;
      const peOi = Number(row.pe?.oi) || 0;
      if (settlement > k) pain += ceOi * (settlement - k);
      if (settlement < k) pain += peOi * (k - settlement);
    }
    if (pain < minPain) {
      minPain = pain;
      maxPainStrike = settlement;
    }
  }
  return maxPainStrike;
}

function sumOiChange(chain, side) {
  let total = 0;
  let has = false;
  for (const row of chain) {
    const leg = side === 'CE' ? row.ce : row.pe;
    const ch = Number(leg?.oiChange);
    if (Number.isFinite(ch)) {
      total += ch;
      has = true;
    }
  }
  return has ? total : null;
}

function classifyBuildup(ceChg, peChg) {
  if (ceChg == null && peChg == null) return '—';
  const ce = ceChg ?? 0;
  const pe = peChg ?? 0;
  if (ce > 0 && pe <= 0) return 'Call buildup';
  if (pe > 0 && ce <= 0) return 'Put buildup';
  if (ce > 0 && pe > 0) return 'Long buildup';
  if (ce < 0 && pe < 0) return 'Short buildup / unwinding';
  if (ce < 0 && pe >= 0) return 'CE unwinding';
  if (pe < 0 && ce >= 0) return 'PE unwinding';
  return 'Mixed';
}

export function computeOptionsAnalytics(chain, spotPrice, daysToExpiry = null) {
  if (!chain?.length) {
    return null;
  }

  let totalCeOi = 0;
  let totalPeOi = 0;
  let totalCeVol = 0;
  let totalPeVol = 0;
  let maxCeOi = 0;
  let maxPeOi = 0;
  let maxCeOiStrike = null;
  let maxPeOiStrike = null;
  let atmIv = null;
  let netDelta = null;
  let gammaExposure = null;
  let ivSamples = [];

  const atmStrike = findAtmStrike(chain, spotPrice);
  const atmRow = chain.find((r) => r.strike === atmStrike);

  for (const row of chain) {
    const ceOi = Number(row.ce?.oi) || 0;
    const peOi = Number(row.pe?.oi) || 0;
    totalCeOi += ceOi;
    totalPeOi += peOi;
    totalCeVol += Number(row.ce?.volume) || 0;
    totalPeVol += Number(row.pe?.volume) || 0;
    if (ceOi > maxCeOi) {
      maxCeOi = ceOi;
      maxCeOiStrike = row.strike;
    }
    if (peOi > maxPeOi) {
      maxPeOi = peOi;
      maxPeOiStrike = row.strike;
    }

    for (const leg of [row.ce, row.pe]) {
      const iv = Number(leg?.iv);
      if (iv > 0) ivSamples.push(iv);
      const delta = Number(leg?.delta);
      const oi = Number(leg?.oi) || 0;
      const gamma = Number(leg?.gamma);
      if (Number.isFinite(delta) && oi > 0) {
        netDelta = (netDelta ?? 0) + delta * oi;
      }
      if (Number.isFinite(gamma) && oi > 0) {
        gammaExposure = (gammaExposure ?? 0) + gamma * oi;
      }
    }
  }

  if (atmRow) {
    const ceIv = Number(atmRow.ce?.iv);
    const peIv = Number(atmRow.pe?.iv);
    if (ceIv > 0 && peIv > 0) atmIv = (ceIv + peIv) / 2;
    else if (ceIv > 0) atmIv = ceIv;
    else if (peIv > 0) atmIv = peIv;
  }

  const pcr = totalCeOi > 0 ? totalPeOi / totalCeOi : null;
  const maxPain = computeMaxPain(chain);

  const ceOiChangeTotal = sumOiChange(chain, 'CE');
  const peOiChangeTotal = sumOiChange(chain, 'PE');

  let buildupLabel = '—';
  if (atmRow) {
    const ceOiChange = Number(atmRow.ce?.oiChange) || 0;
    const peOiChange = Number(atmRow.pe?.oiChange) || 0;
    if (ceOiChange > 0 && peOiChange <= 0) buildupLabel = 'CE buildup';
    else if (peOiChange > 0 && ceOiChange <= 0) buildupLabel = 'PE buildup';
    else if (ceOiChange < 0 && peOiChange < 0) buildupLabel = 'OI unwinding';
    else if (ceOiChange > 0 && peOiChange > 0) buildupLabel = 'Long buildup';
  }

  const chainBuildup = classifyBuildup(ceOiChangeTotal, peOiChangeTotal);

  let dominance = 'Balanced';
  if (pcr != null) {
    if (pcr > 1.15) dominance = 'PE dominance';
    else if (pcr < 0.85) dominance = 'CE dominance';
  }

  let expectedMove = null;
  if (
    atmIv != null &&
    atmIv > 0 &&
    Number.isFinite(spotPrice) &&
    spotPrice > 0 &&
    daysToExpiry != null &&
    daysToExpiry > 0
  ) {
    const t = daysToExpiry / 365;
    expectedMove = spotPrice * (atmIv / 100) * Math.sqrt(t);
  }

  return {
    atmStrike,
    spotPrice: Number.isFinite(spotPrice) ? spotPrice : null,
    totalCeOi,
    totalPeOi,
    totalCeVol,
    totalPeVol,
    pcr,
    maxPain,
    atmIv,
    maxCeOiStrike,
    maxPeOiStrike,
    buildupLabel,
    chainBuildup,
    putBuildup: peOiChangeTotal != null && peOiChangeTotal > 0 ? 'Active' : peOiChangeTotal != null ? 'Weak' : null,
    callBuildup: ceOiChangeTotal != null && ceOiChangeTotal > 0 ? 'Active' : ceOiChangeTotal != null ? 'Weak' : null,
    longBuildup: chainBuildup === 'Long buildup' ? chainBuildup : null,
    shortBuildup: chainBuildup.includes('unwinding') ? chainBuildup : null,
    dominance,
    ivRank: null,
    ivPercentile: null,
    ivRankUnavailable: true,
    ivPercentileUnavailable: true,
    netDelta,
    gammaExposure,
    expectedMove,
    trendBias: null,
    trendBiasUnavailable: true,
  };
}

/** Row heat intensity 0–1 for OI / volume columns */
export function computeChainHeatmap(chain) {
  if (!chain?.length) {
    return { maxOi: 1, maxVol: 1 };
  }
  let maxOi = 1;
  let maxVol = 1;
  for (const row of chain) {
    maxOi = Math.max(maxOi, row.ce?.oi || 0, row.pe?.oi || 0);
    maxVol = Math.max(maxVol, row.ce?.volume || 0, row.pe?.volume || 0);
  }
  return { maxOi, maxVol };
}

/** Liquidity from bid-ask vs mid (Zebu quotes). */
export function computeLiquidityLabel(sideData) {
  if (!sideData) return { label: '—', tone: 'muted' };
  const bid = Number(sideData.bid);
  const ask = Number(sideData.ask);
  const ltp = Number(sideData.ltp);
  const mid =
    ltp > 0 ? ltp : bid > 0 && ask > 0 ? (bid + ask) / 2 : null;
  if (!mid || mid <= 0 || !Number.isFinite(bid) || !Number.isFinite(ask) || ask <= bid) {
    return { label: 'Unknown', tone: 'muted' };
  }
  const spreadPct = ((ask - bid) / mid) * 100;
  if (spreadPct <= 0.5) return { label: 'High', tone: 'good' };
  if (spreadPct <= 1.5) return { label: 'Medium', tone: 'ok' };
  return { label: 'Low', tone: 'warn' };
}
