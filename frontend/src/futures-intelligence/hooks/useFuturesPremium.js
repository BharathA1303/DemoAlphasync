import { useFuturesAnalytics } from './useFuturesAnalytics';

export function useFuturesPremium() {
  const { analytics } = useFuturesAnalytics();
  return {
    premium: analytics.premium,
    basis: analytics.basis,
    spot: analytics.spot,
    atmFuture: analytics.atmFuture,
  };
}

export default useFuturesPremium;
