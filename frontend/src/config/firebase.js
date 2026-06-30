/**
 * Firebase client configuration for AlphaSync.
 *
 * Uses real Firebase authentication with hardcoded project credentials.
 * Env vars (VITE_FIREBASE_*) override the defaults if set.
 */
import { initializeApp } from 'firebase/app';
import {
    getAuth,
    GoogleAuthProvider,
    signInWithPopup as fbSignInWithPopup,
    signInWithEmailAndPassword as fbSignInWithEmail,
    createUserWithEmailAndPassword as fbCreateUser,
    signOut as fbSignOut,
    onAuthStateChanged as fbOnAuthStateChanged,
    sendPasswordResetEmail as fbSendPasswordReset,
    sendEmailVerification as fbSendEmailVerification,
    updateProfile as fbUpdateProfile,
} from 'firebase/auth';

// ── Firebase credentials (hardcoded defaults, overridable via env) ────────────

const firebaseConfig = {
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY || 'AIzaSyC2ZfxSeDvNK1yb2trj7OM8O-y18akFAig',
    authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || 'alphasync--demo.firebaseapp.com',
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || 'alphasync--demo',
    storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || 'alphasync--demo.firebasestorage.app',
    messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || '1000023655271',
    appId: import.meta.env.VITE_FIREBASE_APP_ID || '1:1000023655271:web:fc4d94df2f90f6a859e5c2',
};

// Always true now since we have hardcoded defaults
export const DEMO_MODE = false;

// ══════════════════════════════════════════════════════════════════════════════
// Initialize Firebase
// ══════════════════════════════════════════════════════════════════════════════

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const googleProvider = new GoogleAuthProvider();
googleProvider.addScope('email');
googleProvider.addScope('profile');
googleProvider.setCustomParameters({ prompt: 'select_account' });

// ── Re-export real Firebase functions directly ────────────────────────────────

const signInWithPopup = fbSignInWithPopup;
const signInWithEmailAndPassword = fbSignInWithEmail;
const createUserWithEmailAndPassword = fbCreateUser;
const signOut = fbSignOut;
const sendPasswordResetEmail = fbSendPasswordReset;
const sendEmailVerification = fbSendEmailVerification;
const updateProfile = fbUpdateProfile;
const onAuthStateChanged = fbOnAuthStateChanged;

export {
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
};
export default app;
