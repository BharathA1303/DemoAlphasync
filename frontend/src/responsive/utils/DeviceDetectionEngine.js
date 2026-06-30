/**
 * Device capability detection — touch, hover, foldable, orientation.
 */

export function detectTouchDevice() {
  if (typeof window === 'undefined') return false;
  return (
    'ontouchstart' in window ||
    navigator.maxTouchPoints > 0 ||
    window.matchMedia('(pointer: coarse)').matches
  );
}

export function detectHoverCapability() {
  if (typeof window === 'undefined') return true;
  return window.matchMedia('(hover: hover) and (pointer: fine)').matches;
}

export function detectLandscape() {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(orientation: landscape)').matches;
}

export function detectFoldable() {
  if (typeof window === 'undefined') return false;
  const span = window.matchMedia('(spanning: single-fold-vertical), (spanning: single-fold-horizontal)');
  if (span.matches) return true;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const ratio = Math.max(vw, vh) / Math.min(vw, vh);
  return ratio > 2.1 && vw >= 600 && vw <= 900;
}

export function detectReducedMotion() {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function getDevicePixelRatio() {
  if (typeof window === 'undefined') return 1;
  return window.devicePixelRatio || 1;
}

export function snapshotDeviceCapabilities() {
  return {
    touch: detectTouchDevice(),
    hover: detectHoverCapability(),
    landscape: detectLandscape(),
    foldable: detectFoldable(),
    reducedMotion: detectReducedMotion(),
    dpr: getDevicePixelRatio(),
    standalone: typeof window !== 'undefined' && window.matchMedia('(display-mode: standalone)').matches,
  };
}
