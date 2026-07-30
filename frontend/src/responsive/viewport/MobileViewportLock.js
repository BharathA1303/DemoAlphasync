/**
 * Global viewport lock — dvh/svh/lvh, overflow-x, address-bar stability.
 */

let cleanup = null;

function setViewportUnits() {
  const root = document.documentElement;
  const h = window.innerHeight;
  const vh = h * 0.01;
  root.style.setProperty('--vh', `${vh}px`);
  root.style.setProperty('--app-vh', `${h}px`);

  if (typeof CSS !== 'undefined' && CSS.supports?.('height', '100dvh')) {
    root.style.setProperty('--viewport-height', '100dvh');
    root.style.setProperty('--viewport-min-height', '100svh');
    root.style.setProperty('--viewport-max-height', '100lvh');
  } else {
    root.style.setProperty('--viewport-height', `calc(var(--vh, 1vh) * 100)`);
    root.style.setProperty('--viewport-min-height', `calc(var(--vh, 1vh) * 100)`);
    root.style.setProperty('--viewport-max-height', `calc(var(--vh, 1vh) * 100)`);
  }

  const vv = window.visualViewport;
  if (vv) {
    root.style.setProperty('--visual-viewport-w', `${vv.width}px`);
    root.style.setProperty('--visual-viewport-h', `${vv.height}px`);
    root.style.setProperty('--visual-viewport-offset-top', `${vv.offsetTop}px`);
  }
}

function onResize() {
  requestAnimationFrame(setViewportUnits);
}

export function initMobileViewportLock() {
  if (typeof window === 'undefined') return;
  setViewportUnits();
  window.addEventListener('resize', onResize, { passive: true });
  window.visualViewport?.addEventListener('resize', onResize, { passive: true });
  window.visualViewport?.addEventListener('scroll', onResize, { passive: true });
  window.addEventListener('orientationchange', onResize, { passive: true });
  cleanup = () => {
    window.removeEventListener('resize', onResize);
    window.visualViewport?.removeEventListener('resize', onResize);
    window.visualViewport?.removeEventListener('scroll', onResize);
    window.removeEventListener('orientationchange', onResize);
  };
}

export function disposeMobileViewportLock() {
  cleanup?.();
  cleanup = null;
}
