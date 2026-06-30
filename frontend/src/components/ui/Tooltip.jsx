import { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../../utils/cn';

/**
 * Lightweight tooltip wrapping any trigger element.
 * Renders the popup via a portal so it is never clipped by parent overflow.
 *
 * @param {{
 *   content: string|ReactNode,
 *   position?: 'top'|'bottom'|'left'|'right',
 *   delay?: number,
 *   children: ReactNode,
 * }} props
 */
export default function Tooltip({ content, position = 'top', delay = 400, children, className }) {
    const [visible, setVisible] = useState(false);
    const [coords, setCoords] = useState({ top: 0, left: 0 });
    const timerRef = useRef(null);
    const triggerRef = useRef(null);

    const calcPosition = useCallback(() => {
        if (!triggerRef.current) return;
        const rect = triggerRef.current.getBoundingClientRect();
        const gap = 8;
        let top, left;

        switch (position) {
            case 'right':
                top = rect.top + rect.height / 2;
                left = rect.right + gap;
                break;
            case 'left':
                top = rect.top + rect.height / 2;
                left = rect.left - gap;
                break;
            case 'bottom':
                top = rect.bottom + gap;
                left = rect.left + rect.width / 2;
                break;
            case 'top':
            default:
                top = rect.top - gap;
                left = rect.left + rect.width / 2;
                break;
        }
        setCoords({ top, left });
    }, [position]);

    const show = () => {
        timerRef.current = setTimeout(() => {
            calcPosition();
            setVisible(true);
        }, delay);
    };
    const hide = () => {
        clearTimeout(timerRef.current);
        setVisible(false);
    };

    useEffect(() => () => clearTimeout(timerRef.current), []);

    const transformStyle = {
        top: 'translateX(-50%) translateY(-100%)',
        bottom: 'translateX(-50%)',
        left: 'translateX(-100%) translateY(-50%)',
        right: 'translateY(-50%)',
    };

    return (
        <div className="relative inline-flex" ref={triggerRef} onMouseEnter={show} onMouseLeave={hide}>
            {children}
            {visible && content && createPortal(
                <div
                    className={cn(
                        'fixed z-[9999] px-2.5 py-1.5 text-xs font-medium text-white',
                        'bg-slate-800 border border-slate-700 rounded-lg shadow-lg whitespace-nowrap',
                        'pointer-events-none animate-slide-in',
                        className
                    )}
                    style={{
                        top: coords.top,
                        left: coords.left,
                        transform: transformStyle[position] || transformStyle.top,
                    }}
                >
                    {content}
                </div>,
                document.body
            )}
        </div>
    );
}
