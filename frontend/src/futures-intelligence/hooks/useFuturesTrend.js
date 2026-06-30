import { useFuturesAnalytics } from './useFuturesAnalytics';

export function useFuturesTrend() {
  const { analytics } = useFuturesAnalytics();
  return { trend: analytics.trend };
}

export default useFuturesTrend;
