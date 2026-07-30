import { useEffect } from 'react';
import { useResponsive } from '../hooks/useResponsive';

/**
 * Sticky submit / action bar when keyboard is open on trading routes.
 */
export function StickyTradeActionSystem() {
  const { isDesktop, isTradingRoute } = useResponsive();

  useEffect(() => {
    if (isDesktop || !isTradingRoute) return;

    const root = document.documentElement;

    const ensureBar = () => {
      let bar = document.getElementById('hard-sticky-trade-actions');
      if (!bar) {
        bar = document.createElement('div');
        bar.id = 'hard-sticky-trade-actions';
        bar.className = 'hard-sticky-trade-actions';
        bar.setAttribute('aria-hidden', 'true');
        document.body.appendChild(bar);
      }
      return bar;
    };

    const onFocus = (e) => {
      const form = e.target?.closest?.('form, .order-panel, .hard-order-surface');
      if (!form) return;
      const submit = form.querySelector?.(
        'button[type="submit"], button[data-hard-submit], .btn-buy, .btn-sell',
      );
      const bar = ensureBar();
      if (submit && root.classList.contains('hard-keyboard-open')) {
        bar.innerHTML = '';
        const clone = submit.cloneNode(true);
        clone.addEventListener('click', () => submit.click());
        bar.appendChild(clone);
        bar.classList.add('hard-sticky-trade-actions--visible');
      }
    };

    const onBlur = () => {
      const bar = document.getElementById('hard-sticky-trade-actions');
      bar?.classList.remove('hard-sticky-trade-actions--visible');
    };

    document.addEventListener('focusin', onFocus, true);
    document.addEventListener('focusout', onBlur, true);
    return () => {
      document.removeEventListener('focusin', onFocus, true);
      document.removeEventListener('focusout', onBlur, true);
      document.getElementById('hard-sticky-trade-actions')?.remove();
    };
  }, [isDesktop, isTradingRoute]);

  return null;
}

export default StickyTradeActionSystem;
