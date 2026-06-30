//api.js - Axios instance with auth token handling and rate limit backoff
import axios from 'axios';
import { auth } from '../config/firebase';
import { clearUserSessionCookie } from '../utils/authSessionCookie';

const api = axios.create({
    baseURL: '/api',
    headers: { 'Content-Type': 'application/json' },
    timeout: 15000,
});

/**
 * 429 backoff tracker — when rate-limited, pause ALL requests until cooldown expires.
 * This prevents the cascading 429 avalanche where failed requests trigger more requests.
 */
let _rateLimitedUntil = 0;
export const isRateLimited = () => Date.now() < _rateLimitedUntil;

// Add auth token to requests + skip if rate-limited
api.interceptors.request.use(async (config) => {
    // If we're in a 429 cooldown, reject immediately for polling/market requests
    // to prevent flooding the server with requests that will all fail
    if (
        isRateLimited() &&
        config.url?.includes('/market/') &&
        !config.url?.includes('/market/search')
    ) {
        return Promise.reject(new axios.Cancel('Rate limited — backing off'));
    }

    // Broker connect/refresh calls may retry across multiple broker API
    // hosts server-side — give them more room than the default 15s so the
    // browser doesn't cancel before the backend can return a real error.
    if (config.url?.includes('/broker/')) {
        config.timeout = 35000;
    }

    // Commodity lists fan out many Zebu REST calls server-side.
    if (config.url?.includes('/market/commodities')) {
        config.timeout = 30000;
    }

    try {
        const currentUser = auth.currentUser;
        if (currentUser) {
            // getIdToken() auto-refreshes if token is expired
            const token = await currentUser.getIdToken();
            config.headers.Authorization = `Bearer ${token}`;
            // Also keep localStorage in sync for WebSocket connections
            localStorage.setItem('alphasync_token', token);
        }
    } catch {
        // If token refresh fails, let the request proceed without auth
        // The backend will return 401 and the app will redirect to login
    }
    return config;
});

// Handle 401 and 429 responses
api.interceptors.response.use(
    (response) => response,
    async (error) => {
        // 429 — rate limited: set backoff so all polling pauses
        if (error.response?.status === 429) {
            const retryAfter = parseInt(error.response.headers?.['retry-after'] || '30', 10);
            _rateLimitedUntil = Date.now() + retryAfter * 1000;
            console.warn(`[API] Rate limited — backing off for ${retryAfter}s`);
            return Promise.reject(error);
        }

        if (
            error.response?.status === 401 &&
            !error.config?.url?.includes('/auth/sync') &&
            !error.config?.url?.includes('/auth/logout')
        ) {
            // Firebase token might be revoked or user deleted server-side
            const currentUser = auth.currentUser;
            if (currentUser) {
                try {
                    // Force token refresh — if Firebase rejects, sign out
                    const newToken = await currentUser.getIdToken(true);
                    error.config.headers.Authorization = `Bearer ${newToken}`;
                    return api(error.config);
                } catch {
                    // Firebase session is truly invalid
                    _forceLogout();
                }
            } else {
                _forceLogout();
            }
        }

        return Promise.reject(error);
    }
);

function _forceLogout() {
    auth.signOut?.().catch(() => { });
    localStorage.removeItem('alphasync_token');
    localStorage.removeItem('alphasync_user');
    clearUserSessionCookie();
    if (window.location.pathname !== '/login') {
        window.location.href = '/login';
    }
}

export default api;
