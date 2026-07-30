import { useResponsive } from '../hooks/useResponsive';
import { cn } from '../../utils/cn';
import { chartGestureLock, chartGestureUnlock } from '../gestures/ChartGestureCoordinator';

/**
 * Chart wrapper — touch-action + scroll lock on mobile (desktop unchanged).
 */
export function HardenedChartShell({ children, className }) {
  const { isDesktop } = useResponsive();

  if (isDesktop) {
    return <div className={className}>{children}</div>;
  }

  return (
    <div
      data-hard-chart="true"
      className={cn(
        'hard-chart-shell min-h-0 min-w-0 flex-1 relative',
        className,
      )}
      style={{ touchAction: 'pan-x pan-y pinch-zoom' }}
      onTouchStart={chartGestureLock}
      onTouchEnd={chartGestureUnlock}
      onTouchCancel={chartGestureUnlock}
    >
      {children}
    </div>
  );
}

export default HardenedChartShell;
