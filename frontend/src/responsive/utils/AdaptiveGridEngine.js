import { LAYOUT_MODE } from '../constants/breakpoints';

/**
 * Returns CSS grid template classes for page layouts without modifying desktop grids.
 */
export function getAdaptiveGridClass(layoutMode, variant = 'default') {
  if (layoutMode === LAYOUT_MODE.DESKTOP) {
    return 'responsive-grid-desktop-pass';
  }
  if (layoutMode === LAYOUT_MODE.TABLET) {
    const tablet = {
      default: 'responsive-grid-tablet',
      market: 'responsive-grid-tablet-market',
      portfolio: 'responsive-grid-tablet-portfolio',
    };
    return tablet[variant] || tablet.default;
  }
  const mobile = {
    default: 'responsive-grid-mobile',
    market: 'responsive-grid-mobile-stack',
    portfolio: 'responsive-grid-mobile-stack',
    leaderboard: 'responsive-grid-mobile-stack',
  };
  return mobile[variant] || mobile.default;
}

export function getColumnCount(layoutMode, desktopCols = 4) {
  if (layoutMode === LAYOUT_MODE.DESKTOP) return desktopCols;
  if (layoutMode === LAYOUT_MODE.TABLET) return Math.min(2, desktopCols);
  return 1;
}
