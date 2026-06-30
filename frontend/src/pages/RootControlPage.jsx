import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import { Crown, FileText, History, Loader2, RefreshCw, Settings2, ArrowLeft } from 'lucide-react';
import adminApi from '../services/adminApi';

function parseApiError(error, fallback = 'Request failed') {
    return error?.response?.data?.detail || error?.message || fallback;
}

function safeDate(value) {
    if (!value) return '—';
    let raw = value;
    if (typeof raw === 'string' && !/Z$|[+\-]\d{2}:\d{2}$/.test(raw)) {
        raw = raw + 'Z';
    }
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleString();
}

function formatMoney(value) {
    const numericValue = Number(value || 0);
    if (!Number.isFinite(numericValue)) return '₹0.00';
    return `₹${numericValue.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export default function RootControlPage() {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();

    const [bootLoading, setBootLoading] = useState(true);
    const [accessDenied, setAccessDenied] = useState(false);
    const [users, setUsers] = useState([]);
    const [selectedUserId, setSelectedUserId] = useState(searchParams.get('user') || '');
    const [detailLoading, setDetailLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [userDetail, setUserDetail] = useState(null);

    const [draft, setDraft] = useState({
        available_capital: '',
        virtual_capital: '',
        total_pnl: '',
        total_pnl_percent: '',
        note: '',
    });

    const hasSelectedUser = Boolean(selectedUserId);
    const recentOrders = userDetail?.recent_orders || [];
    const transactions = userDetail?.transactions || [];
    const holdings = userDetail?.holdings || [];
    const performance = userDetail?.performance || {};

    const selectedUserName = useMemo(() => {
        const user = users.find((u) => String(u.id) === String(selectedUserId));
        if (!user) return 'Select a user';
        return user.full_name || user.username || user.email || 'Selected user';
    }, [users, selectedUserId]);

    const loadSelectedUserDetail = useCallback(async (userId) => {
        if (!userId) {
            setUserDetail(null);
            return;
        }
        setDetailLoading(true);
        try {
            const { data } = await adminApi.getUserDetail(userId);
            setUserDetail(data || null);
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to load user detail'));
            setUserDetail(null);
        } finally {
            setDetailLoading(false);
        }
    }, []);

    const bootstrap = useCallback(async () => {
        setBootLoading(true);
        try {
            const [{ data: statsData }, { data: usersData }] = await Promise.all([
                adminApi.getDashboardStats(),
                adminApi.listUsers({ page: 1, per_page: 200 }),
            ]);

            if (!['root', 'max'].includes(String(statsData?.admin_level || '').toLowerCase())) {
                setAccessDenied(true);
                return;
            }

            const incomingUsers = Array.isArray(usersData?.users)
                ? usersData.users
                : Array.isArray(usersData)
                    ? usersData
                    : [];

            setUsers(incomingUsers);

            const preselected = searchParams.get('user') || selectedUserId;
            if (preselected) {
                setSelectedUserId(String(preselected));
            } else if (incomingUsers.length > 0) {
                setSelectedUserId(String(incomingUsers[0].id));
            }
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to open root control center'));
            navigate('/admin/panel', { replace: true });
        } finally {
            setBootLoading(false);
        }
    }, [navigate, searchParams, selectedUserId]);

    useEffect(() => {
        bootstrap();
    }, [bootstrap]);

    useEffect(() => {
        loadSelectedUserDetail(selectedUserId);
    }, [selectedUserId, loadSelectedUserDetail]);

    useEffect(() => {
        setDraft({
            available_capital: userDetail?.portfolio?.available_capital ?? '',
            virtual_capital: userDetail?.virtual_capital ?? '',
            total_pnl: userDetail?.portfolio?.total_pnl ?? '',
            total_pnl_percent: userDetail?.portfolio?.total_pnl_percent ?? '',
            note: '',
        });
    }, [userDetail]);

    const handleSave = async () => {
        if (!hasSelectedUser) {
            toast.error('Select a user first');
            return;
        }

        const payload = {
            available_capital: draft.available_capital === '' ? undefined : Number(draft.available_capital),
            virtual_capital: draft.virtual_capital === '' ? undefined : Number(draft.virtual_capital),
            total_pnl: draft.total_pnl === '' ? undefined : Number(draft.total_pnl),
            total_pnl_percent: draft.total_pnl_percent === '' ? undefined : Number(draft.total_pnl_percent),
            note: draft.note?.trim() || undefined,
        };

        if (Object.values(payload).every((value) => value === undefined)) {
            toast.error('Enter at least one financial value');
            return;
        }

        if (!window.confirm('Apply these financial overrides to this user?')) return;

        setSaving(true);
        try {
            await adminApi.updateUserFinancials(selectedUserId, payload);
            toast.success('User financial snapshot updated');
            await loadSelectedUserDetail(selectedUserId);
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to update financials'));
        } finally {
            setSaving(false);
        }
    };

    if (bootLoading) {
        return (
            <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--bg-base)' }}>
                <Loader2 className="animate-spin" style={{ color: 'var(--brand)' }} />
            </div>
        );
    }

    if (accessDenied) {
        return (
            <div className="min-h-screen p-4 sm:p-6" style={{ background: 'var(--bg-base)' }}>
                <div className="glass-card p-6 max-w-2xl mx-auto">
                    <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>Root or Max Access Required</h1>
                    <p className="mt-2 text-sm" style={{ color: 'var(--text-muted)' }}>
                        This page is available only for root or max admins.
                    </p>
                    <button className="btn-primary mt-4" onClick={() => navigate('/admin/panel', { replace: true })}>
                        Back to Admin Panel
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen p-3 sm:p-4 md:p-5 lg:p-6" style={{ background: 'var(--bg-base)', color: 'var(--text-primary)' }}>
            <header className="flex flex-wrap items-start sm:items-center justify-between gap-3 mb-4">
                <div>
                    <div className="flex items-center gap-2 mb-1">
                        <Crown size={14} style={{ color: '#f59e0b' }} />
                        <span className="text-xs font-bold uppercase tracking-widest" style={{ color: 'var(--text-muted)' }}>Root Workspace</span>
                    </div>
                    <h1 className="text-xl sm:text-2xl font-bold">Root Control Center</h1>
                    <p className="text-xs sm:text-sm" style={{ color: 'var(--text-muted)' }}>Focused controls for overrides, trade history and diagnostics.</p>
                </div>
                <button className="btn-secondary flex items-center gap-2 text-sm" onClick={() => navigate('/admin/panel')}>
                    <ArrowLeft size={14} /> Back to Admin Panel
                </button>
            </header>

            <section className="glass-card p-4 sm:p-5">
                <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 sm:gap-4">
                    <div className="xl:col-span-1 space-y-3 sm:space-y-4">
                        <div className="rounded-xl p-3 sm:p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                            <div className="text-xs font-bold uppercase tracking-widest mb-2" style={{ color: 'var(--text-muted)' }}>Pick User</div>
                            <select className="input-field" value={selectedUserId} onChange={(e) => setSelectedUserId(String(e.target.value || ''))}>
                                {users.map((u) => (
                                    <option key={u.id} value={String(u.id)}>{u.full_name || u.username || u.email}</option>
                                ))}
                            </select>
                            <div className="text-[11px] mt-2" style={{ color: 'var(--text-muted)' }}>Current: {selectedUserName}</div>
                        </div>

                        <div className="rounded-xl p-3 sm:p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                            <div className="grid grid-cols-2 gap-2 sm:gap-3">
                                {[
                                    { label: 'Available Capital', value: hasSelectedUser ? formatMoney(userDetail?.portfolio?.available_capital) : '—' },
                                    { label: 'Total P&L', value: hasSelectedUser ? formatMoney(userDetail?.portfolio?.total_pnl) : '—' },
                                    { label: 'Virtual Capital', value: hasSelectedUser ? formatMoney(userDetail?.virtual_capital) : '—' },
                                    { label: 'P&L %', value: hasSelectedUser ? `${Number(userDetail?.portfolio?.total_pnl_percent || 0).toFixed(2)}%` : '—' },
                                    { label: 'Holdings', value: hasSelectedUser ? holdings.length : '—' },
                                    { label: 'Transactions', value: hasSelectedUser ? transactions.length : '—' },
                                    { label: 'Orders', value: hasSelectedUser ? recentOrders.length : '—' },
                                    { label: 'Active Sessions', value: hasSelectedUser ? (userDetail?.monitoring?.active_devices ?? 0) : '—' },
                                ].map(({ label, value }) => (
                                    <div key={label} className="p-2.5 rounded-lg" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
                                        <div className="text-[11px] font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--text-muted)' }}>{label}</div>
                                        <div className="text-sm font-semibold font-mono break-all">{value}</div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    <div className="xl:col-span-2 space-y-3 sm:space-y-4">
                        <div className="rounded-xl p-3 sm:p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                            <div className="flex items-center justify-between gap-3 mb-3">
                                <h3 className="text-sm font-bold">Financial Overrides</h3>
                                <button className="btn-secondary flex items-center gap-2 text-xs px-3 py-1.5" style={{ height: 'auto' }} onClick={() => loadSelectedUserDetail(selectedUserId)} disabled={detailLoading || !selectedUserId}>
                                    {detailLoading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Refresh
                                </button>
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-3">
                                {[
                                    { key: 'available_capital', label: 'Available Capital' },
                                    { key: 'virtual_capital', label: 'Virtual Capital' },
                                    { key: 'total_pnl', label: 'Total P&L' },
                                    { key: 'total_pnl_percent', label: 'P&L %' },
                                ].map((field) => (
                                    <div key={field.key}>
                                        <label className="label-text">{field.label}</label>
                                        <input
                                            className="input-field"
                                            type="number"
                                            disabled={!hasSelectedUser}
                                            value={draft[field.key]}
                                            onChange={(e) => setDraft((prev) => ({ ...prev, [field.key]: e.target.value }))}
                                            placeholder={field.label}
                                        />
                                    </div>
                                ))}
                            </div>
                            <div className="mt-3">
                                <label className="label-text">Admin note</label>
                                <textarea
                                    className="input-field min-h-[88px]"
                                    disabled={!hasSelectedUser}
                                    value={draft.note}
                                    onChange={(e) => setDraft((prev) => ({ ...prev, note: e.target.value }))}
                                    placeholder="Why was this override applied?"
                                />
                            </div>
                            <div className="flex flex-wrap gap-2 mt-3">
                                <button className="btn-primary flex items-center gap-2 text-sm" onClick={handleSave} disabled={saving || !selectedUserId}>
                                    {saving ? <Loader2 size={14} className="animate-spin" /> : <Settings2 size={14} />} Save Overrides
                                </button>
                            </div>
                        </div>

                        <div className="rounded-xl p-3 sm:p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                            <h3 className="text-sm font-bold mb-3 flex items-center gap-2"><FileText size={14} style={{ color: 'var(--brand)' }} /> Trade History</h3>
                            {!hasSelectedUser ? (
                                <div className="text-sm" style={{ color: 'var(--text-muted)' }}>Select a user to view history.</div>
                            ) : detailLoading ? (
                                <div className="text-sm" style={{ color: 'var(--text-muted)' }}>Loading trades...</div>
                            ) : recentOrders.length ? (
                                <div className="overflow-x-auto rounded-xl" style={{ border: '1px solid var(--border)' }}>
                                    <table className="w-full" style={{ borderCollapse: 'collapse', tableLayout: 'fixed', minWidth: 760 }}>
                                        <thead>
                                            <tr style={{ background: 'var(--bg-surface)' }}>
                                                {['Time', 'Symbol', 'Side', 'Type', 'Qty', 'Status', 'Price'].map((h) => (
                                                    <th key={h} className="text-left px-3 py-2 text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)', borderBottom: '1px solid var(--border)' }}>{h}</th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {recentOrders.slice(0, 12).map((order) => (
                                                <tr key={order.id} style={{ borderBottom: '1px solid var(--border)' }}>
                                                    <td className="px-3 py-2 text-xs font-mono" style={{ color: 'var(--text-muted)' }}>{safeDate(order.created_at)}</td>
                                                    <td className="px-3 py-2 text-xs font-semibold">{order.symbol}</td>
                                                    <td className="px-3 py-2 text-xs font-semibold" style={{ color: order.side === 'BUY' ? '#10b981' : '#ef4444' }}>{order.side}</td>
                                                    <td className="px-3 py-2 text-xs" style={{ color: 'var(--text-secondary)' }}>{order.order_type}</td>
                                                    <td className="px-3 py-2 text-xs font-mono" style={{ color: 'var(--text-secondary)' }}>{order.quantity}</td>
                                                    <td className="px-3 py-2 text-xs" style={{ color: 'var(--text-secondary)' }}>{order.status}</td>
                                                    <td className="px-3 py-2 text-xs font-mono" style={{ color: 'var(--text-secondary)' }}>{formatMoney(order.filled_price ?? order.price)}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            ) : (
                                <div className="text-sm" style={{ color: 'var(--text-muted)' }}>No order history found for this user.</div>
                            )}
                        </div>

                        <div className="rounded-xl p-3 sm:p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                            <h3 className="text-sm font-bold mb-3 flex items-center gap-2"><History size={14} style={{ color: 'var(--brand)' }} /> Performance & Transactions</h3>
                            <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-3 mb-4">
                                {[
                                    { label: 'Filled Orders', value: hasSelectedUser ? (performance.filled_orders ?? 0) : '—' },
                                    { label: 'Open Orders', value: hasSelectedUser ? (performance.open_orders ?? 0) : '—' },
                                    { label: 'Cancelled', value: hasSelectedUser ? (performance.cancelled_orders ?? 0) : '—' },
                                    { label: 'Rejected', value: hasSelectedUser ? (performance.rejected_orders ?? 0) : '—' },
                                ].map(({ label, value }) => (
                                    <div key={label} className="p-3 rounded-lg" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
                                        <div className="text-[11px] font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--text-muted)' }}>{label}</div>
                                        <div className="text-lg font-bold font-mono">{value}</div>
                                    </div>
                                ))}
                            </div>
                            {!hasSelectedUser ? (
                                <div className="text-sm" style={{ color: 'var(--text-muted)' }}>Select a user to see transactions and performance.</div>
                            ) : transactions.length ? (
                                <div className="overflow-x-auto rounded-xl" style={{ border: '1px solid var(--border)' }}>
                                    <table className="w-full" style={{ borderCollapse: 'collapse', tableLayout: 'fixed', minWidth: 720 }}>
                                        <thead>
                                            <tr style={{ background: 'var(--bg-surface)' }}>
                                                {['Time', 'Symbol', 'Side', 'Qty', 'Value', 'Order ID'].map((h) => (
                                                    <th key={h} className="text-left px-3 py-2 text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)', borderBottom: '1px solid var(--border)' }}>{h}</th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {transactions.slice(0, 12).map((tx) => (
                                                <tr key={tx.id} style={{ borderBottom: '1px solid var(--border)' }}>
                                                    <td className="px-3 py-2 text-xs font-mono" style={{ color: 'var(--text-muted)' }}>{safeDate(tx.created_at)}</td>
                                                    <td className="px-3 py-2 text-xs font-semibold">{tx.symbol}</td>
                                                    <td className="px-3 py-2 text-xs font-semibold" style={{ color: tx.transaction_type === 'BUY' ? '#10b981' : '#ef4444' }}>{tx.transaction_type}</td>
                                                    <td className="px-3 py-2 text-xs font-mono" style={{ color: 'var(--text-secondary)' }}>{tx.quantity}</td>
                                                    <td className="px-3 py-2 text-xs font-mono" style={{ color: 'var(--text-secondary)' }}>{formatMoney(tx.total_value)}</td>
                                                    <td className="px-3 py-2 text-[11px] font-mono truncate" style={{ color: 'var(--text-muted)' }}>{tx.order_id || '—'}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            ) : (
                                <div className="text-sm" style={{ color: 'var(--text-muted)' }}>No transaction records found.</div>
                            )}
                        </div>
                    </div>
                </div>
            </section>
        </div>
    );
}
