/**
 * Viewport-based rendering — pause offscreen animation-heavy subtrees.
 */

let observer = null;
let cleanup = null;

export function initResponsivePerformanceManager() {
  if (typeof window === 'undefined' || !('IntersectionObserver' in window)) return;

  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const el = entry.target;
        if (entry.isIntersecting) {
          el.classList.remove('hard-offscreen-paused');
          el.removeAttribute('inert');
        } else {
          el.classList.add('hard-offscreen-paused');
          if (el.dataset.hardPauseInert === 'true') el.setAttribute('inert', '');
        }
      }
    },
    { rootMargin: '80px', threshold: 0.01 },
  );

  const mark = () => {
    document
      .querySelectorAll('[data-hard-pause-offscreen], .responsive-trading-layout, .ticker-marquee')
      .forEach((el) => observer.observe(el));
  };

  mark();
  const mo = new MutationObserver(mark);
  mo.observe(document.body, { childList: true, subtree: true });
  cleanup = () => {
    mo.disconnect();
    observer?.disconnect();
    observer = null;
  };
}

export function disposeResponsivePerformanceManager() {
  cleanup?.();
  cleanup = null;
}
