/**
 * Bridge to send futures subscribe messages on the shared AppShell WebSocket.
 * Avoids opening a second WS connection (which caused reconnect storms / error #185).
 */

let sendFn = null;

export function registerFuturesWsSend(fn) {
  sendFn = typeof fn === 'function' ? fn : null;
}

export function futuresWsSend(payload) {
  if (!sendFn || !payload) return;
  try {
    sendFn(payload);
  } catch {
    // ignore send failures while socket is connecting
  }
}
