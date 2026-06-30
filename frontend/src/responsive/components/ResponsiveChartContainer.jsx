import { useEffect, useRef } from 'react';
import { useResponsive } from '../hooks/useResponsive';
import { cn } from '../../utils/cn';

/**
 * Wraps chart areas for resize-safe, touch-friendly rendering.
 * Desktop: no visual change. Mobile: fullscreen-capable container.
 */
export function ResponsiveChartContainer({ children, className, fullscreenOnMobile = true }) {
  const { isMobile, mobileTradingTab } = useResponsive();
  const ref = useRef(null);

  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(() => {
      window.dispatchEvent(new Event('resize'));
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={cn(
        'responsive-chart-container min-h-0 min-w-0 flex flex-col',
        isMobile && fullscreenOnMobile && mobileTradingTab === 'chart' && 'responsive-chart--mobile-focus',
        className,
      )}
    >
      {children}
    </div>
  );
}

export default ResponsiveChartContainer;
