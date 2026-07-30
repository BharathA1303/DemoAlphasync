const TRUE_VALUES = new Set(['1', 'true', 'yes', 'on']);

function readFlag(name, fallback = false) {
  const raw = String(import.meta.env[name] ?? '').trim().toLowerCase();
  if (!raw) return fallback;
  return TRUE_VALUES.has(raw);
}

export const PROGRESSIVE_FLAGS = {
  options: readFlag('VITE_ENABLE_PROGRESSIVE_OPTIONS', false),
  futures: readFlag('VITE_ENABLE_PROGRESSIVE_FUTURES', false),
  commodities: readFlag('VITE_ENABLE_PROGRESSIVE_COMMODITIES', false),
  debug: readFlag('VITE_PROGRESSIVE_DEBUG', false),
};

export function isProgressiveEnabled(key) {
  return Boolean(PROGRESSIVE_FLAGS[key]);
}

export function isProgressiveDebug() {
  return Boolean(PROGRESSIVE_FLAGS.debug);
}

if (PROGRESSIVE_FLAGS.debug && typeof window !== 'undefined') {
  window.__PROGRESSIVE_FLAGS = { ...PROGRESSIVE_FLAGS };
  console.info('[progressive] flags', window.__PROGRESSIVE_FLAGS);
}
