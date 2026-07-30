/**
 * Mobile keyboard avoidance for trading inputs.
 */

let cleanup = null;
let focusedInput = null;

function updateKeyboardInset() {
  const root = document.documentElement;
  const vv = window.visualViewport;
  if (!vv) return;

  const keyboardHeight = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
  root.style.setProperty('--keyboard-height', `${keyboardHeight}px`);
  root.style.setProperty('--keyboard-offset', `${vv.offsetTop}px`);

  const open = keyboardHeight > 80;
  root.classList.toggle('hard-keyboard-open', open);
  root.dataset.keyboardOpen = open ? 'true' : 'false';

  if (open && focusedInput) {
    requestAnimationFrame(() => {
      focusedInput.scrollIntoView({ block: 'center', behavior: 'smooth' });
    });
  }
}

function onFocusIn(e) {
  const el = e.target;
  if (
    el?.matches?.(
      'input, textarea, select, [contenteditable="true"]',
    )
  ) {
    focusedInput = el;
    document.documentElement.classList.add('hard-input-focused');
    updateKeyboardInset();
  }
}

function onFocusOut() {
  focusedInput = null;
  document.documentElement.classList.remove('hard-input-focused');
  setTimeout(updateKeyboardInset, 80);
}

export function initMobileKeyboardCoordinator() {
  if (typeof window === 'undefined') return;
  updateKeyboardInset();
  window.visualViewport?.addEventListener('resize', updateKeyboardInset, { passive: true });
  window.visualViewport?.addEventListener('scroll', updateKeyboardInset, { passive: true });
  document.addEventListener('focusin', onFocusIn, true);
  document.addEventListener('focusout', onFocusOut, true);
  cleanup = () => {
    window.visualViewport?.removeEventListener('resize', updateKeyboardInset);
    window.visualViewport?.removeEventListener('scroll', updateKeyboardInset);
    document.removeEventListener('focusin', onFocusIn, true);
    document.removeEventListener('focusout', onFocusOut, true);
    document.documentElement.classList.remove('hard-keyboard-open', 'hard-input-focused');
    delete document.documentElement.dataset.keyboardOpen;
  };
}

export function disposeMobileKeyboardCoordinator() {
  cleanup?.();
  cleanup = null;
}
