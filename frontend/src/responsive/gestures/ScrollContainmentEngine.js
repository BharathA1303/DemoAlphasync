/**
 * Isolates nested scroll regions — prevents scroll chaining chaos.
 */

const REGION_SELECTOR = [
  '[data-scroll-region]',
  '.responsive-trading-body',
  '.terminal-area-chart',
  '.responsive-order-mobile',
  '.responsive-modal-sheet',
  '.responsive-table-desktop',
  '.hard-virtual-list',
  '.hard-order-surface',
].join(',');

let cleanup = null;

function markRegions() {
  document.querySelectorAll(REGION_SELECTOR).forEach((el) => {
    if (!el.dataset.scrollRegion) el.dataset.scrollRegion = 'auto';
    el.classList.add('hard-scroll-contained');
  });
}

function onTouchMove(e) {
  const region = e.target?.closest?.('[data-scroll-region], .hard-scroll-contained');
  if (!region) return;
  const { scrollTop, scrollHeight, clientHeight } = region;
  const atTop = scrollTop <= 0;
  const atBottom = scrollTop + clientHeight >= scrollHeight - 1;
  if (atTop || atBottom) {
    e.stopPropagation();
  }
}

export function initScrollContainmentEngine() {
  if (typeof window === 'undefined') return;
  markRegions();
  const observer = new MutationObserver(() => markRegions());
  observer.observe(document.body, { childList: true, subtree: true });
  document.addEventListener('touchmove', onTouchMove, { passive: false, capture: true });
  cleanup = () => {
    observer.disconnect();
    document.removeEventListener('touchmove', onTouchMove, { capture: true });
  };
}

export function disposeScrollContainmentEngine() {
  cleanup?.();
  cleanup = null;
}
