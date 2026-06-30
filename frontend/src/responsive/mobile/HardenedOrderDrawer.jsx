import { useRef } from 'react';
import ResponsiveDrawer from '../../components/layout/ResponsiveDrawer';
import { useResponsive } from '../hooks/useResponsive';
import { cn } from '../../utils/cn';
import MobileTradeExecutionManager from './MobileTradeExecutionManager';

/**
 * Mobile order drawer with snap handle + keyboard-safe scroll (desktop: pass-through).
 */
export function HardenedOrderDrawer(props) {
  const { isDesktop } = useResponsive();
  const panelRef = useRef(null);

  if (isDesktop) {
    return <ResponsiveDrawer {...props} />;
  }

  const { children, className, open, ...rest } = props;

  return (
    <>
      <ResponsiveDrawer {...rest} open={open} className={className}>
        <div ref={panelRef} className={cn('hard-order-surface flex flex-col h-full min-h-0', className)}>
          <div
            className="hard-order-snap-handle flex-shrink-0 lg:hidden"
            role="separator"
            aria-label="Drag to resize order panel"
          />
          <div className="flex-1 min-h-0 overflow-y-auto" data-scroll-region="y">
            {children}
          </div>
        </div>
      </ResponsiveDrawer>
      {open && <MobileTradeExecutionManager panelRef={panelRef} enabled={open} />}
    </>
  );
}

export default HardenedOrderDrawer;
