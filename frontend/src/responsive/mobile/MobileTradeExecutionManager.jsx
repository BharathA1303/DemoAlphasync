import { useEffect, useRef } from 'react';
import { useResponsive } from '../hooks/useResponsive';
import { createTradePanelSnapController, SNAP_STATES } from '../gestures/TradePanelSnapEngine';
import { persistOrderSnapState, readOrderSnapState } from '../hardening/ResponsiveStatePersistence';

/**
 * Enhances mobile order drawers / sheets with snap points (non-desktop only).
 */
export function MobileTradeExecutionManager({ panelRef, enabled = true }) {
  const { isDesktop } = useResponsive();
  const controllerRef = useRef(null);

  useEffect(() => {
    if (isDesktop || !enabled) return;
    const panel = panelRef?.current;
    if (!panel) return;

    panel.classList.add('hard-order-surface');
    panel.dataset.scrollRegion = 'y';

    const saved = readOrderSnapState();
    const initial = saved && Object.values(SNAP_STATES).includes(saved)
      ? saved
      : SNAP_STATES.PREVIEW;

    controllerRef.current = createTradePanelSnapController(panel, {
      onStateChange: (state) => persistOrderSnapState(state),
    });
    controllerRef.current?.setState?.(initial);

    const handle = panel.querySelector('.hard-order-snap-handle');
    if (handle) handle.style.touchAction = 'none';

    return () => {
      controllerRef.current?.destroy?.();
      controllerRef.current = null;
    };
  }, [isDesktop, enabled, panelRef]);

  return null;
}

export default MobileTradeExecutionManager;
