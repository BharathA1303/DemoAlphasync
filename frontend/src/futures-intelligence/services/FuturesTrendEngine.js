import { quoteChange, quoteOiChange } from '../utils/futuresCalculations';

/**
 * Institutional OI–price trend from REAL Zebu change + oi_change only.
 * Returns Neutral when data insufficient.
 */
export function classifyTrendFromQuote(quote) {
  const priceChange = quoteChange(quote);
  const oiChange = quoteOiChange(quote);

  if (priceChange == null || oiChange == null) return 'Neutral';

  const priceUp = priceChange > 0;
  const priceDown = priceChange < 0;
  const oiUp = oiChange > 0;
  const oiDown = oiChange < 0;

  if (priceUp && oiUp) return 'Long Build-up';
  if (priceDown && oiUp) return 'Short Build-up';
  if (priceUp && oiDown) return 'Short Covering';
  if (priceDown && oiDown) return 'Long Unwinding';
  return 'Neutral';
}
