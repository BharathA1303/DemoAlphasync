import { useResponsive } from './useResponsive';
import { getAdaptiveGridClass } from '../utils/AdaptiveGridEngine';

export function useResponsiveLayout(variant = 'default') {
  const { layoutMode, isDesktop, isMobile, isTablet, routeKey, isTradingRoute } = useResponsive();
  const gridClass = getAdaptiveGridClass(layoutMode, variant);

  return {
    layoutMode,
    isDesktop,
    isMobile,
    isTablet,
    routeKey,
    isTradingRoute,
    gridClass,
    pageShellClass: `responsive-page responsive-page--${routeKey}`,
    shellModifier: isDesktop ? 'responsive-shell-desktop' : isTablet ? 'responsive-shell-tablet' : 'responsive-shell-mobile',
  };
}

export default useResponsiveLayout;
