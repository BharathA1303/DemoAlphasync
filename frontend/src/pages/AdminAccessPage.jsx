import { Navigate, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../stores/useAuthStore';

export default function AdminAccessPage() {
    const navigate = useNavigate();
    const user = useAuthStore((s) => s.user);
    const initializing = useAuthStore((s) => s.initializing);
    const logout = useAuthStore((s) => s.logout);

    async function handleSwitchAccount() {
        try {
            await logout();
        } catch {
        }
        navigate('/login?intent=admin', { replace: true });
    }

    if (initializing) {
        return (
            <div style={styles.shell}>
                <div style={styles.card}>
                    <div className="animate-spin" style={styles.spinner} />
                    <p style={styles.muted}>Preparing admin access...</p>
                </div>
            </div>
        );
    }

    if (user?.role === 'admin') {
        return <Navigate to="/admin/panel" replace />;
    }

    return (
        <div style={styles.shell}>
            <div style={styles.card}>
                <div style={styles.badge}>Admin Access</div>
                <h1 style={styles.title}>AlphaSync Admin Panel</h1>

                {!user ? (
                    <>
                        <p style={styles.text}>
                            Sign in with the allowlisted admin email to continue.
                        </p>
                        <div style={styles.actions}>
                            <button
                                style={styles.primaryBtn}
                                onClick={() => navigate('/login?intent=admin', { replace: true })}
                            >
                                Sign In As Admin
                            </button>
                            <button
                                style={styles.secondaryBtn}
                                onClick={() => navigate('/login', { replace: true })}
                            >
                                Back To Login
                            </button>
                        </div>
                    </>
                ) : (
                    <>
                        <p style={styles.text}>
                            Signed in as <strong>{user.email}</strong>, but this account does not have admin role.
                        </p>
                        <p style={styles.note}>
                            Use the allowlisted email, then complete admin 2FA verification.
                        </p>
                        <div style={styles.actions}>
                            <button style={styles.primaryBtn} onClick={handleSwitchAccount}>
                                Sign Out And Switch Account
                            </button>
                            <button
                                style={styles.secondaryBtn}
                                onClick={() => navigate('/account-status', { replace: true })}
                            >
                                Go To Account Status
                            </button>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}

const styles = {
    shell: {
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background:
            'radial-gradient(circle at 0% 0%, #1f334e 0%, #0f1a31 48%, #090f1f 100%)',
        color: '#e2e8f0',
        padding: '24px',
    },
    card: {
        width: '100%',
        maxWidth: '640px',
        borderRadius: '18px',
        border: '1px solid rgba(148,163,184,0.24)',
        background: 'linear-gradient(165deg, rgba(30,41,59,0.96), rgba(15,23,42,0.95))',
        boxShadow: '0 28px 64px rgba(0,0,0,0.45)',
        padding: '28px',
    },
    badge: {
        display: 'inline-flex',
        alignItems: 'center',
        padding: '6px 12px',
        borderRadius: '999px',
        border: '1px solid rgba(56,189,248,0.75)',
        color: '#38bdf8',
        fontWeight: 700,
        fontSize: '13px',
        letterSpacing: '0.3px',
        textTransform: 'uppercase',
    },
    title: {
        marginTop: '16px',
        marginBottom: '10px',
        fontSize: '34px',
        lineHeight: 1.08,
    },
    text: {
        margin: 0,
        color: '#cbd5e1',
        fontSize: '16px',
        lineHeight: 1.6,
    },
    note: {
        marginTop: '12px',
        marginBottom: 0,
        color: '#93c5fd',
        fontSize: '14px',
    },
    actions: {
        display: 'flex',
        gap: '10px',
        marginTop: '20px',
        flexWrap: 'wrap',
    },
    primaryBtn: {
        border: 'none',
        background: 'linear-gradient(135deg, #06b6d4, #2563eb)',
        color: '#fff',
        borderRadius: '10px',
        padding: '10px 14px',
        fontWeight: 700,
        cursor: 'pointer',
    },
    secondaryBtn: {
        border: '1px solid rgba(148,163,184,0.4)',
        background: 'transparent',
        color: '#e2e8f0',
        borderRadius: '10px',
        padding: '10px 14px',
        fontWeight: 600,
        cursor: 'pointer',
    },
    muted: {
        marginTop: '12px',
        color: '#94a3b8',
        fontSize: '14px',
    },
    spinner: {
        width: '40px',
        height: '40px',
        border: '2px solid rgba(56,189,248,0.35)',
        borderTopColor: '#38bdf8',
        borderRadius: '999px',
    },
};
