import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { initViewportCoordinator, subscribeViewport, applyViewportCssVars } from '../utils/ViewportCoordinator';
import { snapshotDeviceCapabilities } from '../utils/DeviceDetectionEngine';
import {
  getBreakpointKey,
  getLayoutMode,
  getDeviceCategory,
  getHeightTier,
  isDesktopWidth,
  isTabletWidth,
  isMobileWidth,
} from '../utils/BreakpointSystem';
import { TRADING_ROUTES, LAYOUT_MODE } from '../constants/breakpoints';

const ResponsiveContext = createContext(null);

export function ResponsiveProvider({ children }) {
  const location = useLocation();
  const readViewport = () => ({
    width: typeof window !== 'undefined' ? Math.max(window.innerWidth, 1) : 1280,
    height: typeof window !== 'undefined' ? Math.max(window.innerHeight, 1) : 800,
  });

  const [viewport, setViewport] = useState(readViewport);
  const [capabilities, setCapabilities] = useState(() => snapshotDeviceCapabilities());
  const [mobileTradingTab, setMobileTradingTab] = useState('chart');

  useLayoutEffect(() => {
    initViewportCoordinator();
    const vp = readViewport();
    setViewport(vp);
    applyViewportCssVars(vp.width, vp.height);
  }, []);

  useEffect(() => {
    return subscribeViewport((vp) => {
      setViewport({ width: vp.width, height: vp.height });
      applyViewportCssVars(vp.width, vp.height);
    });
  }, []);

  useEffect(() => {
    const refresh = () => setCapabilities(snapshotDeviceCapabilities());
    window.addEventListener('orientationchange', refresh, { passive: true });
    const mql = window.matchMedia('(orientation: landscape)');
    mql.addEventListener('change', refresh);
    return () => {
      window.removeEventListener('orientationchange', refresh);
      mql.removeEventListener('change', refresh);
    };
  }, []);

  const { width, height } = viewport;
  const breakpoint = getBreakpointKey(width);
  const layoutMode = getLayoutMode(width);
  const deviceCategory = getDeviceCategory(width, height, { foldable: capabilities.foldable });
  const heightTier = getHeightTier(height);

  const isDesktop = layoutMode === LAYOUT_MODE.DESKTOP;
  const isTablet = layoutMode === LAYOUT_MODE.TABLET;
  const isMobile = layoutMode === LAYOUT_MODE.MOBILE;
  const isCompact = !isDesktop;
  const isTouch = capabilities.touch;

  const routeKey = useMemo(() => {
    const p = location.pathname;
    if (p.startsWith('/terminal')) return 'terminal';
    if (p.startsWith('/futures')) return 'futures';
    if (p.startsWith('/options')) return 'options';
    if (p.startsWith('/commodities')) return 'commodities';
    if (p.startsWith('/market')) return 'market';
    if (p.startsWith('/portfolio')) return 'portfolio';
    if (p.startsWith('/orders')) return 'orders';
    if (p.startsWith('/leaderboard')) return 'leaderboard';
    if (p.startsWith('/algo') || p.startsWith('/zeroloss') || p.startsWith('/auto-alpha')) return 'algo';
    if (p.startsWith('/settings')) return 'settings';
    if (p.startsWith('/bug-report')) return 'bug-report';
    if (p.startsWith('/dashboard')) return 'dashboard';
    if (p.startsWith('/mentor')) return 'mentor';
    if (p === '/' || p.startsWith('/login')) return 'auth';
    return 'default';
  }, [location.pathname]);

  const isTradingRoute = TRADING_ROUTES.some((r) => location.pathname.startsWith(r));

  useEffect(() => {
    if (typeof document === 'undefined') return;
    const root = document.documentElement;
    root.classList.add('responsive-active');
    root.dataset.layoutMode = layoutMode;
    root.dataset.breakpoint = breakpoint;
    root.dataset.device = deviceCategory;
    root.dataset.route = routeKey;
    root.dataset.touch = isTouch ? 'true' : 'false';
    if (capabilities.foldable) root.dataset.foldable = 'true';
    else delete root.dataset.foldable;
    return () => {
      root.classList.remove('responsive-active');
      delete root.dataset.layoutMode;
      delete root.dataset.breakpoint;
      delete root.dataset.device;
      delete root.dataset.route;
      delete root.dataset.touch;
      delete root.dataset.foldable;
    };
  }, [layoutMode, breakpoint, deviceCategory, routeKey, isTouch, capabilities.foldable]);

  const value = useMemo(
    () => ({
      width,
      height,
      breakpoint,
      layoutMode,
      deviceCategory,
      heightTier,
      isDesktop,
      isTablet,
      isMobile,
      isCompact,
      isTouch,
      capabilities,
      routeKey,
      isTradingRoute,
      mobileTradingTab,
      setMobileTradingTab,
      isDesktopWidth: isDesktopWidth(width),
      isTabletWidth: isTabletWidth(width),
      isMobileWidth: isMobileWidth(width),
    }),
    [
      width,
      height,
      breakpoint,
      layoutMode,
      deviceCategory,
      heightTier,
      isDesktop,
      isTablet,
      isMobile,
      isCompact,
      isTouch,
      capabilities,
      routeKey,
      isTradingRoute,
      mobileTradingTab,
    ]
  );

  return (
    <ResponsiveContext.Provider value={value}>
      <div className="responsive-provider-root min-h-0 flex flex-col flex-1">
        {children}
      </div>
    </ResponsiveContext.Provider>
  );
}

export function useResponsiveContext() {
  const ctx = useContext(ResponsiveContext);
  if (!ctx) {
    throw new Error('useResponsiveContext must be used within ResponsiveProvider');
  }
  return ctx;
}

/** Safe hook — returns null outside provider (public routes). */
export function useResponsiveContextSafe() {
  return useContext(ResponsiveContext);
}

export default ResponsiveProvider;
