import { useState, useCallback, useRef, useEffect } from 'react';

/**
 * Reusable drag-position hook with localStorage persistence.
 * Extracted from StrategyDock — usable by any floating panel.
 *
 * @param {string} storageKey   localStorage key for position persistence
 * @param {{ x: number, y: number }} defaultPos  Initial position
 */
export function useDraggable(storageKey, defaultPos = { x: 100, y: 100 }) {
    const [position, setPosition] = useState(() => {
        try {
            const saved = localStorage.getItem(storageKey);
            if (saved) return JSON.parse(saved);
        } catch { /* ignore */ }
        return defaultPos;
    });

    const dragRef = useRef(null);
    const offsetRef = useRef({ x: 0, y: 0 });
    const draggingRef = useRef(false);

    const onMouseDown = useCallback((e) => {
        // Only left-click
        if (e.button !== 0) return;
        draggingRef.current = true;
        offsetRef.current = {
            x: e.clientX - position.x,
            y: e.clientY - position.y,
        };
        e.preventDefault();
    }, [position]);

    useEffect(() => {
        const onMouseMove = (e) => {
            if (!draggingRef.current) return;
            const newPos = {
                x: e.clientX - offsetRef.current.x,
                y: e.clientY - offsetRef.current.y,
            };
            setPosition(newPos);
        };

        const onMouseUp = () => {
            if (draggingRef.current) {
                draggingRef.current = false;
                // Persist final position
                try {
                    localStorage.setItem(storageKey, JSON.stringify(position));
                } catch { /* ignore */ }
            }
        };

        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);

        return () => {
            window.removeEventListener('mousemove', onMouseMove);
            window.removeEventListener('mouseup', onMouseUp);
        };
    }, [storageKey, position]);

    return { position, onMouseDown, dragRef };
}
