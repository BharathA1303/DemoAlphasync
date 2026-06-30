import { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { useResponsive } from '../hooks/useResponsive';
import { cn } from '../../utils/cn';

/**
 * Mobile-optimized modal / bottom sheet — use as optional wrapper for new flows.
 */
export function ResponsiveModalSystem({
  isOpen,
  onClose,
  title,
  children,
  size = 'md',
}) {
  const { isMobile } = useResponsive();

  useEffect(() => {
    if (!isOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [isOpen]);

  if (!isOpen) return null;

  const content = (
    <div className="responsive-modal-root fixed inset-0 z-[100] flex items-end sm:items-center justify-center p-0 sm:p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        aria-label="Close"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? 'responsive-modal-title' : undefined}
        className={cn(
          'responsive-modal-panel relative w-full bg-surface-900 border border-edge/10 shadow-panel',
          isMobile
            ? 'responsive-modal-sheet rounded-t-2xl max-h-[92vh] safe-area-bottom-pad'
            : 'rounded-xl max-h-[85vh]',
          size === 'sm' && 'sm:max-w-md',
          size === 'md' && 'sm:max-w-lg',
          size === 'lg' && 'sm:max-w-2xl',
          'animate-slide-up sm:animate-scale-in',
        )}
      >
        {title && (
          <div className="flex items-center justify-between px-4 py-3 border-b border-edge/10">
            <h2 id="responsive-modal-title" className="text-sm font-semibold text-heading">
              {title}
            </h2>
            <button type="button" onClick={onClose} className="text-gray-500 hover:text-heading p-2 min-h-[44px] min-w-[44px]">
              ×
            </button>
          </div>
        )}
        <div className="overflow-y-auto overscroll-contain max-h-[calc(92vh-56px)] p-4">
          {children}
        </div>
      </div>
    </div>
  );

  const root = document.getElementById('portal-root') || document.body;
  return createPortal(content, root);
}

export default ResponsiveModalSystem;
