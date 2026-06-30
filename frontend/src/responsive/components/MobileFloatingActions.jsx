import { useResponsive } from '../hooks/useResponsive';
import { cn } from '../../utils/cn';

/**
 * Quick BUY/SELL affordances on mobile trading routes.
 * Dispatches custom events so existing pages can listen without modification.
 */
export function MobileFloatingActions() {
  const { isDesktop, isTradingRoute, mobileTradingTab } = useResponsive();

  if (isDesktop || !isTradingRoute || mobileTradingTab === 'order') return null;

  const dispatchTrade = (side) => {
    window.dispatchEvent(
      new CustomEvent('responsive:trade', { detail: { side }, bubbles: true }),
    );
  };

  return (
    <div className="responsive-fab-group fixed right-3 z-[38] flex flex-col gap-2 safe-area-fab-offset lg:hidden">
      <button
        type="button"
        onClick={() => dispatchTrade('BUY')}
        className={cn(
          'responsive-fab responsive-fab-buy',
          'min-h-[44px] min-w-[44px] px-4 py-2 rounded-full font-bold text-sm text-white shadow-lg',
          'bg-bull active:scale-95 transition-transform',
        )}
      >
        BUY
      </button>
      <button
        type="button"
        onClick={() => dispatchTrade('SELL')}
        className={cn(
          'responsive-fab responsive-fab-sell',
          'min-h-[44px] min-w-[44px] px-4 py-2 rounded-full font-bold text-sm text-white shadow-lg',
          'bg-bear active:scale-95 transition-transform',
        )}
      >
        SELL
      </button>
    </div>
  );
}

export default MobileFloatingActions;
