/**
 * Coordinates viewport dimensions, resize debouncing, and CSS variable injection.
 */

let rafId = null;
const listeners = new Set();

function readViewport() {
  if (typeof window === 'undefined') {
    return { width: 1280, height: 800 };
  }
  return {
    width: window.innerWidth,
    height: window.innerHeight,
    visualWidth: window.visualViewport?.width ?? window.innerWidth,
    visualHeight: window.visualViewport?.height ?? window.innerHeight,
  };
}

function notify() {
  const vp = readViewport();
  listeners.forEach((fn) => fn(vp));
}

function scheduleNotify() {
  if (rafId != null) cancelAnimationFrame(rafId);
  rafId = requestAnimationFrame(() => {
    rafId = null;
    notify();
  });
}

let initialized = false;

export function initViewportCoordinator() {
  if (initialized || typeof window === 'undefined') return;
  initialized = true;

  window.addEventListener('resize', scheduleNotify, { passive: true });
  window.visualViewport?.addEventListener('resize', scheduleNotify, { passive: true });
  window.visualViewport?.addEventListener('scroll', scheduleNotify, { passive: true });
  scheduleNotify();
}

export function subscribeViewport(callback) {
  listeners.add(callback);
  callback(readViewport());
  return () => listeners.delete(callback);
}

export function applyViewportCssVars(width, height) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.style.setProperty('--viewport-w', `${width}px`);
  root.style.setProperty('--viewport-h', `${height}px`);
  root.style.setProperty('--responsive-scale', String(Math.min(1, width / 1280)));
}
