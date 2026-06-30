import { useResponsive } from '../hooks/useResponsive';
import { cn } from '../../utils/cn';

/** Visibility coordinator for watchlist panels on mobile trading tabs. */
export function ResponsiveWatchlistLayout({ children, className }) {
  const { isDesktop, mobileTradingTab } = useResponsive();

  if (isDesktop) {
    return <div className={cn('responsive-watchlist-desktop', className)}>{children}</div>;
  }

  const visible = mobileTradingTab === 'watchlist';

  return (
    <div
      className={cn(
        'responsive-watchlist-mobile',
        visible ? 'responsive-panel-visible' : 'responsive-panel-hidden',
        className,
      )}
      aria-hidden={!visible}
    >
      {children}
    </div>
  );
}

export default ResponsiveWatchlistLayout;
