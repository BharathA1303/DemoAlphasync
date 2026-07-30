/**
 * Auto-attaches snap engine to mobile order bottom sheets in the DOM.
 */
import { createTradePanelSnapController, SNAP_STATES } from '../gestures/TradePanelSnapEngine';
import { readOrderSnapState, persistOrderSnapState } from '../hardening/ResponsiveStatePersistence';

const controllers = new Map();
let observer = null;

function attach(el) {
  if (controllers.has(el)) return;
  const saved = readOrderSnapState();
  const initial = saved && Object.values(SNAP_STATES).includes(saved)
    ? saved
    : SNAP_STATES.PREVIEW;
  const ctrl = createTradePanelSnapController(el, {
    onStateChange: persistOrderSnapState,
  });
  ctrl?.setState?.(initial);
  controllers.set(el, ctrl);
}

function scan() {
  if (typeof document === 'undefined') return;
  if (window.matchMedia('(min-width: 1024px)').matches) return;
  document
    .querySelectorAll('.responsive-order-mobile.responsive-order-sheet--open')
    .forEach((el) => {
      el.classList.add('hard-order-surface');
      attach(el);
    });
}

export function initMobileTradeSurfaceRegistry() {
  scan();
  observer = new MutationObserver(scan);
  observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  return () => {
    observer?.disconnect();
    controllers.forEach((c) => c.destroy?.());
    controllers.clear();
  };
}
