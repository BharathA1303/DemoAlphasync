import { useRef } from 'react';
import { useResponsiveLayout } from '../hooks/useResponsiveLayout';
import { useResponsive } from '../hooks/useResponsive';
import { ResponsiveTradingLayout } from '../layouts/ResponsiveTradingLayout';
import { TerminalMobileStateEnhancer } from '../mobile/TerminalMobileStateEnhancer';
import { cn } from '../../utils/cn';

/**
 * Mobile layout shell — same as ResponsiveLayoutManager but WITHOUT bottom nav.
 * Desktop uses identical pass-through behavior.
 */
export function HardenedResponsiveShell({ children, isFullViewportPage }) {
  const containerRef = useRef(null);
  const { pageShellClass, shellModifier, isDesktop, routeKey } = useResponsiveLayout();
  const { isTradingRoute } = useResponsive();

  const content = isTradingRoute && !isDesktop ? (
    <ResponsiveTradingLayout isFullViewportPage={isFullViewportPage}>
      {children}
    </ResponsiveTradingLayout>
  ) : (
    children
  );

  return (
    <div ref={containerRef} className="hard-responsive-shell flex flex-col flex-1 min-h-0 min-w-0">
      <div
        className={cn(
          'responsive-layout-manager hard-mobile-shell flex flex-col flex-1 min-h-0 min-w-0',
          shellModifier,
          pageShellClass,
          isFullViewportPage && 'responsive-layout-fullviewport',
        )}
        data-responsive-route={routeKey}
      >
        <div className="responsive-layout-content flex flex-col flex-1 min-h-0 min-w-0 overflow-hidden">
          {content}
        </div>
      </div>
      <TerminalMobileStateEnhancer containerRef={containerRef} />
    </div>
  );
}

export default HardenedResponsiveShell;
