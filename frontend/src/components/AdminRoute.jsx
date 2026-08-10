import { Navigate } from 'react-router-dom';
import { useAuthStore } from '../stores/useAuthStore';
import AppLoader from './ui/AppLoader';

export default function AdminRoute({ children }) {
    const user = useAuthStore((s) => s.user);
    const initializing = useAuthStore((s) => s.initializing);

    if (initializing) {
        return <AppLoader />;
    }

    if (!user) {
        return <Navigate to="/login" replace />;
    }

    const platRole = (user.role || '').toLowerCase();
    const acadRole = (user.academy_role || '').toLowerCase();
    const adminLevel = (user.admin_level || '').toLowerCase();

    const isAdmin =
        platRole === 'admin' ||
        Boolean(adminLevel) ||
        ['super_admin', 'institution_admin'].includes(acadRole);

    if (!isAdmin) {
        return <Navigate to="/dashboard" replace />;
    }

    return children;
}
