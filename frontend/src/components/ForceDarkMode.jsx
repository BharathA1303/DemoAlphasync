import { useEffect } from 'react';
import { useTheme } from '../context/ThemeContext';

/**
 * Wrapper that forces dark mode while mounted.
 * Used for Landing, Login, Register, TradingModeSelect, BrokerSelect pages
 * which are always dark by design.
 */
export default function ForceDarkMode({ children }) {
    const { setForceDark } = useTheme();

    useEffect(() => {
        setForceDark(true);
        return () => setForceDark(false);
    }, [setForceDark]);

    return children;
}
