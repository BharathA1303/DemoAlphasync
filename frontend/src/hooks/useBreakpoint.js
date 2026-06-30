import { useState, useEffect, useCallback, useMemo } from 'react';

/**
 * Breakpoint thresholds matching tailwind.config.js screens.
 * Desktop ≥ 1400, Laptop 1024-1399, Tablet 768-1023, Mobile < 768.
 */
export const BREAKPOINTS = {
    xs: 480,
    sm: 640,
    md: 768,
    lg: 1024,
    xl: 1400,
    '2xl': 1920,
};

/**
 * Named layout tiers for trading terminal.
 */
export const LAYOUT_TIER = {
    MOBILE: 'mobile',    // < 768
    TABLET: 'tablet',    // 768–1023
    LAPTOP: 'laptop',    // 1024–1399
    DESKTOP: 'desktop',  // ≥ 1400
};

function getTier(width) {
    if (width < BREAKPOINTS.md) return LAYOUT_TIER.MOBILE;
    if (width < BREAKPOINTS.lg) return LAYOUT_TIER.TABLET;
    if (width < BREAKPOINTS.xl) return LAYOUT_TIER.LAPTOP;
    return LAYOUT_TIER.DESKTOP;
}

/**
 * useBreakpoint — returns the current layout tier + convenience booleans.
 *
 * Usage:
 *   const { tier, isMobile, isTablet, isDesktop, width } = useBreakpoint();
 *
 * Debounced via ResizeObserver (no excessive re-renders).
 */
export function useBreakpoint() {
    const [width, setWidth] = useState(() =>
        typeof window !== 'undefined' ? window.innerWidth : 1400
    );

    useEffect(() => {
        let raf;
        const handleResize = () => {
            if (raf) cancelAnimationFrame(raf);
            raf = requestAnimationFrame(() => {
                setWidth(window.innerWidth);
            });
        };

        window.addEventListener('resize', handleResize, { passive: true });
        return () => {
            window.removeEventListener('resize', handleResize);
            if (raf) cancelAnimationFrame(raf);
        };
    }, []);

    const tier = useMemo(() => getTier(width), [width]);

    return useMemo(() => ({
        width,
        tier,
        isMobile: tier === LAYOUT_TIER.MOBILE,
        isTablet: tier === LAYOUT_TIER.TABLET,
        isLaptop: tier === LAYOUT_TIER.LAPTOP,
        isDesktop: tier === LAYOUT_TIER.DESKTOP,
        isCompact: tier === LAYOUT_TIER.MOBILE || tier === LAYOUT_TIER.TABLET,
        isWide: tier === LAYOUT_TIER.DESKTOP || tier === LAYOUT_TIER.LAPTOP,
    }), [width, tier]);
}

/**
 * useMediaQuery — match a single CSS media query string.
 */
export function useMediaQuery(query) {
    const [matches, setMatches] = useState(() => {
        if (typeof window === 'undefined') return false;
        return window.matchMedia(query).matches;
    });

    useEffect(() => {
        const mql = window.matchMedia(query);
        const handler = (e) => setMatches(e.matches);
        mql.addEventListener('change', handler);
        setMatches(mql.matches);
        return () => mql.removeEventListener('change', handler);
    }, [query]);

    return matches;
}
