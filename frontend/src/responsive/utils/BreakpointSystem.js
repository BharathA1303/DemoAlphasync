import { BREAKPOINTS, HEIGHT_BREAKPOINTS, DEVICE_CATEGORY, LAYOUT_MODE } from '../constants/breakpoints';

export function getBreakpointKey(width) {
  if (width >= BREAKPOINTS['4xl']) return '4xl';
  if (width >= BREAKPOINTS['3xl']) return '3xl';
  if (width >= BREAKPOINTS['2xl']) return '2xl';
  if (width >= BREAKPOINTS.xl) return 'xl';
  if (width >= BREAKPOINTS.lg) return 'lg';
  if (width >= BREAKPOINTS.md) return 'md';
  if (width >= BREAKPOINTS.sm) return 'sm';
  if (width >= BREAKPOINTS.xs) return 'xs';
  return 'base';
}

export function getLayoutMode(width) {
  if (width >= BREAKPOINTS.lg) return LAYOUT_MODE.DESKTOP;
  if (width >= BREAKPOINTS.md) return LAYOUT_MODE.TABLET;
  return LAYOUT_MODE.MOBILE;
}

export function getHeightTier(height) {
  if (height >= HEIGHT_BREAKPOINTS.tall) return 'tall';
  if (height >= HEIGHT_BREAKPOINTS.medium) return 'medium';
  if (height >= HEIGHT_BREAKPOINTS.short) return 'short';
  return 'compact';
}

export function getDeviceCategory(width, height, { foldable = false } = {}) {
  if (foldable && width >= BREAKPOINTS.md && width < BREAKPOINTS.lg) {
    return DEVICE_CATEGORY.FOLDABLE;
  }
  const landscape = width > height;
  if (width < BREAKPOINTS.sm) return DEVICE_CATEGORY.PHONE_SMALL;
  if (width < BREAKPOINTS.md) return width >= 414 ? DEVICE_CATEGORY.PHONE_LARGE : DEVICE_CATEGORY.PHONE;
  if (width < BREAKPOINTS.lg) {
    return landscape ? DEVICE_CATEGORY.TABLET_LANDSCAPE : DEVICE_CATEGORY.TABLET_PORTRAIT;
  }
  if (width < BREAKPOINTS.xl) return DEVICE_CATEGORY.LAPTOP_SMALL;
  if (width < BREAKPOINTS['3xl']) return DEVICE_CATEGORY.DESKTOP;
  if (width < BREAKPOINTS['4xl']) return DEVICE_CATEGORY.DESKTOP_LARGE;
  return DEVICE_CATEGORY.ULTRA_WIDE;
}

export function matchesBreakpoint(width, key) {
  const min = BREAKPOINTS[key];
  if (min == null) return true;
  const keys = Object.keys(BREAKPOINTS);
  const idx = keys.indexOf(key);
  const nextKey = keys[idx + 1];
  const max = nextKey ? BREAKPOINTS[nextKey] - 1 : Infinity;
  return width >= min && width <= max;
}

export function isDesktopWidth(width) {
  return width >= BREAKPOINTS.lg;
}

export function isTabletWidth(width) {
  return width >= BREAKPOINTS.md && width < BREAKPOINTS.lg;
}

export function isMobileWidth(width) {
  return width < BREAKPOINTS.md;
}
