/**
 * Enterprise breakpoint system — CSS + JS aligned.
 * Desktop (lg+) layouts remain unchanged; smaller tiers activate responsive layer.
 */

export const BREAKPOINTS = {
  xs: 320,
  sm: 480,
  md: 768,
  lg: 1024,
  xl: 1280,
  '2xl': 1536,
  '3xl': 1920,
  '4xl': 2560,
};

export const HEIGHT_BREAKPOINTS = {
  short: 600,
  medium: 800,
  tall: 1000,
};

export const DEVICE_CATEGORY = {
  PHONE_SMALL: 'phone_small',
  PHONE: 'phone',
  PHONE_LARGE: 'phone_large',
  FOLDABLE: 'foldable',
  TABLET_PORTRAIT: 'tablet_portrait',
  TABLET_LANDSCAPE: 'tablet_landscape',
  LAPTOP_SMALL: 'laptop_small',
  DESKTOP: 'desktop',
  DESKTOP_LARGE: 'desktop_large',
  ULTRA_WIDE: 'ultra_wide',
};

export const LAYOUT_MODE = {
  DESKTOP: 'desktop',
  TABLET: 'tablet',
  MOBILE: 'mobile',
};

/** Routes that use trading-terminal responsive shell */
export const TRADING_ROUTES = ['/terminal', '/futures', '/options'];

/** Mobile bottom nav primary routes */
export const MOBILE_NAV_ROUTES = [
  { path: '/dashboard', label: 'Home', key: 'dashboard' },
  { path: '/terminal', label: 'Trade', key: 'terminal' },
  { path: '/orders', label: 'Orders', key: 'orders' },
  { path: '/portfolio', label: 'Portfolio', key: 'portfolio' },
  { path: '/settings', label: 'Menu', key: 'menu' },
];

export const TOUCH_TARGET_MIN_PX = 44;

export const TEST_VIEWPORTS = [
  320, 375, 390, 414, 480, 768, 820, 1024, 1280, 1440, 1920, 2560,
];
