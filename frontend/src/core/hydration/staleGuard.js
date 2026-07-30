export function toEpochMs(value) {
  if (value == null) return null;
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 1e12 ? Math.floor(value) : Math.floor(value * 1000);
  }
  if (typeof value === 'string') {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function getStaleMs(snapshotTs, nowMs = Date.now()) {
  const ts = toEpochMs(snapshotTs);
  if (!ts) return null;
  return Math.max(0, nowMs - ts);
}

export function isSnapshotStale(snapshotTs, thresholdMs) {
  if (!Number.isFinite(thresholdMs) || thresholdMs <= 0) return false;
  const stale = getStaleMs(snapshotTs);
  if (stale == null) return false;
  return stale > thresholdMs;
}
