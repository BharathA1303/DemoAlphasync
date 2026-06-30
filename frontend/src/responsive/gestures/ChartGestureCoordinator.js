/**
 * Chart touch isolation — prevents page scroll while interacting with charts.
 */

const CHART_SELECTORS = [
  '.terminal-area-chart',
  '.responsive-chart--mobile-focus',
  '[data-hard-chart]',
  '.tv-lightweight-charts',
  'canvas',
].join(',');

let activeLocks = 0;
let cleanup = null;

function isChartTarget(target) {
  return Boolean(target?.closest?.(CHART_SELECTORS));
}

function lock() {
  activeLocks += 1;
  document.documentElement.classList.add('hard-chart-gesture-lock');
  document.documentElement.dataset.chartGesture = 'active';
}

function unlock() {
  activeLocks = Math.max(0, activeLocks - 1);
  if (activeLocks === 0) {
    document.documentElement.classList.remove('hard-chart-gesture-lock');
    delete document.documentElement.dataset.chartGesture;
  }
}

export function chartGestureLock() {
  lock();
}

export function chartGestureUnlock() {
  unlock();
}

function onTouchStart(e) {
  if (isChartTarget(e.target)) lock();
}

function onTouchEnd() {
  unlock();
}

export function initChartGestureCoordinator() {
  if (typeof window === 'undefined') return;
  document.addEventListener('touchstart', onTouchStart, { passive: true, capture: true });
  document.addEventListener('touchend', onTouchEnd, { passive: true, capture: true });
  document.addEventListener('touchcancel', onTouchEnd, { passive: true, capture: true });
  cleanup = () => {
    document.removeEventListener('touchstart', onTouchStart, { capture: true });
    document.removeEventListener('touchend', onTouchEnd, { capture: true });
    document.removeEventListener('touchcancel', onTouchEnd, { capture: true });
    activeLocks = 0;
    document.documentElement.classList.remove('hard-chart-gesture-lock');
    delete document.documentElement.dataset.chartGesture;
  };
}

export function disposeChartGestureCoordinator() {
  cleanup?.();
  cleanup = null;
}
