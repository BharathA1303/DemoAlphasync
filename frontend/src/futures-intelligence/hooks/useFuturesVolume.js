import { useFuturesAnalytics } from './useFuturesAnalytics';

export function useFuturesVolume() {
  const { analytics } = useFuturesAnalytics();
  return {
    totalVolume: analytics.totalVolume,
    expiryRows: analytics.expiryRows,
  };
}

export default useFuturesVolume;
