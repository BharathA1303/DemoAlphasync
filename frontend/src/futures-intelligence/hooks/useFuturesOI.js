import { useFuturesAnalytics } from './useFuturesAnalytics';

export function useFuturesOI() {
  const { analytics } = useFuturesAnalytics();
  return {
    totalOI: analytics.totalOI,
    expiryRows: analytics.expiryRows,
  };
}

export default useFuturesOI;
