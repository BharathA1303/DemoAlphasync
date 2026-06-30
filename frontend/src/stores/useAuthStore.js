import { create } from 'zustand';
import {
    auth,
    googleProvider,
    signInWithPopup,
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    signOut,
    onAuthStateChanged,
    sendPasswordResetEmail,
    sendEmailVerification,
    updateProfile,
    DEMO_MODE,
} from '../config/firebase';
import api from '../services/api';
import {
    setUserSessionCookie,
    clearUserSessionCookie,
} from '../utils/authSessionCookie';

const pendingSyncRequests = new Map();
const GROUP_TOKEN_STORAGE_KEY = 'alphasync_group_token';

const VERIFICATION_CONTINUE_PATH = '/verify-email';

function getVerificationActionSettings() {
    const origin = window.location.origin;
    return {
        url: `${origin}${VERIFICATION_CONTINUE_PATH}`,
        handleCodeInApp: false,
    };
}

async function sendVerificationEmail(user) {
    const actionCodeSettings = getVerificationActionSettings();
    try {
        await sendEmailVerification(user, actionCodeSettings);
    } catch {
        await sendEmailVerification(user);
    }
}

async function syncUserWithBackend(firebaseUser, payload = {}) {
    const key = `${firebaseUser?.uid || 'unknown'}:${JSON.stringify(payload || {})}`;
    if (pendingSyncRequests.has(key)) {
        return pendingSyncRequests.get(key);
    }

    const requestPromise = (async () => {
        const firstToken = await firebaseUser.getIdToken();
        localStorage.setItem('alphasync_token', firstToken);

        try {
            return await api.post('/auth/sync', payload);
        } catch (err) {
            if (err?.response?.status !== 401) {
                throw err;
            }

            const refreshedToken = await firebaseUser.getIdToken(true);
            localStorage.setItem('alphasync_token', refreshedToken);
            return await api.post('/auth/sync', payload);
        }
    })();

    pendingSyncRequests.set(key, requestPromise);
    try {
        return await requestPromise;
    } finally {
        pendingSyncRequests.delete(key);
    }
}

function getAuthIntent() {
    const intent = (localStorage.getItem('alphasync_auth_intent') || 'login').toLowerCase();
    return intent === 'register' ? 'register' : 'login';
}

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

async function clearInvalidSession() {
    try {
        await signOut(auth);
    } catch {
    }
    localStorage.removeItem('alphasync_token');
    localStorage.removeItem('alphasync_user');
    clearUserSessionCookie();
    try {
        sessionStorage.removeItem('alphasync_admin_session');
    } catch {
    }
}

function syncUserSessionCookie(user) {
    setUserSessionCookie();
}

/**
 * Auth store — Firebase-based authentication.
 *
 * Flow:
 *   1. User signs in via Firebase (Google popup / email+password)
 *   2. Firebase returns an ID token
 *   3. ID token sent to backend POST /api/auth/sync to find-or-create local user
 *   4. Backend returns local user profile
 *   5. All subsequent API calls use the Firebase ID token as Bearer
 */
