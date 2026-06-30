/**
 * Draggable bottom-sheet snap engine for mobile order surfaces.
 * Snap states: collapsed | preview | execution | confirmation
 */

export const SNAP_STATES = {
  COLLAPSED: 'collapsed',
  PREVIEW: 'preview',
  EXECUTION: 'execution',
  CONFIRMATION: 'confirmation',
};

/** Fraction of viewport height for each snap point */
export const SNAP_FRACTIONS = {
  [SNAP_STATES.COLLAPSED]: 0.12,
  [SNAP_STATES.PREVIEW]: 0.42,
  [SNAP_STATES.EXECUTION]: 0.72,
  [SNAP_STATES.CONFIRMATION]: 0.92,
};

export function fractionToHeight(fraction) {
  const vh = window.visualViewport?.height ?? window.innerHeight;
  const safeBottom = parseFloat(
    getComputedStyle(document.documentElement).getPropertyValue('--safe-bottom') || '0',
  ) || 0;
  return Math.round(vh * fraction - safeBottom);
}

export function nearestSnapState(currentHeight) {
  const vh = window.visualViewport?.height ?? window.innerHeight;
  const ratio = currentHeight / vh;
  let best = SNAP_STATES.PREVIEW;
  let bestDist = Infinity;
  for (const [state, frac] of Object.entries(SNAP_FRACTIONS)) {
    const dist = Math.abs(ratio - frac);
    if (dist < bestDist) {
      bestDist = dist;
      best = state;
    }
  }
  return best;
}

export function createTradePanelSnapController(panelEl, { onStateChange } = {}) {
  if (!panelEl) return null;

  let state = SNAP_STATES.PREVIEW;
  let startY = 0;
  let startHeight = 0;
  let dragging = false;

  const applyState = (next) => {
    state = next;
    const h = fractionToHeight(SNAP_FRACTIONS[next]);
    panelEl.style.height = `${h}px`;
    panelEl.style.maxHeight = `${h}px`;
    panelEl.dataset.snapState = next;
    onStateChange?.(next);
  };

  applyState(SNAP_STATES.PREVIEW);

  const onPointerDown = (e) => {
    if (e.button !== undefined && e.button !== 0) return;
    dragging = true;
    startY = e.clientY ?? e.touches?.[0]?.clientY ?? 0;
    startHeight = panelEl.getBoundingClientRect().height;
    panelEl.setPointerCapture?.(e.pointerId);
    panelEl.classList.add('hard-snap-dragging');
  };

  const onPointerMove = (e) => {
    if (!dragging) return;
    const y = e.clientY ?? e.touches?.[0]?.clientY ?? 0;
    const delta = startY - y;
    const nextH = Math.max(
      fractionToHeight(SNAP_FRACTIONS[SNAP_STATES.COLLAPSED]),
      Math.min(fractionToHeight(SNAP_FRACTIONS[SNAP_STATES.CONFIRMATION]), startHeight + delta),
    );
    panelEl.style.height = `${nextH}px`;
    panelEl.style.maxHeight = `${nextH}px`;
  };

  const onPointerUp = (e) => {
    if (!dragging) return;
    dragging = false;
    panelEl.classList.remove('hard-snap-dragging');
    panelEl.releasePointerCapture?.(e.pointerId);
    const h = panelEl.getBoundingClientRect().height;
    const velocity = (e.clientY ?? 0) - startY;
    let target = nearestSnapState(h);
    if (Math.abs(velocity) > 40) {
      const order = Object.keys(SNAP_FRACTIONS);
      const idx = order.indexOf(target);
      target = velocity < 0 ? order[Math.min(idx + 1, order.length - 1)] : order[Math.max(idx - 1, 0)];
    }
    applyState(target);
  };

  panelEl.addEventListener('pointerdown', onPointerDown);
  panelEl.addEventListener('pointermove', onPointerMove);
  panelEl.addEventListener('pointerup', onPointerUp);
  panelEl.addEventListener('pointercancel', onPointerUp);

  return {
    setState: applyState,
    getState: () => state,
    destroy: () => {
      panelEl.removeEventListener('pointerdown', onPointerDown);
      panelEl.removeEventListener('pointermove', onPointerMove);
      panelEl.removeEventListener('pointerup', onPointerUp);
      panelEl.removeEventListener('pointercancel', onPointerUp);
    },
  };
}
