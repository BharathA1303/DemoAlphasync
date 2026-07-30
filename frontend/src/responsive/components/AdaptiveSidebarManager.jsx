/**
 * Coordinates mobile sidebar scroll lock — existing Sidebar keeps its own overlay/drawer.
 */
import { useEffect } from 'react';
import { useResponsive } from '../hooks/useResponsive';

export function AdaptiveSidebarManager({
  children,
  sidebarCollapsed,
  sidebarSlot,
}) {
  const { isMobile } = useResponsive();
  const drawerOpen = isMobile && !sidebarCollapsed;

  useEffect(() => {
    if (!isMobile || typeof document === 'undefined') return;
    document.body.style.overflow = drawerOpen ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [drawerOpen, isMobile]);

  return (
    <>
      {sidebarSlot}
      {children}
    </>
  );
}

export default AdaptiveSidebarManager;