export const useAuthStore = create((set, get) => ({
    /** @type {object|null} */
    user: (() => {
        try {
            const stored = localStorage.getItem('alphasync_user');
            return stored ? JSON.parse(stored) : null;
        } catch { return null; }
    })(),

    /** @type {import('firebase/auth').User|null} */
    firebaseUser: null,

    /** @type {boolean} */
    loading: true,

    /** @type {boolean} */
    initializing: true,

    // ─── Initialize Firebase auth listener ────────────────────────────────────

    /**
     * Call once on app mount to listen for Firebase auth state changes.
     * Automatically gets fresh tokens and syncs with backend.
     */
    initAuth: () => {
        const unsubscribe = onAuthStateChanged(auth, async (firebaseUser) => {
            if (firebaseUser) {
                // For email/password users, don't sync until email is verified
                const isEmailProvider = firebaseUser.providerData?.[0]?.providerId === 'password';
                if (isEmailProvider && !firebaseUser.emailVerified) {
                    // Unverified email user — don't sync, sign them out
                    await signOut(auth);
                    localStorage.removeItem('alphasync_token');
                    localStorage.removeItem('alphasync_user');
                    clearUserSessionCookie();
                    set({ user: null, firebaseUser: null, loading: false, initializing: false });
                    return;
                }

                set({ firebaseUser, loading: true });
                try {
                    const pendingUsername = localStorage.getItem('alphasync_pending_username') || '';
                    const authIntent = getAuthIntent();
                    const groupToken = getGroupTokenForSync();
                    const res = await syncUserWithBackend(
                        firebaseUser,
                        {
                            ...(pendingUsername ? { username: pendingUsername } : {}),
                            auth_intent: authIntent,
                            ...(groupToken ? { group_token: groupToken } : {}),
                        }
                    );
                    localStorage.removeItem('alphasync_pending_username');
                    localStorage.removeItem('alphasync_auth_intent');
                    localStorage.removeItem(GROUP_TOKEN_STORAGE_KEY);
                    localStorage.setItem('alphasync_user', JSON.stringify(res.data.user));
                    syncUserSessionCookie(res.data.user);
                    set({ user: res.data.user, loading: false, initializing: false });
                } catch (err) {
                    console.error('Auth sync failed:', err?.response?.data?.detail || err?.response?.data || err.message);
                    localStorage.removeItem('alphasync_auth_intent');
                    await clearInvalidSession();
                    set({ user: null, firebaseUser: null, loading: false, initializing: false });
                }
            } else {
                localStorage.removeItem('alphasync_token');
                localStorage.removeItem('alphasync_user');
                clearUserSessionCookie();
                set({ user: null, firebaseUser: null, loading: false, initializing: false });
            }
        });
        return unsubscribe;
    },

    // ─── Actions ──────────────────────────────────────────────────────────────

    loginWithGoogle: async (intent = 'login') => {
        const authIntent = intent === 'register' ? 'register' : 'login';
        const groupToken = getGroupTokenForSync();
        localStorage.setItem('alphasync_auth_intent', authIntent);

        // Avoid sticky-account reuse; force fresh account selection in popup.
        try {
            await signOut(auth);
        } catch {
        }

        const result = await signInWithPopup(auth, googleProvider);

        try {
            const res = await syncUserWithBackend(result.user, {
                auth_intent: authIntent,
                ...(groupToken ? { group_token: groupToken } : {}),
            });
            localStorage.removeItem('alphasync_auth_intent');
            localStorage.removeItem(GROUP_TOKEN_STORAGE_KEY);
            localStorage.setItem('alphasync_user', JSON.stringify(res.data.user));
            syncUserSessionCookie(res.data.user);
            set({ user: res.data.user, firebaseUser: result.user, loading: false, initializing: false });
            return { success: true, isNew: res.data.is_new_user, user: res.data.user };
        } catch (err) {
            const detail = err.response?.data?.detail;
            console.error('Auth sync error:', detail || err.message);
            localStorage.removeItem('alphasync_auth_intent');
            if (err?.response?.status === 401) {
                await clearInvalidSession();
                set({ user: null, firebaseUser: null });
            }
            if (err?.response?.status === 404) {
                await clearInvalidSession();
                set({ user: null, firebaseUser: null });
            }
            const error = new Error(detail || err.message);
            error.code = err.code;
            error.response = err.response;
            throw error;
        }
    },

    loginWithEmail: async (email, password) => {
        const result = await signInWithEmailAndPassword(auth, email, password);

        // Block login if email not verified
        if (!result.user.emailVerified) {
            await signOut(auth);
            const error = new Error('Please verify your email before signing in. Check your inbox.');
            error.code = 'auth/email-not-verified';
            throw error;
        }

        const pendingUsername = localStorage.getItem('alphasync_pending_username') || '';
        const groupToken = getGroupTokenForSync();
        // Use stored intent ('register' if set during registration, 'login' otherwise).
        // If the sync returns 404 (user not in DB but email is now verified),
        // automatically retry as 'register' — this handles the case where the user
        // closed the browser between registration and email verification.
        const authIntent = getAuthIntent();
        const syncPayload = {
            ...(pendingUsername ? { username: pendingUsername } : {}),
            auth_intent: authIntent,
            ...(groupToken ? { group_token: groupToken } : {}),
        };
        try {
            let res;
            try {
                res = await syncUserWithBackend(result.user, syncPayload);
            } catch (firstErr) {
                if (firstErr?.response?.status === 404 && authIntent !== 'register') {
                    // User verified their email but the backend has no record yet —
                    // retry as a new registration.
                    res = await syncUserWithBackend(result.user, { ...syncPayload, auth_intent: 'register' });
                } else {
                    throw firstErr;
                }
            }
            localStorage.removeItem('alphasync_pending_username');
            localStorage.removeItem('alphasync_auth_intent');
            localStorage.removeItem(GROUP_TOKEN_STORAGE_KEY);
            localStorage.setItem('alphasync_user', JSON.stringify(res.data.user));
            syncUserSessionCookie(res.data.user);
            set({ user: res.data.user, firebaseUser: result.user, loading: false, initializing: false });
            return { success: true, isNew: res.data.is_new_user, user: res.data.user };
        } catch (err) {
            if (err?.response?.status === 401) {
                await clearInvalidSession();
                set({ user: null, firebaseUser: null });
            }
            throw err;
        }
    },

    registerWithEmail: async (email, password, displayName, username) => {
        getGroupTokenForSync();
        const result = await createUserWithEmailAndPassword(auth, email, password);

        // Set display name in Firebase
        if (displayName) {
            await updateProfile(result.user, { displayName });
        }

        // Send verification email — user must verify before they can trade
        await sendVerificationEmail(result.user);
        sessionStorage.setItem('alphasync_verify_email', email);

        // Store pending registration info so we can sync after verification.
        // auth_intent must persist across the sign-out so that loginWithEmail
        // knows to CREATE the user in the backend (not just look one up).
        localStorage.setItem('alphasync_pending_username', username || '');
        localStorage.setItem('alphasync_auth_intent', 'register');
        set({ firebaseUser: result.user });

        // Sign out immediately — user must verify email first
        await signOut(auth);
        localStorage.removeItem('alphasync_token');
        localStorage.removeItem('alphasync_user');
        clearUserSessionCookie();
        set({ user: null, firebaseUser: null });

        return { success: true, needsVerification: true };
    },

    /**
     * Resend verification email to the current or provided email.
     */
    resendVerification: async (email, password) => {
        if (!email || !password) {
            const err = new Error('Please enter your password to resend verification email.');
            err.code = 'auth/missing-password';
            throw err;
        }

        // Sign in temporarily to get the user object for resend
        const result = await signInWithEmailAndPassword(auth, email, password);
        if (!result.user.emailVerified) {
            await sendVerificationEmail(result.user);
        }
        await signOut(auth);
        return { sent: !result.user.emailVerified, alreadyVerified: result.user.emailVerified };
    },

    resetPassword: async (email) => {
        await sendPasswordResetEmail(auth, email);
    },

    logout: async () => {
        try {
            await api.post('/auth/logout');
        } catch {
            // Best-effort
        }
        await signOut(auth);
        localStorage.removeItem('alphasync_token');
        localStorage.removeItem('alphasync_user');
        localStorage.removeItem('alphasync_onboarded');
        clearUserSessionCookie();
        try {
            sessionStorage.removeItem('alphasync_admin_session');
        } catch {
        }
        set({ user: null, firebaseUser: null });
    },

    /**
     * Get a fresh Firebase ID token (auto-refreshes if expired).
     * Used by the API interceptor.
     */
    getToken: async () => {
        const { firebaseUser } = get();
        if (!firebaseUser) {
            // Try getting from Firebase auth directly
            const currentUser = auth.currentUser;
            if (currentUser) {
                return await currentUser.getIdToken();
            }
            return null;
        }
        return await firebaseUser.getIdToken();
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
     * Step 1 — request an OTP to be sent to the supplied phone number.
     * Returns the server response { message, expires_in, cooldown }.
     * Throws on validation or rate-limit errors.
     */
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
}));