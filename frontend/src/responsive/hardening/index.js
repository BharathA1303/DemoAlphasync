/* Responsive Phase 2 hardening — public API (additive layer) */

export { ResponsiveHardeningRoot } from './ResponsiveHardeningRoot';
export { HardenedResponsiveShell } from './HardenedResponsiveShell';
export { ResponsiveCrashBoundary } from './ResponsiveCrashBoundary';
export { ResponsiveHydrationGuard } from './ResponsiveHydrationGuard';
export { ResponsiveViewportDebugger } from './ResponsiveViewportDebugger';
export { VirtualizedTradingList } from './VirtualizedTradingList';
export { initResponsiveHardening, disposeResponsiveHardening } from './bootstrap';

export { HardenedOrderDrawer } from '../mobile/HardenedOrderDrawer';
export { HardenedChartShell } from '../mobile/HardenedChartShell';
export { MobileTradeExecutionManager } from '../mobile/MobileTradeExecutionManager';
export { StickyTradeActionSystem } from '../mobile/StickyTradeActionSystem';
export { TerminalMobileStateEnhancer } from '../mobile/TerminalMobileStateEnhancer';
export { HardenedOptionsChainShell } from '../mobile/HardenedOptionsChainShell';

export { initMobileViewportLock } from '../viewport/MobileViewportLock';
export { SNAP_STATES, SNAP_FRACTIONS, createTradePanelSnapController } from '../gestures/TradePanelSnapEngine';
export { chartGestureLock, chartGestureUnlock } from '../gestures/ChartGestureCoordinator';
