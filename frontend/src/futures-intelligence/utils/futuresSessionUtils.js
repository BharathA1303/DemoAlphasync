import { getMarketSessionSnapshot, shouldUseRealtimePrices } from '../../market/utils/marketSessionUtils';

export function getFuturesSessionLabel() {
  const snap = getMarketSessionSnapshot();
  if (snap.isOpen) return 'LIVE';
  if (snap.state === 'preopen' || snap.state === 'pre_open') return 'PRE-OPEN';
  return 'CLOSED';
}

export function isFuturesLiveSession() {
  return shouldUseRealtimePrices();
}

export { getMarketSessionSnapshot, shouldUseRealtimePrices };
