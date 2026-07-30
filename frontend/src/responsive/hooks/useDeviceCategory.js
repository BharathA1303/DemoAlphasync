import { useResponsive } from './useResponsive';

export function useDeviceCategory() {
  const { deviceCategory, layoutMode, isMobile, isTablet, isDesktop, capabilities } = useResponsive();
  return {
    deviceCategory,
    layoutMode,
    isMobile,
    isTablet,
    isDesktop,
    isFoldable: capabilities.foldable,
    isTouch: capabilities.touch,
    hasHover: capabilities.hover,
    isLandscape: capabilities.landscape,
  };
}

export default useDeviceCategory;
