import { useTheme } from '../../context/ThemeContext';
import { cn } from '../../utils/cn';

export default function AppLoader({ className = '' }) {
    const { theme } = useTheme() || {};
    const activeTheme = theme === 'dark' ? 'dark' : 'light';

    return (
        <div className={cn('app-loader-screen', activeTheme, className)} role="status" aria-label="Loading AlphaSync">
            <div className="app-loader-mark" aria-hidden="true">
                <span className="app-loader-ring" />
                <span className="app-loader-logo-shell">
                    <img src="/logo.svg" alt="" className="app-loader-logo logo-light-adapt" />
                </span>
            </div>
        </div>
    );
}
