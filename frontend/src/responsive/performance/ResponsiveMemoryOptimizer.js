/**
 * Low-end device detection — reduces visual cost automatically.
 */

let cleanup = null;

function classifyDevice() {
  const root = document.documentElement;
  const mem = navigator.deviceMemory;
  const cores = navigator.hardwareConcurrency;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const coarse = window.matchMedia('(pointer: coarse)').matches;
  const lowRam = typeof mem === 'number' && mem <= 4;
  const lowCpu = typeof cores === 'number' && cores <= 4;
  const lowEnd = lowRam || lowCpu;

  root.classList.toggle('hard-low-end', lowEnd);
  root.classList.toggle('hard-reduced-motion', reducedMotion);
  root.classList.toggle('hard-coarse-pointer', coarse);
  root.dataset.deviceTier = lowEnd ? 'low' : reducedMotion ? 'reduced' : 'normal';
}

export function initResponsiveMemoryOptimizer() {
  if (typeof window === 'undefined') return;
  classifyDevice();
  const mql = window.matchMedia('(prefers-reduced-motion: reduce)');
  const handler = () => classifyDevice();
  mql.addEventListener('change', handler);
  window.addEventListener('orientationchange', handler, { passive: true });
  cleanup = () => {
    mql.removeEventListener('change', handler);
    window.removeEventListener('orientationchange', handler);
  };
}

export function disposeResponsiveMemoryOptimizer() {
  cleanup?.();
  cleanup = null;
}
