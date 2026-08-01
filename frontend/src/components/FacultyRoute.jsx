import { Navigate } from 'react-router-dom';
import { useAuthStore } from '../stores/useAuthStore';
import AppLoader from './ui/AppLoader';

const FACULTY_ACADEMY_ROLES = ['faculty', 'institution_admin', 'super_admin'];

export default function FacultyRoute({ children }) {
    const user = useAuthStore((s) => s.user);
    const initializing = useAuthStore((s) => s.initializing);

    if (initializing) {
        return <AppLoader />;
    }

    if (!user || !FACULTY_ACADEMY_ROLES.includes(user.academy_role)) {
        return <Navigate to="/dashboard" replace />;
    }

    return children;
}
