import { useResponsiveContextSafe } from '../providers/ResponsiveProvider';
import { LAYOUT_MODE } from '../constants/breakpoints';

const FALLBACK = {
  width: 1280,
  height: 800,
  breakpoint: 'xl',
  layoutMode: LAYOUT_MODE.DESKTOP,
  deviceCategory: 'desktop',
  heightTier: 'medium',
  isDesktop: true,
  isTablet: false,
  isMobile: false,
  isCompact: false,
  isTouch: false,
  capabilities: { touch: false, hover: true, landscape: false, foldable: false },
  routeKey: 'default',
  isTradingRoute: false,
  mobileTradingTab: 'chart',
  setMobileTradingTab: () => {},
  isDesktopWidth: true,
  isTabletWidth: false,
  isMobileWidth: false,
};

export function useResponsive() {
  const ctx = useResponsiveContextSafe();
  return ctx ?? FALLBACK;
}

export default useResponsive;
