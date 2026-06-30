import { useSyncExternalStore } from 'react';

/**
 * SSR-safe media query subscription — stable on first client paint (unlike context lag after login).
 */
export function useMediaQuery(query, defaultValue = false) {
  return useSyncExternalStore(
    (onStoreChange) => {
      if (typeof window === 'undefined') return () => {};
      const mql = window.matchMedia(query);
      const handler = () => onStoreChange();
      if (mql.addEventListener) mql.addEventListener('change', handler);
      else mql.addListener(handler);
      return () => {
        if (mql.removeEventListener) mql.removeEventListener('change', handler);
        else mql.removeListener(handler);
      };
    },
    () => {
      if (typeof window === 'undefined') return defaultValue;
      return window.matchMedia(query).matches;
    },
    () => defaultValue,
  );
}

/** lg breakpoint — matches Tailwind / responsive layer desktop layout */
export function useIsLgUp(defaultValue = true) {
  return useMediaQuery('(min-width: 1024px)', defaultValue);
}

export default useMediaQuery;
