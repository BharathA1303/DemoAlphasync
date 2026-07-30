import { useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../../utils/cn';
import { useTheme } from '../../context/ThemeContext';

const sizeClasses = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    lg: 'max-w-lg',
    xl: 'max-w-xl',
    fullscreen: 'w-screen h-screen max-w-none rounded-none m-0',
};

/**
 * Portal-based, focus-trapped, ESC-to-close modal.
 *
 * @param {{
 *   isOpen: boolean,
 *   onClose: () => void,
 *   title?: string,
 *   size?: 'sm'|'md'|'lg'|'xl'|'fullscreen',
 *   hideCloseButton?: boolean,
 *   children: ReactNode,
 * }} props
 */
export default function Modal({
    isOpen,
    onClose,
    title,
    size = 'md',
    hideCloseButton = false,
    className,
    children,
}) {
    const overlayRef = useRef(null);
    const contentRef = useRef(null);
    const { theme, prefs } = useTheme();

    // ESC to close
    useEffect(() => {
        if (!isOpen) return;
        const handler = (e) => { if (e.key === 'Escape') onClose(); };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [isOpen, onClose]);

    // Focus trap
    useEffect(() => {
        if (!isOpen || !contentRef.current) return;
        const focusable = contentRef.current.querySelectorAll(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length) focusable[0].focus();
    }, [isOpen]);

    // Prevent body scroll
    useEffect(() => {
        document.body.style.overflow = isOpen ? 'hidden' : '';
        return () => { document.body.style.overflow = ''; };
    }, [isOpen]);

    const handleOverlayClick = useCallback((e) => {
        if (e.target === overlayRef.current) onClose();
    }, [onClose]);

    if (!isOpen) return null;

    return createPortal(
        <div
            ref={overlayRef}
            onClick={handleOverlayClick}
            className={cn(
                'fixed inset-0 z-50 flex items-center justify-center p-4',
                'bg-black/70 backdrop-blur-sm animate-fade-in',
                theme,
                `accent-${prefs?.accentColor || 'cyan'}`,
            )}
            role="dialog"
            aria-modal="true"
        >
            <div
                ref={contentRef}
                className={cn(
                    'w-full bg-surface-800 border border-edge/10 rounded-xl shadow-panel',
                    'animate-slide-in',
                    sizeClasses[size],
                    className
                )}
            >
                {/* Header */}
                {(title || !hideCloseButton) && (
                    <div className="flex items-center justify-between px-6 py-4 border-b border-edge/5">
                        {title && <h3 className="text-base font-semibold text-heading">{title}</h3>}
                        {!hideCloseButton && (
                            <button
                                onClick={onClose}
                                className="ml-auto text-gray-400 hover:text-heading transition-colors p-1 rounded hover:bg-overlay/5"
                                aria-label="Close modal"
                            >
                                ✕
                            </button>
                        )}
                    </div>
                )}

                {/* Content */}
                <div className="!p-0">{children}</div>
            </div>
        </div>,
        document.body
    );
}
