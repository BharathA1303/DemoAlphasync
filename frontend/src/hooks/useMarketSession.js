import { useSyncExternalStore, useCallback } from 'react';
import { marketSessionManager } from '../market/MarketSessionManager';

const STATE_LABELS = {
  weekend: 'Weekend',
  holiday: 'Holiday',
  closed: 'Market Closed',
  after_market: 'After Market Hours',
};

const CLOSED_MESSAGE =
  'Trading is available Mon-Fri 9:15 AM - 3:30 PM IST.';

/**
 * Shared market session state — reads from MarketSessionManager (single poll source).
 */
export function useMarketSession() {
  const snapshot = useSyncExternalStore(
    (cb) => marketSessionManager.subscribe(cb),
    () => marketSessionManager.getSnapshot(),
    () => marketSessionManager.getSnapshot(),
  );

  const marketOpen = snapshot.isOpen;
  const marketState = snapshot.state || '';
  // Live AMDP feed vs local simulation — drives the feed badge. Keyed off the
  // active provider, NOT simulation_mode (which stays on for both, since the
  // AMDP feed is itself a replay stream driven by the virtual clock).
  const liveFeedActive = snapshot.raw?.live_feed_active === true;
  const marketStateLabel = marketOpen
    ? ''
    : (STATE_LABELS[marketState] || 'Market Closed');
  const sessionLabel =
    snapshot.label ||
    (marketOpen ? 'Market Open' : marketStateLabel || 'Market Closed');

  const refresh = useCallback(() => marketSessionManager.refresh(), []);

  const closedDetail = marketStateLabel
    ? `Cannot place futures orders - ${marketStateLabel}. ${CLOSED_MESSAGE}`
    : `Cannot place futures orders - Market Closed. ${CLOSED_MESSAGE}`;

  return {
    marketOpen,
    marketState,
    marketStateLabel,
    sessionLabel,
    closedDetail,
    liveFeedActive,
    refresh,
  };
}
