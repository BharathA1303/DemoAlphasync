/**
 * Central layout orchestrator — desktop pass-through, mobile/tablet adaptations.
 * Does NOT alter desktop panel structure; only adds wrappers + mobile chrome.
 */
import { useResponsiveLayout } from '../hooks/useResponsiveLayout';
import { useResponsive } from '../hooks/useResponsive';
import ResponsiveBottomNavigation from '../components/ResponsiveBottomNavigation';
import ResponsiveTradingLayout from './ResponsiveTradingLayout';
import { cn } from '../../utils/cn';

export function ResponsiveLayoutManager({ children, isFullViewportPage = false }) {
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
    <div
      className={cn(
        'responsive-layout-manager flex flex-col flex-1 min-h-0 min-w-0',
        shellModifier,
        pageShellClass,
        isFullViewportPage && 'responsive-layout-fullviewport',
      )}
      data-responsive-route={routeKey}
    >
      <div className="responsive-layout-content flex flex-col flex-1 min-h-0 min-w-0 overflow-hidden">
        {content}
      </div>
      {!isDesktop && <ResponsiveBottomNavigation />}
    </div>
  );
}

export default ResponsiveLayoutManager;
