/**
 * GPU-friendly, interruptible animation tiering.
 */

let cleanup = null;

export function initResponsiveAnimationCoordinator() {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const lowEnd = root.classList.contains('hard-low-end');
  const tier = reduced ? 'minimal' : lowEnd ? 'light' : 'full';
  root.dataset.animationTier = tier;
  root.classList.toggle('hard-anim-minimal', tier === 'minimal');
  root.classList.toggle('hard-anim-light', tier === 'light');

  const handler = () => {
    const r = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    root.dataset.animationTier = r ? 'minimal' : root.classList.contains('hard-low-end') ? 'light' : 'full';
  };
  window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', handler);
  cleanup = () => window.matchMedia('(prefers-reduced-motion: reduce)').removeEventListener('change', handler);
}

export function disposeResponsiveAnimationCoordinator() {
  cleanup?.();
  cleanup = null;
}
