/**
 * Responsive QA — viewport presets for manual / automated testing.
 */
import { TEST_VIEWPORTS } from '../constants/breakpoints';

export { TEST_VIEWPORTS };

export function applyTestViewport(width, height = 800) {
  if (typeof document === 'undefined') return;
  document.documentElement.style.setProperty('--test-viewport-w', `${width}px`);
  document.documentElement.dataset.testViewport = String(width);
}

export function getViewportChecklist() {
  return TEST_VIEWPORTS.map((w) => ({
    width: w,
    label: `${w}px`,
    checks: [
      'no horizontal overflow',
      'no overlapping panels',
      'chart not clipped',
      'buttons >= 44px touch target',
      'forms accessible',
      'sidebar no overflow',
      'ticker no overlap',
      'modals fit viewport',
    ],
  }));
}
