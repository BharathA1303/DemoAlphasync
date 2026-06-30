import { useEffect, useRef } from 'react';
import { useResponsive } from '../hooks/useResponsive';
import { persistTerminalMode, readTerminalMode } from '../hardening/ResponsiveStatePersistence';

const MODES = ['watchlist', 'chart', 'execution', 'position'];
const TAB_MAP = {
  watchlist: 'watchlist',
  chart: 'chart',
  execution: 'order',
  position: 'chart',
};

/**
 * Swipe between terminal states on mobile (additive — uses existing tab API).
 */
export function TerminalMobileStateEnhancer({ containerRef }) {
  const { isDesktop, setMobileTradingTab } = useResponsive();
  const startX = useRef(0);
  const modeIndex = useRef(1);

  useEffect(() => {
    if (isDesktop) return;
    const saved = readTerminalMode();
    const idx = MODES.indexOf(saved);
    if (idx >= 0) {
      modeIndex.current = idx;
      setMobileTradingTab(TAB_MAP[MODES[idx]] || 'chart');
    }
  }, [isDesktop, setMobileTradingTab]);

  useEffect(() => {
    if (isDesktop) return;
    const el = containerRef?.current;
    if (!el) return;

    const onStart = (e) => {
      startX.current = e.touches?.[0]?.clientX ?? 0;
    };

    const onEnd = (e) => {
      const endX = e.changedTouches?.[0]?.clientX ?? 0;
      const dx = endX - startX.current;
      if (Math.abs(dx) < 56) return;
      if (dx < 0 && modeIndex.current < MODES.length - 1) modeIndex.current += 1;
      if (dx > 0 && modeIndex.current > 0) modeIndex.current -= 1;
      const mode = MODES[modeIndex.current];
      persistTerminalMode(mode);
      setMobileTradingTab(TAB_MAP[mode] || 'chart');
    };

    el.addEventListener('touchstart', onStart, { passive: true });
    el.addEventListener('touchend', onEnd, { passive: true });
    return () => {
      el.removeEventListener('touchstart', onStart);
      el.removeEventListener('touchend', onEnd);
    };
  }, [isDesktop, containerRef, setMobileTradingTab]);

  return null;
}

export default TerminalMobileStateEnhancer;
