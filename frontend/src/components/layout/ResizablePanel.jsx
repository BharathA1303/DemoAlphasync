import { useState, useRef, useCallback, useEffect, memo } from 'react';
import { cn } from '../../utils/cn';

/**
 * ResizablePanel — wraps a child and adds a drag handle on one edge.
 *
 * Props:
 *  - side: 'left' | 'right' | 'top' | 'bottom' — which edge gets the handle
 *  - defaultSize: initial px size (width for left/right, height for top/bottom)
 *  - minSize / maxSize: clamp boundaries
 *  - onResize: (newSize: number) => void
 *  - className: applied to outer wrapper
 *  - children: panel content
 *
 * The component uses pointer events for smooth cross-browser dragging.
 */
function ResizablePanel({
    side = 'right',
    defaultSize = 260,
    minSize = 180,
    maxSize = 500,
    onResize,
    className,
    children,
    style,
}) {
    const [size, setSize] = useState(defaultSize);
    const dragging = useRef(false);
    const startPos = useRef(0);
    const startSize = useRef(0);

    const isHorizontal = side === 'left' || side === 'right';

    const handlePointerDown = useCallback((e) => {
        e.preventDefault();
        dragging.current = true;
        startPos.current = isHorizontal ? e.clientX : e.clientY;
        startSize.current = size;
        document.body.classList.add('select-none-on-drag');
        e.target.setPointerCapture(e.pointerId);
    }, [size, isHorizontal]);

    const handlePointerMove = useCallback((e) => {
        if (!dragging.current) return;
        const delta = isHorizontal
            ? e.clientX - startPos.current
            : e.clientY - startPos.current;

        // Handle grows toward chart: right handle → grows leftward (negative delta)
        const direction = (side === 'right' || side === 'bottom') ? -1 : 1;
        const newSize = Math.round(
            Math.min(maxSize, Math.max(minSize, startSize.current + delta * direction))
        );
        setSize(newSize);
        onResize?.(newSize);
    }, [isHorizontal, side, minSize, maxSize, onResize]);

    const handlePointerUp = useCallback((e) => {
        dragging.current = false;
        document.body.classList.remove('select-none-on-drag');
        if (e.target.hasPointerCapture?.(e.pointerId)) {
            e.target.releasePointerCapture(e.pointerId);
        }
    }, []);

    const handle = (
        <div
            className={cn(
                'resize-handle',
                isHorizontal ? 'resize-handle--horizontal' : 'resize-handle--vertical',
                dragging.current && 'active'
            )}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
        />
    );

    const sizeStyle = isHorizontal
        ? { width: size, minWidth: minSize, maxWidth: maxSize }
        : { height: size, minHeight: minSize, maxHeight: maxSize };

    return (
        <div
            className={cn('flex flex-shrink-0 overflow-hidden', isHorizontal ? 'flex-row' : 'flex-col', className)}
            style={{ ...sizeStyle, ...style }}
        >
            {(side === 'right' || side === 'bottom') && handle}
            <div className="flex-1 min-w-0 min-h-0 overflow-hidden flex flex-col">
                {children}
            </div>
            {(side === 'left' || side === 'top') && handle}
        </div>
    );
}

export default memo(ResizablePanel);
