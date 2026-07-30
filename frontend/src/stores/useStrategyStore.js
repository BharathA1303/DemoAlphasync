import { create } from 'zustand';

/**
 * Strategy store — owns enabled-strategies map and cached engine results.
 * Replaces scattered localStorage reads in StrategyDock.
 */

const STORAGE_KEY = 'strategy_enabled';

/** Load persisted enabled map or fall back to defaults. */
function loadEnabled() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) return JSON.parse(raw);
    } catch { /* ignore */ }
    return null;
}

export const useStrategyStore = create((set, get) => ({
    /** @type {Record<string, boolean>} strategyId → enabled */
    enabledMap: loadEnabled() || {},

    /** @type {object|null} Latest engine output { overall, results } */
    engineOutput: null,

    // ─── Actions ──────────────────────────────────────────────────────────────

    /** Toggle a strategy on/off and persist. */
    toggleStrategy: (id) => {
        set((s) => {
            const next = { ...s.enabledMap, [id]: !s.enabledMap[id] };
            localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
            return { enabledMap: next };
        });
    },

    /** Initialise enabled map from strategy list if empty. */
    initDefaults: (strategies) => {
        const current = get().enabledMap;
        if (Object.keys(current).length > 0) return;
        const defaults = {};
        strategies.forEach((s) => { defaults[s.id] = true; });
        localStorage.setItem(STORAGE_KEY, JSON.stringify(defaults));
        set({ enabledMap: defaults });
    },

    /** Cache the latest engine run result. */
    setEngineOutput: (output) => set({ engineOutput: output }),
}));
