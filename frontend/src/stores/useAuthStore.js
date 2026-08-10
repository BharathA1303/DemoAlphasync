import { create } from 'zustand';
import api from '../services/api';
import {
    setUserSessionCookie,
    clearUserSessionCookie,
} from '../utils/authSessionCookie';

const GROUP_TOKEN_STORAGE_KEY = 'alphasync_group_token';
const INST_TOKEN_STORAGE_KEY = 'alphasync_inst_token';

function getGroupTokenForSync() {
    try {
        const params = new URLSearchParams(window.location.search || '');
        const fromUrl = (params.get('grp') || '').trim();
        if (fromUrl) {
            localStorage.setItem(GROUP_TOKEN_STORAGE_KEY, fromUrl);
            return fromUrl;
        }
    } catch {
    }

    try {
        const stored = (localStorage.getItem(GROUP_TOKEN_STORAGE_KEY) || '').trim();
        return stored || '';
    } catch {
        return '';
    }
}

function getInstitutionTokenForSync() {
    try {
        const params = new URLSearchParams(window.location.search || '');
        const fromUrl = (params.get('inst') || '').trim();
        if (fromUrl) {
            localStorage.setItem(INST_TOKEN_STORAGE_KEY, fromUrl);
            return fromUrl;
        }
    } catch {
    }

    try {
        const stored = (localStorage.getItem(INST_TOKEN_STORAGE_KEY) || '').trim();
        return stored || '';
    } catch {
        return '';
    }
}

function persistSession(token, user) {
    localStorage.setItem('alphasync_token', token);
    localStorage.setItem('alphasync_user', JSON.stringify(user));
    localStorage.removeItem(GROUP_TOKEN_STORAGE_KEY);
    localStorage.removeItem(INST_TOKEN_STORAGE_KEY);
    setUserSessionCookie();
}

function clearSession() {
    localStorage.removeItem('alphasync_token');
    localStorage.removeItem('alphasync_user');
    localStorage.removeItem('alphasync_onboarded');
    clearUserSessionCookie();
    try {
        sessionStorage.removeItem('alphasync_admin_session');
    } catch {
    }
}

/**
 * Auth store — local username/email/password authentication.
 *
 * Flow:
 *   1. User registers or logs in via POST /api/auth/register or /login
 *   2. Backend returns a JWT + the local user profile
 *   3. Token is stored in localStorage and sent as Bearer on every request
 *      (see services/api.js interceptor)
 */
export const useAuthStore = create((set, get) => ({
    /** @type {object|null} */
    user: (() => {
        try {
            const stored = localStorage.getItem('alphasync_user');
            return stored ? JSON.parse(stored) : null;
        } catch { return null; }
    })(),

    /** @type {boolean} */
    loading: true,

    /** @type {boolean} */
    initializing: true,

    // ─── Initialize auth on app mount ──────────────────────────────────────

    /**
     * Call once on app mount. Validates any stored token against the
     * backend and refreshes the cached user profile.
     */
    initAuth: async () => {
        const token = localStorage.getItem('alphasync_token');
        if (!token) {
            set({ user: null, loading: false, initializing: false });
            return;
        }

        set({ loading: true });
        try {
            const res = await api.get('/auth/me');
            localStorage.setItem('alphasync_user', JSON.stringify(res.data));
            setUserSessionCookie();
            set({ user: res.data, loading: false, initializing: false });
        } catch {
            clearSession();
            set({ user: null, loading: false, initializing: false });
        }
    },

    // ─── Actions ──────────────────────────────────────────────────────────────

    login: async (usernameOrEmail, password) => {
        const instToken = getInstitutionTokenForSync();
        const res = await api.post('/auth/login', {
            username: usernameOrEmail,
            password,
            ...(instToken ? { institution_token: instToken } : {}),
        });
        persistSession(res.data.token, res.data.user);
        set({ user: res.data.user, loading: false, initializing: false });
        return { success: true, isNew: false, user: res.data.user };
    },

    register: async ({ username, email, password, full_name }) => {
        const groupToken = getGroupTokenForSync();
        const instToken = getInstitutionTokenForSync();
        const res = await api.post('/auth/register', {
            username,
            email,
            password,
            full_name,
            ...(groupToken ? { group_token: groupToken } : {}),
            ...(instToken ? { institution_token: instToken } : {}),
        });
        persistSession(res.data.token, res.data.user);
        set({ user: res.data.user, loading: false, initializing: false });
        return { success: true, isNew: true, user: res.data.user };
    },

    logout: async () => {
        try {
            await api.post('/auth/logout');
        } catch {
            // Best-effort
        }
        clearSession();
        set({ user: null });
    },

    /**
     * Get the stored JWT (used by the API interceptor / WebSocket connections).
     */
    getToken: () => {
        return localStorage.getItem('alphasync_token');
    },

    /**
     * Partially update user fields in store + localStorage.
     */
    updateUser: (patch) => {
        const current = get().user;
        if (!current) return;
        const updated = { ...current, ...patch };
        localStorage.setItem('alphasync_user', JSON.stringify(updated));
        set({ user: updated });
    },

    /**
     * Save the user's mobile number as contact info (no OTP required).
     * Validates format on the backend (+91, 10-digit, starts with 6-9).
     * Patches the in-memory store so callers see the phone immediately.
     */
    submitPhone: async (phone) => {
        const response = await api.post('/auth/set-phone', { phone });
        const current = get().user;
        if (current) {
            const updated = { ...current, phone: response.data.phone };
            localStorage.setItem('alphasync_user', JSON.stringify(updated));
            set({ user: updated });
        }
        return response.data;
    },

    switchTenant: async (tenantId) => {
        const response = await api.post('/auth/switch-tenant', { tenant_id: tenantId });
        if (response.data?.user) {
            localStorage.setItem('alphasync_user', JSON.stringify(response.data.user));
            set({ user: response.data.user });
        }
        return response.data;
    },
}));
