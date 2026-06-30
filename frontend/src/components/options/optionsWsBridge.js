/**
 * Send options subscribe messages on the shared AppShell WebSocket (no second socket).
 */

let sendFn = null;

export function registerOptionsWsSend(fn) {
  sendFn = typeof fn === 'function' ? fn : null;
}

/** @param {string[]|{ type?: string, symbols?: string[] }} payload */
export function optionsWsSend(payload) {
  if (!sendFn || !payload) return;
  try {
    const symbols = Array.isArray(payload) ? payload : payload.symbols;
    if (Array.isArray(symbols) && symbols.length > 0) {
      sendFn({ type: 'subscribe', symbols });
      return;
    }
    sendFn(payload);
  } catch {
    /* socket connecting */
  }
}

export function optionsWsUnsubscribe(symbols) {
  if (!sendFn || !symbols?.length) return;
  try {
    sendFn({ type: 'unsubscribe', symbols });
  } catch {
    /* ignore */
  }
}
