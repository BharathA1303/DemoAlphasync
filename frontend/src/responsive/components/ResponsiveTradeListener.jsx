/**
 * Bridges mobile FAB trade events to URL params (terminal already reads ?side=).
 * No changes to existing page components.
 */
import { useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useResponsive } from '../hooks/useResponsive';

export function ResponsiveTradeListener() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isDesktop, isTradingRoute, setMobileTradingTab } = useResponsive();

  useEffect(() => {
    if (isDesktop || !isTradingRoute) return;

    const handler = (e) => {
      const side = e.detail?.side;
      if (side !== 'BUY' && side !== 'SELL') return;
      setMobileTradingTab('order');
      const params = new URLSearchParams(location.search);
      params.set('side', side);
      navigate({ pathname: location.pathname, search: params.toString() }, { replace: false });
      window.dispatchEvent(new CustomEvent('responsive:open-order-panel', { detail: { side } }));
    };

    window.addEventListener('responsive:trade', handler);
    return () => window.removeEventListener('responsive:trade', handler);
  }, [isDesktop, isTradingRoute, location.pathname, location.search, navigate, setMobileTradingTab]);

  return null;
}

export default ResponsiveTradeListener;
