const COOKIE_NAME = 'alphasync_user_session';
const COOKIE_TTL_SECONDS = 60 * 60 * 24 * 30;

function _isSecureContext() {
    return typeof window !== 'undefined' && window.location?.protocol === 'https:';
}

export function setUserSessionCookie() {
    if (typeof document === 'undefined') return;
    const secure = _isSecureContext() ? '; Secure' : '';
    document.cookie = `${COOKIE_NAME}=1; Max-Age=${COOKIE_TTL_SECONDS}; Path=/; SameSite=Lax${secure}`;
}

export function hasUserSessionCookie() {
    if (typeof document === 'undefined') return false;
    const prefix = `${COOKIE_NAME}=`;
    return document.cookie.split(';').some((entry) => entry.trim().startsWith(prefix));
}

export function clearUserSessionCookie() {
    if (typeof document === 'undefined') return;
    const secure = _isSecureContext() ? '; Secure' : '';
    document.cookie = `${COOKIE_NAME}=; Max-Age=0; Path=/; SameSite=Lax${secure}`;
}
