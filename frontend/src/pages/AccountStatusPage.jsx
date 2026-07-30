import { Navigate, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../stores/useAuthStore';

const STATUS_COPY = {
    pending_approval: {
        title: 'Account Under Review',
        subtitle: 'Your registration is complete. Our team will review and approve your account shortly.',
        badge: 'Pending Approval',
        tone: '#f59e0b',
    },
    expired: {
        title: 'Demo Access Expired',
        subtitle: 'Your demo trading window has ended. Contact support to extend access.',
        badge: 'Access Expired',
        tone: '#f97316',
    },
    deactivated: {
        title: 'Account Deactivated',
        subtitle: 'This account is currently deactivated. Contact support for assistance.',
        badge: 'Deactivated',
        tone: '#ef4444',
    },
};

export default function AccountStatusPage() {
    const navigate = useNavigate();
    const user = useAuthStore((s) => s.user);
    const logout = useAuthStore((s) => s.logout);

    if (!user) {
        return <Navigate to="/login" replace />;
    }

    const statusKey = (user.account_status || '').toLowerCase();
    const isActive = statusKey === 'active' && !!user.is_active;

    if (isActive) {
        return <Navigate to="/dashboard" replace />;
    }

    const copy = STATUS_COPY[statusKey] || {
        title: 'Account Restricted',
        subtitle: 'Your account is currently restricted. Please contact support.',
        badge: 'Restricted',
        tone: '#f97316',
    };

    async function handleLogout() {
        await logout();
        navigate('/login', { replace: true });
    }

    async function handleBackToSignIn() {
        await logout();
        navigate('/login', { replace: true });
    }

    return (
        <div style={{
            minHeight: '100vh',
            background: 'radial-gradient(circle at 0% 0%, #122339 0%, #0b1020 45%, #080d18 100%)',
            color: '#e2e8f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
        }}>
            <div style={{
                width: '100%',
                maxWidth: 640,
                borderRadius: 18,
                border: '1px solid rgba(148,163,184,0.2)',
                background: 'linear-gradient(160deg, rgba(30,41,59,0.95), rgba(15,23,42,0.95))',
                boxShadow: '0 28px 64px rgba(0,0,0,0.45)',
                padding: 28,
            }}>
                <div style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 8,
                    background: 'rgba(15,23,42,0.75)',
                    border: `1px solid ${copy.tone}`,
                    color: copy.tone,
                    borderRadius: 999,
                    padding: '6px 12px',
                    fontSize: 13,
                    fontWeight: 700,
                    letterSpacing: 0.4,
                    textTransform: 'uppercase',
                }}>
                    {copy.badge}
                </div>

                <h1 style={{ marginTop: 18, marginBottom: 10, fontSize: 34, lineHeight: 1.08 }}>
                    {copy.title}
                </h1>

                <p style={{ margin: 0, color: '#cbd5e1', fontSize: 16, lineHeight: 1.6 }}>
                    {copy.subtitle}
                </p>

                <div style={{
                    marginTop: 22,
                    borderRadius: 12,
                    border: '1px solid rgba(148,163,184,0.18)',
                    background: 'rgba(2,6,23,0.5)',
                    padding: 14,
                    display: 'grid',
                    gap: 8,
                }}>
                    <div style={{ fontSize: 13, color: '#94a3b8' }}>Email</div>
                    <div style={{ fontSize: 15, fontWeight: 600 }}>{user.email}</div>
                    <div style={{ fontSize: 13, color: '#94a3b8' }}>Status</div>
                    <div style={{ fontSize: 15, fontWeight: 600 }}>{statusKey || 'restricted'}</div>
                    {user.access_expires_at ? (
                        <>
                            <div style={{ fontSize: 13, color: '#94a3b8' }}>Access Expiry</div>
                            <div style={{ fontSize: 15, fontWeight: 600 }}>
                                {new Date(user.access_expires_at).toLocaleString()}
                            </div>
                        </>
                    ) : null}
                </div>

                <div style={{ display: 'flex', gap: 10, marginTop: 22, flexWrap: 'wrap' }}>
                    <button
                        onClick={handleBackToSignIn}
                        style={{
                            border: '1px solid rgba(148,163,184,0.4)',
                            background: 'transparent',
                            color: '#e2e8f0',
                            borderRadius: 10,
                            padding: '10px 14px',
                            fontWeight: 600,
                            cursor: 'pointer',
                        }}
                    >
                        Back To Sign In
                    </button>

                    <button
                        onClick={handleLogout}
                        style={{
                            border: 'none',
                            background: 'linear-gradient(135deg, #ef4444, #b91c1c)',
                            color: '#fff',
                            borderRadius: 10,
                            padding: '10px 14px',
                            fontWeight: 700,
                            cursor: 'pointer',
                        }}
                    >
                        Sign Out
                    </button>
                </div>
            </div>
        </div>
    );
}
