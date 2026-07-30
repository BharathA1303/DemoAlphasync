// AppShell.jsx - Main authenticated layout with sidebar, navbar, and market ticker
import { useState, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import Navbar from './Navbar';
import MarketTickerBar from './MarketTickerBar';
import FeedbackWidget from '../FeedbackWidget';
import { useWebSocket } from '../../hooks/useWebSocket';
import { useLivePortfolio } from '../../hooks/useLivePortfolio';
import { useTheme } from '../../context/ThemeContext';
import { cn } from '../../utils/cn';
import { LS_SIDEBAR } from '../../utils/constants';
import { AdaptiveSidebarManager } from '../../responsive';
import { HardenedResponsiveShell } from '../../responsive/hardening';

// Root font-size for rem-based scaling (Tailwind uses rem for text-sm, text-xs, etc.)
const FONT_SIZE_PX = { small: '14px', medium: '16px', large: '18px' };

/**
 * Root authenticated shell: sidebar + navbar + market ticker + page content.
 *
 * Layout grid (desktop):
 *   [Fixed Sidebar 240/72px] [Main: Navbar 56px / TickerBar 28px / Page]
 *
 * Terminal and AI Mentor routes: main area is overflow-hidden (internal scroll only)
 * Other routes: main area is overflow-y-auto
 * Mobile: sidebar becomes a full-width overlay drawer; main content stays at 0 margin.
 */
export default function AppShell() {
    const location = useLocation();
    const { theme, prefs } = useTheme();

    // Full-viewport pages manage their own internal scroll (no document scroll in <main>)
    const isFullViewportPage =
        location.pathname.startsWith('/terminal') ||
        location.pathname.startsWith('/mentor');

    // ── Apply font size on <html> so all rem-based sizes scale ──────────────
    useEffect(() => {
        const size = FONT_SIZE_PX[prefs?.fontSize] || '16px';
        document.documentElement.style.fontSize = size;
        return () => { document.documentElement.style.fontSize = ''; };
    }, [prefs?.fontSize]);

    // ── Mount WebSocket — always connected when authenticated ──────────────
    useWebSocket();

    // ── Global portfolio polling — keeps P&L updated even when WS is down ───
    useLivePortfolio();

    // ── Sidebar state — default collapsed, restored from localStorage ───────
    const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
        try {
            const saved = localStorage.getItem(LS_SIDEBAR);
            if (saved === 'open') return false;
            if (saved === 'closed') return true;
        } catch {
            // ignore storage errors and default to collapsed
        }
        return true;
    });

    const toggleSidebar = () => setSidebarCollapsed((prev) => !prev);

    useEffect(() => {
        try {
            localStorage.setItem(LS_SIDEBAR, sidebarCollapsed ? 'closed' : 'open');
        } catch {
            // ignore storage errors
        }
    }, [sidebarCollapsed]);

    // Mobile: keep drawer closed by default; close after route change
    useEffect(() => {
        if (typeof window !== 'undefined' && window.innerWidth < 1024) {
            setSidebarCollapsed(true);
        }
    }, [location.pathname]);

    // Mobile: start with menu closed (full content visible)
    useEffect(() => {
        if (typeof window !== 'undefined' && window.innerWidth < 1024) {
            setSidebarCollapsed(true);
        }
    }, []);

    return (
        <div className={cn(
            'h-screen bg-[var(--bg-base)] flex overflow-hidden',
            theme,
            `accent-${prefs?.accentColor || 'cyan'}`,
            prefs?.animationsEnabled === false && 'ui-no-animations',
        )}>
            <AdaptiveSidebarManager
                sidebarCollapsed={sidebarCollapsed}
                sidebarSlot={(
                    <Sidebar
                        collapsed={sidebarCollapsed}
                        onToggle={toggleSidebar}
                    />
                )}
            >
                <div
                    className={cn(
                        'flex flex-col flex-1 min-w-0 min-h-0 overflow-hidden w-full',
                        sidebarCollapsed ? 'lg:ml-[72px]' : 'lg:ml-[240px]'
                    )}
                >
                    <Navbar onMenuToggle={toggleSidebar} />
                    <MarketTickerBar />

                    <HardenedResponsiveShell isFullViewportPage={isFullViewportPage}>
                        <main className={cn(
                            'flex-1 min-h-0',
                            isFullViewportPage ? 'overflow-hidden' : 'overflow-y-auto'
                        )}>
                            <Outlet />
                        </main>
                    </HardenedResponsiveShell>
                </div>
            </AdaptiveSidebarManager>
            <div id="portal-root" />
            <FeedbackWidget />
        </div>
    );
}
