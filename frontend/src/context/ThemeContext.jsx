import { createContext, useContext, useState, useEffect, useCallback } from 'react';

const ThemeContext = createContext(null);
const THEME_KEY = 'alphasync_theme';
const PREFS_KEY = 'alphasync_ui_prefs';

const DEFAULT_PREFS = {
    accentColor: 'cyan',       // cyan | blue | green | purple | orange | rose
    fontSize: 'medium',        // small | medium | large
    chartStyle: 'candles',     // candles | line | area
    layoutDensity: 'comfortable', // compact | comfortable | spacious
    animationsEnabled: true,
    showPnlPercent: true,
    showPnlValue: true,
    compactNumbers: false,     // e.g. 1.2L instead of 1,20,000
    defaultOrderType: 'MARKET', // MARKET | LIMIT
    confirmBeforeOrder: true,
};

function loadPrefs() {
    try {
        const saved = localStorage.getItem(PREFS_KEY);
        if (saved) return { ...DEFAULT_PREFS, ...JSON.parse(saved) };
    } catch { /* ignore */ }
    return { ...DEFAULT_PREFS };
}

export function ThemeProvider({ children }) {
    const [theme, setTheme] = useState(() => {
        const saved = localStorage.getItem(THEME_KEY);
        return saved === 'dark' ? 'dark' : 'light';
    });

    const [prefs, setPrefsState] = useState(loadPrefs);

    // Persist theme preference only — do NOT apply class to document root.
    // Theme class is applied by AppShell so only authenticated dashboard
    // pages are affected. Public pages (landing, login, etc.) stay light.
    useEffect(() => {
        localStorage.setItem(THEME_KEY, theme);
    }, [theme]);

    useEffect(() => {
        localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    }, [prefs]);

    const setForceDark = (enabled) => {
        setTheme(enabled ? 'dark' : 'light');
    };

    const toggleTheme = () => {
        setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'));
    };

    const updatePrefs = useCallback((patch) => {
        setPrefsState((prev) => ({ ...prev, ...patch }));
    }, []);

    const resetPrefs = useCallback(() => {
        setPrefsState({ ...DEFAULT_PREFS });
    }, []);

    return (
        <ThemeContext.Provider value={{
            theme, userTheme: theme, toggleTheme, setForceDark, setTheme,
            prefs, updatePrefs, resetPrefs, DEFAULT_PREFS,
        }}>
            {children}
        </ThemeContext.Provider>
    );
}

export const useTheme = () => useContext(ThemeContext);
