import { useEffect } from 'react';
import { useResponsiveContextSafe } from '../providers/ResponsiveProvider';
import { initResponsiveHardening, disposeResponsiveHardening } from './bootstrap';
import { ResponsiveCrashBoundary } from './ResponsiveCrashBoundary';
import { ResponsiveHydrationGuard } from './ResponsiveHydrationGuard';
import { ResponsiveViewportDebugger } from './ResponsiveViewportDebugger';
import { StickyTradeActionSystem } from '../mobile/StickyTradeActionSystem';
import './ResponsiveHardening.css';
import './MobileAppLayout.css';

/**
 * Global responsive hardening orchestrator (additive — does not replace ResponsiveProvider).
 */
export function ResponsiveHardeningRoot({ children }) {
  const ctx = useResponsiveContextSafe();

  useEffect(() => {
    const dispose = initResponsiveHardening(ctx);
    return () => {
      dispose?.();
      disposeResponsiveHardening();
    };
  }, [ctx]);

  return (
    <ResponsiveCrashBoundary>
      <ResponsiveHydrationGuard>
        {children}
        <StickyTradeActionSystem />
        <ResponsiveViewportDebugger />
      </ResponsiveHydrationGuard>
    </ResponsiveCrashBoundary>
  );
}

export default ResponsiveHardeningRoot;
