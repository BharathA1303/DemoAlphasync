import { useState, useCallback, useRef, useEffect } from 'react';
import api from '../services/api';

/**
 * Generic debounced search hook.
 * Used by Navbar search and Watchlist search to eliminate duplicate logic.
 *
 * @param {string}  endpoint   API path that accepts `?q=` query param
 * @param {string}  resultKey  Key in response JSON to extract results array
 * @param {number}  delay      Debounce delay in ms (default 300)
 */
export function useSearch(endpoint = '/market/search', resultKey = 'results', delay = 300) {
    const [query, setQuery] = useState('');
    const [debouncedQuery, setDebouncedQuery] = useState('');
    const [results, setResults] = useState([]);
    const [isSearching, setIsSearching] = useState(false);
    const abortRef = useRef(null);

    // Debounce the query string into debouncedQuery
    useEffect(() => {
        const timer = setTimeout(() => setDebouncedQuery(query), delay);
        return () => clearTimeout(timer);
    }, [query, delay]);

    useEffect(() => {
        if (!debouncedQuery || debouncedQuery.length < 2) {
            setResults([]);
            return;
        }

        let cancelled = false;

        (async () => {
            // Cancel previous in-flight request
            if (abortRef.current) abortRef.current.abort();
            const controller = new AbortController();
            abortRef.current = controller;

            setIsSearching(true);
            try {
                const res = await api.get(`${endpoint}?q=${encodeURIComponent(debouncedQuery)}`, {
                    signal: controller.signal,
                });
                if (!cancelled) {
                    setResults(res.data[resultKey] || res.data || []);
                }
            } catch (err) {
                if (!cancelled && err.name !== 'CanceledError' && err.name !== 'AbortError') {
                    setResults([]);
                }
            } finally {
                if (!cancelled) setIsSearching(false);
            }
        })();

        return () => { cancelled = true; };
    }, [debouncedQuery, endpoint, resultKey]);

    const clear = useCallback(() => {
        setQuery('');
        setResults([]);
    }, []);

    return { query, setQuery, results, isSearching, clear };
}
