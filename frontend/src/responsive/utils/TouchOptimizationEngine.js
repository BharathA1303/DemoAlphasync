import { TOUCH_TARGET_MIN_PX } from '../constants/breakpoints';

export function ensureTouchTarget(el, minPx = TOUCH_TARGET_MIN_PX) {
  if (!el) return;
  const rect = el.getBoundingClientRect();
  if (rect.width < minPx || rect.height < minPx) {
    el.style.minWidth = `${minPx}px`;
    el.style.minHeight = `${minPx}px`;
  }
}

export function enableMomentumScroll(el) {
  if (!el) return;
  el.style.webkitOverflowScrolling = 'touch';
  el.style.overflowScrolling = 'touch';
}

export function applyTouchFeedback(el, className = 'responsive-touch-active') {
  if (!el) return () => {};
  const onStart = () => el.classList.add(className);
  const onEnd = () => el.classList.remove(className);
  el.addEventListener('touchstart', onStart, { passive: true });
  el.addEventListener('touchend', onEnd, { passive: true });
  el.addEventListener('touchcancel', onEnd, { passive: true });
  return () => {
    el.removeEventListener('touchstart', onStart);
    el.removeEventListener('touchend', onEnd);
    el.removeEventListener('touchcancel', onEnd);
  };
}
