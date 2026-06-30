import { quoteOi, quoteOiChange } from '../utils/futuresCalculations';

export function aggregateOI(quotesBySymbol = {}, symbols = []) {
  let total = 0;
  let hasAny = false;
  for (const sym of symbols) {
    const oi = quoteOi(quotesBySymbol[sym]);
    if (oi != null) {
      total += oi;
      hasAny = true;
    }
  }
  return hasAny ? total : null;
}

export function getContractOI(quote) {
  return quoteOi(quote);
}

export function getContractOIChange(quote) {
  return quoteOiChange(quote);
}
