/* AlphaSync Responsive Architecture — public API */

export { ResponsiveProvider, useResponsiveContext, useResponsiveContextSafe } from './providers/ResponsiveProvider';
export { useResponsive } from './hooks/useResponsive';
export { useDeviceCategory } from './hooks/useDeviceCategory';
export { useResponsiveLayout } from './hooks/useResponsiveLayout';
export { useResponsiveTradeBridge } from './hooks/useResponsiveTradeBridge';

export { ResponsiveLayoutManager } from './layouts/ResponsiveLayoutManager';
export { ResponsiveTradingLayout } from './layouts/ResponsiveTradingLayout';

export { AdaptiveSidebarManager } from './components/AdaptiveSidebarManager';
export { ResponsiveBottomNavigation } from './components/ResponsiveBottomNavigation';
export { ResponsiveChartContainer } from './components/ResponsiveChartContainer';
export { ResponsiveWatchlistLayout } from './components/ResponsiveWatchlistLayout';
export { ResponsiveOrderPanel } from './components/ResponsiveOrderPanel';
export { ResponsiveModalSystem } from './components/ResponsiveModalSystem';
export { ResponsiveTableEngine } from './components/ResponsiveTableEngine';
export { MobileFloatingActions } from './components/MobileFloatingActions';

export * from './constants/breakpoints';
export { getLayoutMode, isDesktopWidth } from './utils/BreakpointSystem';
export { snapshotDeviceCapabilities } from './utils/DeviceDetectionEngine';
