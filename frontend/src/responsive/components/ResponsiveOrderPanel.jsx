import { useResponsive } from '../hooks/useResponsive';
import { cn } from '../../utils/cn';

/**
 * Wraps order panels — mobile: bottom sheet / full-screen drawer styling via CSS.
 * Desktop: pass-through.
 */
export function ResponsiveOrderPanel({ children, className, open = true, onClose }) {
  const { isDesktop, mobileTradingTab } = useResponsive();

  if (isDesktop) {
    return <div className={cn('responsive-order-desktop', className)}>{children}</div>;
  }

  const show = mobileTradingTab === 'order' || open;

  return (
    <>
      {show && onClose && (
        <button
          type="button"
          className="responsive-order-backdrop fixed inset-0 z-[45] bg-black/40 backdrop-blur-sm lg:hidden"
          aria-label="Close order panel"
          onClick={onClose}
        />
      )}
      <div
        className={cn(
          'responsive-order-mobile',
          show ? 'responsive-order-sheet--open' : 'responsive-order-sheet--closed',
          className,
        )}
      >
        <div className="responsive-order-sheet-handle lg:hidden" aria-hidden />
        {children}
      </div>
    </>
  );
}

export default ResponsiveOrderPanel;
