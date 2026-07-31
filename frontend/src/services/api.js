//api.js - Axios instance with auth token handling and rate limit backoff
import axios from 'axios';
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
api.interceptors.request.use((config) => {
    // If we're in a 429 cooldown, reject immediately for polling/market requests
    // to prevent flooding the server with requests that will all fail
    if (
        isRateLimited() &&
        config.url?.includes('/market/') &&
        !config.url?.includes('/market/search')
    ) {
        return Promise.reject(new axios.Cancel('Rate limited — backing off'));
    }

    // Commodity lists fan out many data feed REST calls server-side.
    if (config.url?.includes('/market/commodities')) {
        config.timeout = 30000;
    }

    const token = localStorage.getItem('alphasync_token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// Handle 401 and 429 responses
api.interceptors.response.use(
    (response) => response,
    (error) => {
        // 429 — rate limited: set backoff so all polling pauses
        if (error.response?.status === 429) {
            const retryAfter = parseInt(error.response.headers?.['retry-after'] || '30', 10);
            _rateLimitedUntil = Date.now() + retryAfter * 1000;
            console.warn(`[API] Rate limited — backing off for ${retryAfter}s`);
            return Promise.reject(error);
        }

        if (
            error.response?.status === 401 &&
            !error.config?.url?.includes('/auth/login') &&
            !error.config?.url?.includes('/auth/register') &&
            !error.config?.url?.includes('/auth/logout')
        ) {
            // Token missing/expired/revoked — clear session and redirect to login
            _forceLogout();
        }

        return Promise.reject(error);
    }
);

function _forceLogout() {
    localStorage.removeItem('alphasync_token');
    localStorage.removeItem('alphasync_user');
    clearUserSessionCookie();
    if (window.location.pathname !== '/login') {
        window.location.href = '/login';
    }
}

export default api;
