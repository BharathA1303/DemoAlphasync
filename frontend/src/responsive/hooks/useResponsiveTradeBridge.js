/**
 * Optional hook for trading pages to open order panel from mobile FAB / tabs.
 * Import in FuturesPage or similar without changing business logic.
 */
import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useResponsive } from './useResponsive';

export function useResponsiveTradeBridge({ onOpenOrderPanel }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { isDesktop, setMobileTradingTab } = useResponsive();

  useEffect(() => {
    if (isDesktop) return;
    const side = searchParams.get('side');
    if (side === 'BUY' || side === 'SELL') {
      setMobileTradingTab('order');
      onOpenOrderPanel?.(side);
    }
  }, [searchParams, isDesktop, setMobileTradingTab, onOpenOrderPanel]);

  useEffect(() => {
    if (isDesktop || !onOpenOrderPanel) return;
    const handler = (e) => {
      const side = e.detail?.side;
      if (side === 'BUY' || side === 'SELL') {
        setMobileTradingTab('order');
        onOpenOrderPanel(side);
      }
    };
    window.addEventListener('responsive:open-order-panel', handler);
    return () => window.removeEventListener('responsive:open-order-panel', handler);
  }, [isDesktop, onOpenOrderPanel, setMobileTradingTab]);
}

export default useResponsiveTradeBridge;
