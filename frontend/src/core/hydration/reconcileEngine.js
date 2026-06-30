const _reconcileTimers = new Map();
const _reconcileInflight = new Map();

export function scheduleReconcile(key, fetcher, onResult, onError, delayMs = 0) {
  if (!key || typeof fetcher !== 'function') return;
  const cacheKey = String(key);
  cancelReconcile(cacheKey);

  const timer = setTimeout(async () => {
    if (_reconcileInflight.get(cacheKey)) return;
    _reconcileInflight.set(cacheKey, true);
    try {
      const result = await fetcher();
      onResult?.(result);
    } catch (err) {
      onError?.(err);
    } finally {
      _reconcileInflight.delete(cacheKey);
    }
  }, Math.max(0, Number(delayMs) || 0));

  _reconcileTimers.set(cacheKey, timer);
}

export function cancelReconcile(key) {
  const cacheKey = String(key);
  const timer = _reconcileTimers.get(cacheKey);
  if (timer) clearTimeout(timer);
  _reconcileTimers.delete(cacheKey);
}

export function cancelAllReconciles() {
  for (const timer of _reconcileTimers.values()) {
    clearTimeout(timer);
  }
  _reconcileTimers.clear();
}
