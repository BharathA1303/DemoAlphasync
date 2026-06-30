import { memo, useState, useRef, useCallback } from 'react';
import { cn } from '../utils/cn';

/**
 * PanelContainer — universal wrapper for every panel in the app.
 *
 * Features:
 *   - Consistent header with title, optional icon, optional action buttons
 *   - Loading skeleton & error fallback states
 *   - Scrollable body
 *   - Optional resize handle (vertical resize)
 *   - Floating variant for popup panels
 *
 * @param {{
 *   title: string,
 *   icon?: React.ReactNode,
 *   actions?: React.ReactNode,
 *   children: React.ReactNode,
 *   isLoading?: boolean,
 *   error?: string|null,
 *   className?: string,
 *   bodyClassName?: string,
 *   headerClassName?: string,
 *   floating?: boolean,
 *   resizable?: boolean,
 *   minHeight?: number,
 *   maxHeight?: number,
 *   noPadding?: boolean,
 *   noScroll?: boolean,
 *   onClose?: () => void,
 *   dragHandleProps?: object,
 * }} props
 */
function PanelContainer({
    title,
    icon,
    actions,
    children,
    isLoading = false,
    error = null,
    className,
    bodyClassName,
    headerClassName,
    floating = false,
    resizable = false,
    minHeight = 120,
    maxHeight = 800,
    noPadding = false,
    noScroll = false,
    onClose,
    dragHandleProps,
}) {
    // ── Resize state ──────────────────────────────────────────────────────────
    const [height, setHeight] = useState(null);
    const resizeRef = useRef(null);

    const onResizeStart = useCallback((e) => {
        e.preventDefault();
        const startY = e.clientY;
        const startH = resizeRef.current?.parentElement?.offsetHeight ?? 200;

        const onMove = (ev) => {
            const newH = Math.min(maxHeight, Math.max(minHeight, startH + ev.clientY - startY));
            setHeight(newH);
        };
        const onUp = () => {
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseup', onUp);
        };
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
    }, [minHeight, maxHeight]);

    // ── Error state ───────────────────────────────────────────────────────────
    if (error) {
        return (
            <div className={cn('flex flex-col rounded-xl border border-red-500/20 bg-surface-900/60', className)}>
                <PanelHeader title={title} icon={icon} actions={actions} className={headerClassName} onClose={onClose} dragHandleProps={dragHandleProps} />
                <div className="flex-1 flex items-center justify-center p-6 text-sm text-red-500">
                    {error}
                </div>
            </div>
        );
    }

    return (
        <div
            className={cn(
                'flex flex-col',
                floating
                    ? 'rounded-xl border border-edge/10 bg-surface-900/95 backdrop-blur-xl shadow-2xl'
                    : 'bg-surface-900/30',
                className
            )}
            style={height ? { height } : undefined}
        >
            {title && (
                <PanelHeader
                    title={title}
                    icon={icon}
                    actions={actions}
                    className={headerClassName}
                    onClose={onClose}
                    dragHandleProps={dragHandleProps}
                />
            )}

            {/* Body */}
            <div className={cn(
                'flex-1 min-h-0',
                !noScroll && 'overflow-y-auto',
                !noPadding && 'px-3 py-2',
                bodyClassName,
            )}>
                {isLoading ? <PanelSkeleton /> : children}
            </div>

            {/* Resize handle */}
            {resizable && (
                <div
                    ref={resizeRef}
                    className="h-1.5 cursor-row-resize flex items-center justify-center group"
                    onMouseDown={onResizeStart}
                >
                    <div className="w-8 h-0.5 rounded-full bg-edge/10 group-hover:bg-edge/30 transition-colors" />
                </div>
            )}
        </div>
    );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function PanelHeader({ title, icon, actions, className, onClose, dragHandleProps }) {
    return (
        <div
            className={cn(
                'flex items-center gap-2 px-3 py-2 border-b border-edge/5 flex-shrink-0',
                dragHandleProps && 'cursor-move select-none',
                className,
            )}
            {...(dragHandleProps || {})}
        >
            {icon && <span className="text-gray-500">{icon}</span>}
            <h3 className="section-title text-xs flex-1">
                {title}
            </h3>
            {actions}
            {onClose && (
                <button
                    onClick={onClose}
                    className="text-gray-600 hover:text-gray-700 transition-colors p-0.5 -mr-1"
                    aria-label="Close panel"
                >
                    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
                    </svg>
                </button>
            )}
        </div>
    );
}

function PanelSkeleton() {
    return (
        <div className="space-y-2 p-2 animate-pulse">
            {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-4 bg-surface-700 rounded w-full" style={{ width: `${85 - i * 10}%` }} />
            ))}
        </div>
    );
}

export default memo(PanelContainer);
