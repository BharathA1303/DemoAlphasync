import { useRef, useEffect, memo } from 'react';
import { cn } from '../../utils/cn';

/**
 * ResponsiveDrawer — renders children inline on desktop, as a slide-over drawer on mobile/tablet.
 *
 * Props:
 *  - open: boolean — controls drawer visibility on compact screens
 *  - onClose: () => void
 *  - side: 'left' | 'right' — which edge the drawer slides from
 *  - isCompact: boolean — when true, renders as drawer; otherwise inline
 *  - width: string — drawer width when in overlay mode (default: 'w-[300px]')
 *  - className: applied to content wrapper
 *  - children: panel content
 */
function ResponsiveDrawer({
    open,
    onClose,
    side = 'left',
    isCompact = false,
    width = 'w-[300px]',
    className,
    children,
}) {
    const drawerRef = useRef(null);

    // Close on Escape
    useEffect(() => {
        if (!isCompact || !open) return;
        const handler = (e) => {
            if (e.key === 'Escape') onClose?.();
        };
        document.addEventListener('keydown', handler);
        return () => document.removeEventListener('keydown', handler);
    }, [isCompact, open, onClose]);

    // ── Inline mode (desktop) ──────────────────────────────────────────────
    if (!isCompact) {
        return (
            <div className={cn('flex flex-col h-full', className)}>
                {children}
            </div>
        );
    }

    // ── Drawer mode (tablet/mobile) ────────────────────────────────────────
    return (
        <>
            {/* Backdrop */}
            {open && (
                <div
                    className="fixed inset-0 bg-black/60 z-40 animate-fade-in"
                    onClick={onClose}
                    aria-hidden="true"
                />
            )}

            {/* Drawer panel */}
            <div
                ref={drawerRef}
                className={cn(
                    'fixed top-0 z-50 h-full flex flex-col',
                    'bg-surface-900/95 backdrop-blur-xl border-edge/10',
                    'transition-transform duration-300 ease-in-out',
                    width,
                    side === 'left'
                        ? cn('left-0 border-r', open ? 'translate-x-0' : '-translate-x-full')
                        : cn('right-0 border-l', open ? 'translate-x-0' : 'translate-x-full'),
                    className
                )}
            >
                {children}
            </div>
        </>
    );
}

export default memo(ResponsiveDrawer);
