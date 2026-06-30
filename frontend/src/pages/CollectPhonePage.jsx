import { useMemo, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../stores/useAuthStore';
import usePageMeta from '../hooks/usePageMeta';

function isValidIndianMobile(value) {
    return /^[6-9]\d{9}$/.test(value.replace(/\D/g, ''));
}

export default function CollectPhonePage() {
    usePageMeta('Add Mobile Number | AlphaSync', 'Add your mobile number to continue to your account status.');

    const navigate = useNavigate();
    const user = useAuthStore((s) => s.user);
    const submitPhone = useAuthStore((s) => s.submitPhone);

    const [phone, setPhone] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const role = (user?.role || '').toLowerCase();
    const status = (user?.account_status || 'active').toLowerCase();
    const isActive = status === 'active' && user?.is_active !== false;

    const nextPath = useMemo(() => {
        if (role === 'admin') {
            return isActive ? '/admin/panel' : '/account-status';
        }
        return isActive ? '/dashboard' : '/account-status';
    }, [role, isActive]);

    if (!user) {
        return <Navigate to="/login" replace />;
    }

    if (role !== 'admin' && user?.phone) {
        if (isActive) {
            localStorage.setItem('alphasync_trading_mode', 'demo');
            localStorage.setItem('alphasync_onboarded', '1');
        }
        return <Navigate to={nextPath} replace />;
    }

    async function handleSubmit(e) {
        e.preventDefault();
        const digits = phone.replace(/\D/g, '').slice(0, 10);
        if (!isValidIndianMobile(digits)) {
            setError('Enter a valid 10-digit Indian mobile number (starts with 6–9).');
            return;
        }

        setLoading(true);
        setError('');
        try {
            await submitPhone(digits);
            if (isActive && role !== 'admin') {
                localStorage.setItem('alphasync_trading_mode', 'demo');
                localStorage.setItem('alphasync_onboarded', '1');
            }
            navigate(nextPath, { replace: true });
        } catch (err) {
            setError(err?.response?.data?.detail || err?.message || 'Failed to save phone number. Please try again.');
        } finally {
            setLoading(false);
        }
    }

    return (
        <div
            style={{
                minHeight: '100vh',
                background: 'radial-gradient(circle at 0% 0%, #122339 0%, #0b1020 45%, #080d18 100%)',
                color: '#e2e8f0',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '24px',
            }}
        >
            <form
                onSubmit={handleSubmit}
                style={{
                    width: '100%',
                    maxWidth: 640,
                    borderRadius: 18,
                    border: '1px solid rgba(148,163,184,0.2)',
                    background: 'linear-gradient(160deg, rgba(30,41,59,0.95), rgba(15,23,42,0.95))',
                    boxShadow: '0 28px 64px rgba(0,0,0,0.45)',
                    padding: 28,
                }}
            >
                <div
                    style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 8,
                        background: 'rgba(15,23,42,0.75)',
                        border: '1px solid #22d3ee',
                        color: '#22d3ee',
                        borderRadius: 999,
                        padding: '6px 12px',
                        fontSize: 13,
                        fontWeight: 700,
                        letterSpacing: 0.4,
                        textTransform: 'uppercase',
                    }}
                >
                    Contact Required
                </div>

                <h1 style={{ marginTop: 18, marginBottom: 10, fontSize: 34, lineHeight: 1.08 }}>
                    Add Mobile Number
                </h1>

                <p style={{ margin: 0, color: '#cbd5e1', fontSize: 16, lineHeight: 1.6 }}>
                    Enter your number once to continue. This will also appear in Admin Panel for account approval.
                </p>

                <div
                    style={{
                        marginTop: 22,
                        borderRadius: 12,
                        border: '1px solid rgba(148,163,184,0.18)',
                        background: 'rgba(2,6,23,0.5)',
                        padding: 14,
                        display: 'grid',
                        gap: 10,
                    }}
                >
                    <div style={{ fontSize: 13, color: '#94a3b8' }}>Mobile Number</div>
                    <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                        <div
                            style={{
                                border: '1px solid rgba(148,163,184,0.3)',
                                borderRadius: 10,
                                padding: '10px 12px',
                                color: '#cbd5e1',
                                background: 'rgba(15,23,42,0.65)',
                                fontWeight: 600,
                            }}
                        >
                            +91
                        </div>
                        <input
                            type="tel"
                            inputMode="numeric"
                            autoFocus
                            maxLength={10}
                            value={phone}
                            onChange={(e) => {
                                setError('');
                                setPhone(e.target.value.replace(/\D/g, '').slice(0, 10));
                            }}
                            placeholder="9876543210"
                            style={{
                                flex: 1,
                                border: `1px solid ${error ? '#ef4444' : 'rgba(148,163,184,0.3)'}`,
                                borderRadius: 10,
                                padding: '10px 12px',
                                color: '#e2e8f0',
                                background: 'rgba(15,23,42,0.65)',
                                outline: 'none',
                            }}
                        />
                    </div>
                    {error ? <div style={{ color: '#f87171', fontSize: 13 }}>{error}</div> : null}
                </div>

                <div style={{ display: 'flex', gap: 10, marginTop: 22, flexWrap: 'wrap' }}>
                    <button
                        type="submit"
                        disabled={loading || phone.length !== 10}
                        style={{
                            border: 'none',
                            background: loading || phone.length !== 10
                                ? 'rgba(34,211,238,0.35)'
                                : 'linear-gradient(135deg, #06b6d4, #0284c7)',
                            color: '#fff',
                            borderRadius: 10,
                            padding: '10px 16px',
                            fontWeight: 700,
                            cursor: loading || phone.length !== 10 ? 'not-allowed' : 'pointer',
                        }}
                    >
                        {loading ? 'Saving...' : 'Continue'}
                    </button>
                </div>
            </form>
        </div>
    );
}
