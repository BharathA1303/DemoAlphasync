import { quoteVolume } from '../utils/futuresCalculations';

export function aggregateVolume(quotesBySymbol = {}, symbols = []) {
  let total = 0;
  let hasAny = false;
  for (const sym of symbols) {
    const vol = quoteVolume(quotesBySymbol[sym]);
    if (vol != null) {
      total += vol;
      hasAny = true;
    }
  }
  return hasAny ? total : null;
}

export function getContractVolume(quote) {
  return quoteVolume(quote);
}
