const _snapshots = new Map();

export function setSnapshot(key, payload) {
  if (!key) return;
  _snapshots.set(String(key), payload);
}

export function getSnapshot(key) {
  if (!key) return null;
  return _snapshots.get(String(key)) ?? null;
}

export function clearSnapshot(key) {
  if (!key) return;
  _snapshots.delete(String(key));
}

export function clearAllSnapshots() {
  _snapshots.clear();
}
