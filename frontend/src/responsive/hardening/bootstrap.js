/**
 * Initializes all responsive hardening modules (additive layer).
 */
import { initMobileViewportLock, disposeMobileViewportLock } from '../viewport/MobileViewportLock';
import { initAdaptiveSafeAreaManager, disposeAdaptiveSafeAreaManager } from '../viewport/AdaptiveSafeAreaManager';
import { initScrollContainmentEngine, disposeScrollContainmentEngine } from '../gestures/ScrollContainmentEngine';
import { initChartGestureCoordinator, disposeChartGestureCoordinator } from '../gestures/ChartGestureCoordinator';
import { initAdaptiveTouchFeedback, disposeAdaptiveTouchFeedback } from '../gestures/AdaptiveTouchFeedback';
import { initResponsivePerformanceManager, disposeResponsivePerformanceManager } from '../performance/ResponsivePerformanceManager';
import { initResponsiveMemoryOptimizer, disposeResponsiveMemoryOptimizer } from '../performance/ResponsiveMemoryOptimizer';
import { initResponsiveAnimationCoordinator, disposeResponsiveAnimationCoordinator } from '../performance/ResponsiveAnimationCoordinator';
import { initMobileKeyboardCoordinator, disposeMobileKeyboardCoordinator } from '../mobile/MobileKeyboardCoordinator';
import { initMobileTradeSurfaceRegistry } from '../mobile/MobileTradeSurfaceRegistry';
import {
  initResponsiveStatePersistence,
  disposeResponsiveStatePersistence,
} from './ResponsiveStatePersistence';
import { initResponsiveInteractionProfiler, disposeResponsiveInteractionProfiler } from '../performance/ResponsiveInteractionProfiler';

let active = false;
let disposeTradeSurfaces = null;

export function initResponsiveHardening(responsiveContext = null) {
  if (active || typeof window === 'undefined') return () => {};
  active = true;

  initMobileViewportLock();
  initAdaptiveSafeAreaManager();
  initScrollContainmentEngine();
  initChartGestureCoordinator();
  initAdaptiveTouchFeedback();
  initResponsivePerformanceManager();
  initResponsiveMemoryOptimizer();
  initResponsiveAnimationCoordinator();
  initMobileKeyboardCoordinator();
  initResponsiveStatePersistence(responsiveContext);
  initResponsiveInteractionProfiler();
  disposeTradeSurfaces = initMobileTradeSurfaceRegistry();

  document.documentElement.classList.add('responsive-hardening-active');

  return disposeResponsiveHardening;
}

export function disposeResponsiveHardening() {
  if (!active) return;
  active = false;

  disposeMobileViewportLock();
  disposeAdaptiveSafeAreaManager();
  disposeScrollContainmentEngine();
  disposeChartGestureCoordinator();
  disposeAdaptiveTouchFeedback();
  disposeResponsivePerformanceManager();
  disposeResponsiveMemoryOptimizer();
  disposeResponsiveAnimationCoordinator();
  disposeMobileKeyboardCoordinator();
  disposeResponsiveInteractionProfiler();
  disposeResponsiveStatePersistence();
  disposeTradeSurfaces?.();
  disposeTradeSurfaces = null;

  document.documentElement.classList.remove('responsive-hardening-active');
}
