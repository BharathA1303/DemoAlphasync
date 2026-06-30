import { create } from 'zustand';
import api from '../services/api';

/**
 * Multi-broker connection store.
 *
 * Tracks connection state for Zebu, Alice Blue, and Zerodha.
 * Users must connect at least one broker to use demo trading.
 */
export const useBrokerStore = create((set, get) => ({
    // ─── Per-broker status ───────────────────────────────────────────
    brokers: {
        zebu: { status: 'disconnected', brokerUserId: null, tokenExpiry: null, credentialsConfigured: false, apiKeyPreview: null },
        aliceblue: { status: 'disconnected', brokerUserId: null, tokenExpiry: null, credentialsConfigured: false, apiKeyPreview: null },
        zerodha: { status: 'disconnected', brokerUserId: null, tokenExpiry: null, credentialsConfigured: false, apiKeyPreview: null },
    },

    /** True once the server-confirmed broker status has been fetched at least once */
    statusLoaded: false,

    /** True if at least one broker is connected */
    anyConnected: false,

    /** True while an API call is in-flight */
    loading: false,

    /** Last error message */
    error: null,

    // ─── Helpers ─────────────────────────────────────────────────────

    _setBroker: (broker, patch) =>
        set((s) => ({
            brokers: { ...s.brokers, [broker]: { ...s.brokers[broker], ...patch } },
        })),

    _refreshAnyConnected: () => {
        const { brokers } = get();
        const any = Object.values(brokers).some((b) => b.status === 'connected');
        set({ anyConnected: any });
    },

    // ─── OAuth flow: initiate connect (returns redirect URL) ─────────

    /**
     * Start broker OAuth — returns { redirect_url, state }.
     * Caller should do window.location.href = redirect_url.
     */
    connect: async (broker = 'zebu') => {
        set({ loading: true, error: null });
        try {
            const endpointMap = {
                zebu: '/broker/zebu/connect',
                aliceblue: '/broker/aliceblue/connect',
                zerodha: '/broker/zerodha/connect',
            };
            const endpoint = endpointMap[broker];
            if (!endpoint) throw new Error(`Unsupported broker: ${broker}`);
            const res = await api.get(endpoint);
            get()._setBroker(broker, { status: 'connecting' });
            set({ loading: false });
            return res.data; // { redirect_url, state }
        } catch (err) {
            const msg = err.response?.data?.detail || 'Failed to initiate connection';
            set({ loading: false, error: msg });
            throw new Error(msg);
        }
    },

    /**
     * Exchange OAuth callback params for a stored token.
     * Called from BrokerCallbackPage after the broker redirects back.
     */
    handleCallback: async (broker, params = {}) => {
        set({ loading: true, error: null });
        try {
            let res;
            if (broker === 'zebu') {
                res = await api.post('/broker/zebu/callback', {
                    auth_code: params.authCode || '',
                    state: params.state || '',
                    susertoken: params.susertoken || '',
                    uid: params.uid || '',
                    actid: params.actid || '',
                });
            } else if (broker === 'aliceblue') {
                res = await api.post('/broker/aliceblue/callback', {
                    auth_code: params.authCode || '',
                    state: params.state || '',
                    broker_user_id: params.brokerUserId || '',
                });
            } else if (broker === 'zerodha') {
                res = await api.post('/broker/zerodha/callback', {
                    request_token: params.requestToken || params.authCode || '',
                    state: params.state || '',
                });
            } else {
                throw new Error(`Unknown broker: ${broker}`);
            }
            get()._setBroker(broker, {
                status: 'connected',
                brokerUserId: res.data.broker_user_id,
            });
            set({ loading: false, anyConnected: true });
            get().clearOAuthContext();
            return res.data;
        } catch (err) {
            const msg = err.response?.data?.detail || 'Broker callback failed';
            get()._setBroker(broker, { status: 'disconnected' });
            set({ loading: false, error: msg });
            throw new Error(msg);
        }
    },

    /**
     * Disconnect a specific broker.
     */
    disconnect: async (broker = 'zebu') => {
        set({ loading: true, error: null });
        try {
            const endpointMap = {
                zebu: '/broker/zebu/disconnect',
                aliceblue: '/broker/aliceblue/disconnect',
                zerodha: '/broker/zerodha/disconnect',
            };
            await api.delete(endpointMap[broker] || `/broker/${broker}/disconnect`);
            get()._setBroker(broker, { status: 'disconnected', brokerUserId: null, tokenExpiry: null });
            set({ loading: false });
            get()._refreshAnyConnected();
        } catch (err) {
            const msg = err.response?.data?.detail || 'Disconnect failed';
            set({ loading: false, error: msg });
        }
    },

    /**
     * Direct Zebu login via QuickAuth (no OAuth redirect needed).
     */
    login: async (zebuUserId, password, factor2 = '', apiKey = '', vendorCode = '') => {
        set({ loading: true, error: null });
        try {
            const res = await api.post('/broker/zebu/login', {
                zebu_user_id: zebuUserId,
                password,
                factor2,
                api_key: apiKey,
                vendor_code: vendorCode || undefined,
            });
            get()._setBroker('zebu', {
                status: 'connected',
                brokerUserId: res.data.broker_user_id,
            });
            set({ loading: false, anyConnected: true });
            return res.data;
        } catch (err) {
            const msg = err.response?.data?.detail || 'Zebu login failed';
            get()._setBroker('zebu', { status: 'disconnected' });
            set({ loading: false, error: msg });
            throw new Error(msg);
        }
    },

    /**
     * Refresh broker session — reuses stored token if valid, otherwise
     * returns OAuth redirect URL for re-authentication.
     */
    refreshSession: async (broker = 'zebu') => {
        set({ loading: true, error: null });
        try {
            const res = await api.post(`/broker/${broker}/refresh`);
            if (res.data.reauth_required) {
                set({ loading: false });
                return res.data; // { redirect_url, state, reauth_required: true }
            }
            get()._setBroker(broker, { status: 'connected' });
            set({ loading: false, anyConnected: true });
            return res.data;
        } catch (err) {
            const msg = err.response?.data?.detail || 'Session refresh failed';
            set({ loading: false, error: msg });
            throw new Error(msg);
        }
    },

    /**
     * Persist OAuth context before redirecting to a broker login page.
     */
    storeOAuthContext: (broker, state) => {
        try {
            localStorage.setItem('broker_oauth_broker', broker);
            if (state) localStorage.setItem('broker_oauth_state', state);
        } catch {
            // localStorage unavailable
        }
    },

    clearOAuthContext: () => {
        try {
            localStorage.removeItem('broker_oauth_broker');
            localStorage.removeItem('broker_oauth_state');
        } catch {
            // ignore
        }
    },

    /**
     * Fetch status for all brokers. Call on app mount / dashboard load.
     * This is the server-confirmed source of truth for the onboarding gate.
     */
    fetchStatus: async () => {
        try {
            const res = await api.get('/broker/all-status');
            const { brokers: statuses, any_connected } = res.data;
            const updated = { ...get().brokers };
            for (const [broker, s] of Object.entries(statuses)) {
                if (updated[broker]) {
                    updated[broker] = {
                        ...updated[broker],
                        status: s.connected ? 'connected' : s.is_expired ? 'expired' : 'disconnected',
                        brokerUserId: s.broker_user_id || null,
                        tokenExpiry: s.token_expiry || null,
                    };
                }
            }
            set({ brokers: updated, anyConnected: any_connected, statusLoaded: true });
            return any_connected;
        } catch {
            // silent — non-critical
            return get().anyConnected;
        }
    },

    /**
     * Save (or update) the user's own app credentials for a broker.
     * Alice Blue/Zerodha: { api_key, api_secret }. Zebu (optional override): { api_key, vendor_code }.
     */
    saveCredentials: async (broker, fields = {}) => {
        set({ loading: true, error: null });
        try {
            const res = await api.post(`/broker/${broker}/credentials`, fields);
            get()._setBroker(broker, { credentialsConfigured: true });
            set({ loading: false });
            return res.data;
        } catch (err) {
            const msg = err.response?.data?.detail || 'Failed to save credentials';
            set({ loading: false, error: msg });
            throw new Error(msg);
        }
    },

    /**
     * Check whether app credentials are already saved for a broker (masked preview only).
     */
    fetchCredentialsStatus: async (broker) => {
        try {
            const res = await api.get(`/broker/${broker}/credentials`);
            get()._setBroker(broker, {
                credentialsConfigured: Boolean(res.data?.configured),
                apiKeyPreview: res.data?.api_key_preview || null,
            });
            return res.data;
        } catch {
            return { configured: false, api_key_preview: null };
        }
    },

    /**
     * Remove saved broker app credentials (keeps user account and other data).
     */
    clearCredentials: async (broker = 'zebu') => {
        set({ loading: true, error: null });
        try {
            await api.delete(`/broker/${broker}/credentials`);
            get()._setBroker(broker, {
                status: 'disconnected',
                brokerUserId: null,
                tokenExpiry: null,
                credentialsConfigured: false,
                apiKeyPreview: null,
            });
            set({ loading: false });
            get()._refreshAnyConnected();
            try {
                localStorage.removeItem('alphasync_onboarded');
            } catch {
                // ignore
            }
            return { success: true };
        } catch (err) {
            const msg = err.response?.data?.detail || 'Failed to clear credentials';
            set({ loading: false, error: msg });
            throw new Error(msg);
        }
    },

    /**
     * Dev helper: manually inject a Zebu session token.
     */
    manualToken: async (sessionToken, brokerUserId = '', uid = '') => {
        set({ loading: true, error: null });
        try {
            const res = await api.post('/broker/zebu/manual-token', {
                session_token: sessionToken,
                broker_user_id: brokerUserId,
                uid,
            });
            get()._setBroker('zebu', { status: 'connected', brokerUserId: res.data.broker_user_id });
            set({ loading: false, anyConnected: true });
            return res.data;
        } catch (err) {
            const msg = err.response?.data?.detail || 'Manual token failed';
            set({ loading: false, error: msg });
            throw new Error(msg);
        }
    },

    // ─── Backward-compat shims ────────────────────────────────────────
    // Some legacy code calls `status` / `brokerUserId` from store root.
    get status() { return get().brokers.zebu?.status ?? 'disconnected'; },
    get brokerUserId() { return get().brokers.zebu?.brokerUserId ?? null; },
}));
