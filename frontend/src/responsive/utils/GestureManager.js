/**
 * Lightweight swipe gesture handler for drawers and mobile panels.
 */

const SWIPE_THRESHOLD = 48;
const SWIPE_VELOCITY = 0.3;

export function createSwipeHandler({ onSwipeLeft, onSwipeRight, onSwipeUp, onSwipeDown, axis = 'x' }) {
  let startX = 0;
  let startY = 0;
  let startTime = 0;

  const onTouchStart = (e) => {
    const t = e.touches[0];
    if (!t) return;
    startX = t.clientX;
    startY = t.clientY;
    startTime = Date.now();
  };

  const onTouchEnd = (e) => {
    const t = e.changedTouches[0];
    if (!t) return;
    const dx = t.clientX - startX;
    const dy = t.clientY - startY;
    const dt = Math.max(1, Date.now() - startTime);
    const vx = Math.abs(dx) / dt;
    const vy = Math.abs(dy) / dt;

    if (axis === 'x' || axis === 'both') {
      if (Math.abs(dx) > SWIPE_THRESHOLD && vx > SWIPE_VELOCITY) {
        if (dx > 0) onSwipeRight?.();
        else onSwipeLeft?.();
      }
    }
    if (axis === 'y' || axis === 'both') {
      if (Math.abs(dy) > SWIPE_THRESHOLD && vy > SWIPE_VELOCITY) {
        if (dy > 0) onSwipeDown?.();
        else onSwipeUp?.();
      }
    }
  };

  return { onTouchStart, onTouchEnd };
}

export function attachSwipe(el, handlers, axis = 'x') {
  if (!el) return () => {};
  const h = createSwipeHandler({ ...handlers, axis });
  el.addEventListener('touchstart', h.onTouchStart, { passive: true });
  el.addEventListener('touchend', h.onTouchEnd, { passive: true });
  return () => {
    el.removeEventListener('touchstart', h.onTouchStart);
    el.removeEventListener('touchend', h.onTouchEnd);
  };
}
