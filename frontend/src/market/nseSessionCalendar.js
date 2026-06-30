/**
 * Client-side NSE session truth (IST) — mirrors backend market_session.py calendar.
 * Used to correct stale/wrong API session responses (e.g. holiday shown as open).
 */

const IST = 'Asia/Kolkata';

/** NSE trading holidays 2026 (YYYY-MM-DD, Asia/Kolkata). Keep in sync with backend. */
export const NSE_HOLIDAYS_IST = new Set([
  '2026-01-26',
  '2026-03-10',
  '2026-03-17',
  '2026-03-30',
  '2026-04-03',
  '2026-04-14',
  '2026-05-01',
  '2026-05-27',
  '2026-05-28',
  '2026-06-06',
  '2026-07-06',
  '2026-08-15',
  '2026-08-25',
  '2026-10-02',
  '2026-10-20',
  '2026-11-09',
  '2026-11-10',
  '2026-11-30',
  '2026-12-25',
]);

const STATE_LABELS = {
  open: 'Market Open',
  pre_market: 'Pre-Market',
  closing: 'Closing',
  after_market: 'After Market',
  closed: 'Market Closed',
  weekend: 'Weekend',
  holiday: 'Holiday',
};

function getIstParts(date = new Date()) {
  const fmt = new Intl.DateTimeFormat('en-GB', {
    timeZone: IST,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
  const parts = fmt.formatToParts(date);
  const pick = (type) => parts.find((p) => p.type === type)?.value || '';
  const hour = Number(pick('hour'));
  const minute = Number(pick('minute'));
  const second = Number(pick('second'));
  return {
    date: `${pick('year')}-${pick('month')}-${pick('day')}`,
    weekday: pick('weekday'),
    time: `${pick('hour')}:${pick('minute')}:${pick('second')}`,
    minutes: hour * 60 + minute,
  };
}

/**
 * Authoritative NSE session for display + frozen price mode (IST).
 */
export function computeLocalNseSession(now = new Date()) {
  const ist = getIstParts(now);

  if (ist.weekday === 'Sat' || ist.weekday === 'Sun') {
    return {
      state: 'weekend',
      label: STATE_LABELS.weekend,
      isOpen: false,
      isClosed: true,
      frozen: true,
      ist_date: ist.date,
      ist_time: ist.time,
    };
  }

  if (NSE_HOLIDAYS_IST.has(ist.date)) {
    return {
      state: 'holiday',
      label: STATE_LABELS.holiday,
      isOpen: false,
      isClosed: true,
      frozen: true,
      ist_date: ist.date,
      ist_time: ist.time,
    };
  }

  const m = ist.minutes;
  if (m >= 9 * 60 + 0 && m < 9 * 60 + 15) {
    return {
      state: 'pre_market',
      label: STATE_LABELS.pre_market,
      isOpen: false,
      isClosed: true,
      frozen: true,
      ist_date: ist.date,
      ist_time: ist.time,
    };
  }
  if (m >= 9 * 60 + 15 && m < 15 * 60 + 30) {
    return {
      state: 'open',
      label: STATE_LABELS.open,
      isOpen: true,
      isClosed: false,
      frozen: false,
      ist_date: ist.date,
      ist_time: ist.time,
    };
  }
  if (m >= 15 * 60 + 30 && m < 15 * 60 + 40) {
    return {
      state: 'closing',
      label: STATE_LABELS.closing,
      isOpen: false,
      isClosed: true,
      frozen: true,
      ist_date: ist.date,
      ist_time: ist.time,
    };
  }
  if (m >= 15 * 60 + 40 && m < 16 * 60 + 0) {
    return {
      state: 'after_market',
      label: STATE_LABELS.after_market,
      isOpen: false,
      isClosed: true,
      frozen: true,
      ist_date: ist.date,
      ist_time: ist.time,
    };
  }

  return {
    state: 'closed',
    label: STATE_LABELS.closed,
    isOpen: false,
    isClosed: true,
    frozen: true,
    ist_date: ist.date,
    ist_time: ist.time,
  };
}

/** Merge API payload with IST calendar truth (local wins for open/closed). */
export function mergeSessionWithLocalTruth(apiSession = {}) {
  const local = computeLocalNseSession();
  const apiState = String(apiSession.state || '').toLowerCase();

  return {
    ...apiSession,
    state: local.state,
    label: local.label,
    isOpen: local.isOpen,
    isClosed: local.isClosed,
    is_trading_hours: local.isOpen,
    is_trading: local.isOpen,
    can_place_orders: local.isOpen && apiState === 'open' && !!apiSession.can_place_orders,
    can_run_algo: local.isOpen,
    frozen: local.frozen,
    ist_date: local.ist_date,
    ist_time: local.ist_time,
    session_corrected: apiState === 'open' && !local.isOpen,
  };
}
