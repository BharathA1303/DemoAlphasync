/**
 * Lightweight touch feedback (haptic-ready architecture).
 */

let cleanup = null;

function onTouchStart(e) {
  const el = e.target?.closest?.(
    'button, a, [role="button"], .responsive-fab, .responsive-trading-tabs button',
  );
  if (!el || el.disabled) return;
  el.classList.add('hard-touch-active');
}

function onTouchEnd(e) {
  document.querySelectorAll('.hard-touch-active').forEach((el) => {
    el.classList.remove('hard-touch-active');
  });
}

export function initAdaptiveTouchFeedback() {
  if (typeof window === 'undefined') return;
  document.addEventListener('touchstart', onTouchStart, { passive: true, capture: true });
  document.addEventListener('touchend', onTouchEnd, { passive: true, capture: true });
  document.addEventListener('touchcancel', onTouchEnd, { passive: true, capture: true });
  cleanup = () => {
    document.removeEventListener('touchstart', onTouchStart, { capture: true });
    document.removeEventListener('touchend', onTouchEnd, { capture: true });
    document.removeEventListener('touchcancel', onTouchEnd, { capture: true });
  };
}

export function disposeAdaptiveTouchFeedback() {
  cleanup?.();
  cleanup = null;
}
