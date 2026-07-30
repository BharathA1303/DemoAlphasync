import { useEffect, useRef } from 'react';

/**
 * Register global keyboard shortcuts.
 *
 * @param {Record<string, (e: KeyboardEvent) => void>} shortcuts
 *   Key: modifier+key string, e.g. 'alt+t', 'escape', 'b'
 *   Value: handler function
 * @param {boolean} [enabled=true] - Toggle shortcuts on/off
 *
 * @example
 * useKeyboardShortcuts({
 *   'alt+t': () => focusTerminal(),
 *   'escape': () => closeModal(),
 * });
 */
export function useKeyboardShortcuts(shortcuts, enabled = true) {
    const shortcutsRef = useRef(shortcuts);
    shortcutsRef.current = shortcuts;

    useEffect(() => {
        if (!enabled) return;

        const handler = (e) => {
            const parts = [];
            if (e.altKey) parts.push('alt');
            if (e.ctrlKey) parts.push('ctrl');
            if (e.shiftKey) parts.push('shift');
            parts.push(e.key.toLowerCase());

            const combo = parts.join('+');

            // Also allow single-key shortcuts when no modifier except for the key itself
            const singleKey = e.key.toLowerCase();

            const fn = shortcutsRef.current[combo] || shortcutsRef.current[singleKey];
            if (fn) {
                // Skip shortcuts if user is typing in an input/textarea/select
                const tag = document.activeElement?.tagName;
                if (!e.altKey && !e.ctrlKey && (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT')) return;
                fn(e);
            }
        };

        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [enabled]);
}
