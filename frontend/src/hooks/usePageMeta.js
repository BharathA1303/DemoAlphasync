import { useEffect } from 'react';

/**
 * Sets the document title and meta description for the current page.
 * Helps search engines index SPA pages correctly.
 */
export default function usePageMeta(title, description) {
    useEffect(() => {
        const prev = document.title;
        document.title = title
            ? `${title} | AlphaSync`
            : "AlphaSync — India's #1 Paper Trading Platform";

        let metaDesc = document.querySelector('meta[name="description"]');
        const prevDesc = metaDesc?.getAttribute('content');
        if (description && metaDesc) {
            metaDesc.setAttribute('content', description);
        }

        return () => {
            document.title = prev;
            if (prevDesc && metaDesc) metaDesc.setAttribute('content', prevDesc);
        };
    }, [title, description]);
}
