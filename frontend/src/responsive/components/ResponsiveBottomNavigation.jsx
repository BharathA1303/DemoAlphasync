import { NavLink, useLocation } from 'react-router-dom';
import { LayoutDashboard, ChartCandlestick, ClipboardList, Briefcase, Menu } from 'lucide-react';
import { MOBILE_NAV_ROUTES } from '../constants/breakpoints';
import { useResponsive } from '../hooks/useResponsive';
import { cn } from '../../utils/cn';

const ICONS = {
  dashboard: LayoutDashboard,
  terminal: ChartCandlestick,
  orders: ClipboardList,
  portfolio: Briefcase,
  menu: Menu,
};

export function ResponsiveBottomNavigation() {
  const { isDesktop } = useResponsive();
  const location = useLocation();

  if (isDesktop) return null;

  return (
    <nav
      className="responsive-bottom-nav fixed bottom-0 left-0 right-0 z-[40] lg:hidden"
      aria-label="Primary navigation"
    >
      <div className="responsive-bottom-nav-inner flex items-stretch justify-around border-t border-edge/10 bg-surface-900/90 backdrop-blur-xl safe-area-bottom-pad">
        {MOBILE_NAV_ROUTES.map((item) => {
          const Icon = ICONS[item.key] || Menu;
          const isActive =
            location.pathname === item.path ||
            (item.path === '/terminal' &&
              (location.pathname.startsWith('/futures') ||
                location.pathname.startsWith('/options')));
          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={cn(
                'flex flex-1 flex-col items-center justify-center gap-0.5 py-2 min-h-[52px] min-w-[44px] transition-colors',
                isActive ? 'text-primary-600' : 'text-gray-500 hover:text-heading',
              )}
            >
              <Icon className="w-5 h-5" strokeWidth={isActive ? 2.5 : 2} />
              <span className="text-[10px] font-medium">{item.label}</span>
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}

export default ResponsiveBottomNavigation;
