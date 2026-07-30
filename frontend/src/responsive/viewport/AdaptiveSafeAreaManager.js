/**
 * Safe-area CSS variables for notch, Dynamic Island, gesture nav, foldables.
 */

let cleanup = null;

function refreshSafeArea() {
  const root = document.documentElement;
  const sat = getComputedStyle(root).getPropertyValue('env(safe-area-inset-top)') || '0px';
  const sab = getComputedStyle(root).getPropertyValue('env(safe-area-inset-bottom)') || '0px';
  const sal = getComputedStyle(root).getPropertyValue('env(safe-area-inset-left)') || '0px';
  const sar = getComputedStyle(root).getPropertyValue('env(safe-area-inset-right)') || '0px';
  root.style.setProperty('--safe-top', sat.trim() || '0px');
  root.style.setProperty('--safe-bottom', sab.trim() || '0px');
  root.style.setProperty('--safe-left', sal.trim() || '0px');
  root.style.setProperty('--safe-right', sar.trim() || '0px');
  root.style.setProperty(
    '--safe-fab-bottom',
    `calc(4.5rem + ${sab.trim() || '0px'})`,
  );
}

export function initAdaptiveSafeAreaManager() {
  if (typeof window === 'undefined') return;
  refreshSafeArea();
  const handler = () => requestAnimationFrame(refreshSafeArea);
  window.addEventListener('resize', handler, { passive: true });
  window.addEventListener('orientationchange', handler, { passive: true });
  cleanup = () => {
    window.removeEventListener('resize', handler);
    window.removeEventListener('orientationchange', handler);
  };
}

export function disposeAdaptiveSafeAreaManager() {
  cleanup?.();
  cleanup = null;
}
