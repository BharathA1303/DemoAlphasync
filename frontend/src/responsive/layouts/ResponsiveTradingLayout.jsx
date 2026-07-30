/**
 * Mobile/tablet trading workflow shell — chart / watchlist / order modes.
 * Desktop: transparent pass-through (children unchanged).
 */
import { useResponsive } from '../hooks/useResponsive';
import MobileFloatingActions from '../components/MobileFloatingActions';
import ResponsiveTradeListener from '../components/ResponsiveTradeListener';
import { cn } from '../../utils/cn';

const TABS = [
  { key: 'chart', label: 'Chart' },
  { key: 'watchlist', label: 'Watchlist' },
  { key: 'order', label: 'Trade' },
];

export function ResponsiveTradingLayout({ children, isFullViewportPage }) {
  const { isDesktop, mobileTradingTab, setMobileTradingTab, routeKey } = useResponsive();

  if (isDesktop) {
    return <>{children}</>;
  }

  return (
    <div
      className={cn(
        'responsive-trading-layout flex flex-col flex-1 min-h-0 min-w-0',
        isFullViewportPage && 'responsive-trading-layout--fullscreen',
      )}
      data-trading-tab={mobileTradingTab}
      data-route={routeKey}
    >
      <div className="responsive-trading-tabs flex-shrink-0 flex border-b border-edge/10 bg-surface-900/80 backdrop-blur-md safe-area-top-pad">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setMobileTradingTab(tab.key)}
            className={cn(
              'flex-1 py-2.5 text-xs font-semibold transition-colors min-h-[44px]',
              mobileTradingTab === tab.key
                ? 'text-primary-600 border-b-2 border-primary-600'
                : 'text-gray-500 hover:text-heading',
            )}
            aria-selected={mobileTradingTab === tab.key}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div
        className={cn(
          'responsive-trading-body flex-1 min-h-0 min-w-0 overflow-hidden',
          `responsive-trading-view--${mobileTradingTab}`,
        )}
      >
        {children}
      </div>

      <ResponsiveTradeListener />
      <MobileFloatingActions />
    </div>
  );
}

export default ResponsiveTradingLayout;
