import { setSnapshot } from './snapshotStore';
import { getStaleMs, isSnapshotStale } from './staleGuard';
import { scheduleReconcile, cancelReconcile } from './reconcileEngine';

export function normalizeSnapshotPayload(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const data = payload.data && typeof payload.data === 'object' ? payload.data : payload;
  return {
    snapshot: Boolean(payload.snapshot),
    snapshot_ts: payload.snapshot_ts ?? null,
    stale_ms: payload.stale_ms ?? null,
    stream_symbols: Array.isArray(payload.stream_symbols) ? payload.stream_symbols : [],
    data,
  };
}

export async function hydrateSnapshot({
  key,
  enabled = true,
  snapshotFetcher,
  reconcileFetcher,
  subscribe,
  onSnapshot,
  onReconcile,
  onError,
  staleThresholdMs = 5000,
  reconcileDelayMs = 0,
}) {
  if (!enabled || typeof snapshotFetcher !== 'function') return null;

  try {
    const raw = await snapshotFetcher();
    const payload = normalizeSnapshotPayload(raw);
    if (!payload) return null;

    setSnapshot(key, payload);
    onSnapshot?.(payload);

    if (typeof subscribe === 'function' && payload.stream_symbols?.length) {
      subscribe(payload.stream_symbols);
    }

    const staleMs = getStaleMs(payload.snapshot_ts);
    const shouldForceReconcile = isSnapshotStale(payload.snapshot_ts, staleThresholdMs);

    if (typeof reconcileFetcher === 'function') {
      scheduleReconcile(
        key,
        reconcileFetcher,
        (result) => onReconcile?.(normalizeSnapshotPayload(result)),
        onError,
        shouldForceReconcile ? 0 : reconcileDelayMs,
      );
    }

    return { ...payload, stale_ms: payload.stale_ms ?? staleMs };
  } catch (err) {
    onError?.(err);
    return null;
  }
}

export function cancelHydration(key) {
  if (!key) return;
  cancelReconcile(key);
}
