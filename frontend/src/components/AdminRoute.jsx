import { Navigate } from 'react-router-dom';
import { useAuthStore } from '../stores/useAuthStore';
import AppLoader from './ui/AppLoader';

export default function AdminRoute({ children }) {
    const user = useAuthStore((s) => s.user);
    const initializing = useAuthStore((s) => s.initializing);

    if (initializing) {
        return <AppLoader />;
    }

    if (!user || user.role !== 'admin') {
        return <Navigate to="/admin" replace />;
    }

    return children;
}
