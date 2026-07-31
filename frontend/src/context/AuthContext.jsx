// Legacy AuthContext — replaced by useAuthStore (stores/useAuthStore.js).
// Kept as a thin shim so any remaining imports don't break at runtime.
import { createContext, useContext } from 'react';
import { useAuthStore } from '../stores/useAuthStore';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
    // No-op wrapper — auth is managed by useAuthStore
    return children;
}

export function useAuth() {
    const user = useAuthStore((s) => s.user);
    const logout = useAuthStore((s) => s.logout);
    return { user, logout, isAuthenticated: !!user };
}
