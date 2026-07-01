import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import { useNavigate } from 'react-router-dom';
import {
    Shield, Users, Clock, UserCheck, UserX, RefreshCw, LogOut,
    Search, ChevronLeft, ChevronRight, AlertTriangle, Loader2,
    KeyRound, CheckCircle2, XCircle, Activity, Eye, X,
    Crown, UserPlus, Settings2, Trash2, ShieldCheck, EyeOff,
    FileText, History, Link2, Copy, Plus, Pencil, Download, Bookmark, Star
} from 'lucide-react';

import { useAuthStore } from '../stores/useAuthStore';
import adminApi, {
    clearAdminSessionToken,
    getAdminSessionToken,
    setAdminSessionToken,
} from '../services/adminApi';

const DEFAULT_ACTION_STATE = { durationDays: 30, reason: '', totpCode: '' };

const DEFAULT_USERS_DATA = {
    users: [],
    total: 0,
    page: 1,
    per_page: 25,
    total_pages: 1,
};

function normalizeUsersData(payload) {
    if (Array.isArray(payload)) {
        return {
            ...DEFAULT_USERS_DATA,
            users: payload,
            total: payload.length,
        };
    }

    if (!payload || typeof payload !== 'object') {
        return DEFAULT_USERS_DATA;
    }

    const users = Array.isArray(payload.users)
        ? payload.users
        : Array.isArray(payload.data)
            ? payload.data
            : [];

    const total = Number.isFinite(Number(payload.total))
        ? Number(payload.total)
        : users.length;
    const page = Number.isFinite(Number(payload.page)) ? Number(payload.page) : 1;
    const perPageRaw = payload.per_page ?? payload.perPage;
    const perPage = Number.isFinite(Number(perPageRaw)) ? Number(perPageRaw) : DEFAULT_USERS_DATA.per_page;
    const totalPagesRaw = payload.total_pages ?? payload.totalPages;
    const totalPages = Number.isFinite(Number(totalPagesRaw))
        ? Math.max(1, Number(totalPagesRaw))
        : Math.max(1, Math.ceil(total / Math.max(1, perPage)));

    return {
        users,
        total,
        page,
        per_page: perPage,
        total_pages: totalPages,
    };
}

function parseApiError(error, fallback = 'Request failed') {
    return error?.response?.data?.detail || error?.message || fallback;
}

function normalizeAdminLevel(level) {
    const normalized = String(level || '').trim().toLowerCase();
    if (['root', 'max', 'manage', 'view_only'].includes(normalized)) return normalized;
    return 'manage';
}

function safeDate(value) {
    if (!value) return '—';
    // Backend stores timestamps in UTC without timezone suffix.
    // Append "Z" so the browser correctly converts UTC → local time (IST).
    let raw = value;
    if (typeof raw === 'string' && !/Z$|[+\-]\d{2}:\d{2}$/.test(raw)) {
        raw = raw + 'Z';
    }
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleString();
}

function safeDateTimeParts(value) {
    if (!value) return { date: '—', time: '—' };
    let raw = value;
    if (typeof raw === 'string' && !/Z$|[+\-]\d{2}:\d{2}$/.test(raw)) {
        raw = raw + 'Z';
    }
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return { date: '—', time: '—' };
    return {
        date: d.toLocaleDateString(),
        time: d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    };
}

function formatLastOnline(value, isOnline, accountStatus) {
    if ((accountStatus || '').toLowerCase() !== 'active') {
        return { label: '—', detail: 'Only for active users', tone: 'muted' };
    }
    if (!value) {
        return { label: 'Offline', detail: 'No activity yet', tone: 'muted' };
    }

    let raw = value;
    if (typeof raw === 'string' && !/Z$|[+\-]\d{2}:\d{2}$/.test(raw)) {
        raw = raw + 'Z';
    }
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) {
        return { label: 'Offline', detail: 'Invalid timestamp', tone: 'muted' };
    }

    if (isOnline) {
        return { label: 'Online', detail: 'Active now', tone: 'online' };
    }

    const diffSec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
    if (diffSec < 60) return { label: 'Last seen now', detail: d.toLocaleTimeString(), tone: 'recent' };

    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) {
        return { label: `Last seen ${diffMin}m ago`, detail: d.toLocaleTimeString(), tone: 'recent' };
    }

    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) {
        return { label: `Last seen ${diffHours}h ago`, detail: d.toLocaleTimeString(), tone: 'muted' };
    }

    const diffDays = Math.floor(diffHours / 24);
    return { label: `Last seen ${diffDays}d ago`, detail: d.toLocaleDateString(), tone: 'muted' };
}

function formatMoney(value) {
    const numericValue = Number(value || 0);
    if (!Number.isFinite(numericValue)) return '₹0.00';
    return `₹${numericValue.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function statusTone(status) {
    switch ((status || '').toLowerCase()) {
        case 'active': return { bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.3)', text: '#10b981' };
        case 'pending_approval': return { bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.3)', text: '#f59e0b' };
        case 'expired': return { bg: 'rgba(249,115,22,0.12)', border: 'rgba(249,115,22,0.3)', text: '#f97316' };
        case 'deactivated': return { bg: 'rgba(239,68,68,0.12)', border: 'rgba(239,68,68,0.3)', text: '#ef4444' };
        case 'deleted': return { bg: 'rgba(236,72,153,0.12)', border: 'rgba(236,72,153,0.3)', text: '#ec4899' };
        default: return { bg: 'rgba(148,163,184,0.12)', border: 'rgba(148,163,184,0.3)', text: '#94a3b8' };
    }
}

const LEVEL_COLORS = {
    root: { bg: 'rgba(245,158,11,0.12)', border: 'rgba(245,158,11,0.3)', text: '#f59e0b', icon: Crown },
    max: { bg: 'rgba(249,115,22,0.12)', border: 'rgba(249,115,22,0.3)', text: '#f97316', icon: Crown },
    manage: { bg: 'rgba(16,185,129,0.12)', border: 'rgba(16,185,129,0.3)', text: '#10b981', icon: ShieldCheck },
    view_only: { bg: 'rgba(148,163,184,0.12)', border: 'rgba(148,163,184,0.3)', text: '#94a3b8', icon: EyeOff },
};

function StatusPill({ status }) {
    const tone = statusTone(status);
    const label = (status || 'unknown').toLowerCase() === 'pending_approval'
        ? 'pending'
        : (status || 'unknown').replaceAll('_', ' ');
    return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold uppercase tracking-wider whitespace-nowrap"
            style={{ background: tone.bg, border: `1px solid ${tone.border}`, color: tone.text }}>
            <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: tone.text }} />
            {label}
        </span>
    );
}

function LevelPill({ level }) {
    const cfg = LEVEL_COLORS[level] || LEVEL_COLORS.view_only;
    const Icon = cfg.icon;
    return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold uppercase tracking-wider whitespace-nowrap"
            style={{ background: cfg.bg, border: `1px solid ${cfg.border}`, color: cfg.text }}>
            <Icon size={12} />
            {(level || 'unknown').replace('_', ' ')}
        </span>
    );
}

function StatCard({ icon: Icon, label, value, color, subtext }) {
    return (
        <div className="admin-mini-stat flex flex-col gap-1.5 sm:gap-2">
            <div className="flex items-center gap-2">
                <Icon size={16} style={{ color: color || 'var(--brand)' }} />
                <span className="text-[10px] sm:text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>{label}</span>
            </div>
            <div className="text-xl sm:text-2xl lg:text-3xl font-extrabold font-mono" style={{ color: color || 'var(--text-primary)' }}>{value}</div>
            {subtext ? <div className="text-[11px] sm:text-xs" style={{ color: 'var(--text-muted)' }}>{subtext}</div> : null}
        </div>
    );
}

function RatingStars({ rating }) {
    const safeRating = Math.max(0, Math.min(5, Number(rating) || 0));
    return (
        <span className="inline-flex items-center gap-0.5">
            {Array.from({ length: 5 }, (_, index) => (
                <span
                    key={index}
                    style={{ color: index < safeRating ? '#FBB724' : '#94a3b8', fontSize: 14, lineHeight: 1 }}
                >
                    {index < safeRating ? '★' : '☆'}
                </span>
            ))}
        </span>
    );
}

function FeedbackCell({ rating, comment }) {
    if (!rating) {
        return (
            <div className="flex flex-col leading-tight">
                <span style={{ color: 'var(--text-muted)' }}>—</span>
                <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>No feedback</span>
            </div>
        );
    }

    const cleanComment = String(comment || '').trim();
    if (!cleanComment) {
        return <em style={{ color: 'var(--text-muted)' }}>No comment</em>;
    }

    const shortComment = cleanComment.length > 40 ? `${cleanComment.slice(0, 40)}...` : cleanComment;
    return <span title={cleanComment} style={{ color: 'var(--text-secondary)' }}>{shortComment}</span>;
}

/* ── Manage User Modal ─────────────────────────────────────────────── */
function ManageUserModal({ user: selectedUser, userDetail, detailLoading, actionState, setActionState, onAction, onClose, actionLoading }) {
    if (!selectedUser) return null;
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }} onClick={onClose}>
            <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl animate-slide-up"
                style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', boxShadow: '0 24px 64px rgba(0,0,0,0.5)' }}
                onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center justify-between p-5" style={{ borderBottom: '1px solid var(--border)' }}>
                    <div className="flex items-center gap-3 min-w-0">
                        <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0" style={{ background: 'var(--brand-glow)' }}>
                            <UserCheck size={20} style={{ color: 'var(--brand)' }} />
                        </div>
                        <div className="min-w-0">
                            <h2 className="text-lg font-bold truncate" style={{ color: 'var(--text-primary)' }}>Manage User</h2>
                            <p className="text-sm truncate" style={{ color: 'var(--text-secondary)' }}>{selectedUser.email}</p>
                        </div>
                    </div>
                    <button className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 transition-colors"
                        style={{ color: 'var(--text-muted)' }} onClick={onClose}><X size={18} /></button>
                </div>
                <div className="p-5 flex flex-col gap-5">
                    {/* ── Identity ── */}
                    <div>
                        <div className="text-xs font-bold uppercase tracking-widest mb-2" style={{ color: 'var(--text-muted)' }}>Identity &amp; Contact</div>
                        <div className="grid grid-cols-2 gap-3">
                            {[
                                { label: 'Full Name', content: <span className="text-sm font-medium">{selectedUser.full_name || '—'}</span> },
                                { label: 'Username', content: <span className="text-sm font-mono">{selectedUser.username || '—'}</span> },
                                { label: 'Email / Gmail', content: <span className="text-sm break-all">{selectedUser.email}</span> },
                                {
                                    label: 'Mobile Number', content: selectedUser.phone
                                        ? <span className="text-sm font-mono font-semibold" style={{ color: '#10b981' }}>{selectedUser.phone}</span>
                                        : <span className="text-sm font-semibold" style={{ color: '#f59e0b' }}>⚠ Not set</span>
                                },
                                { label: 'Auth Provider', content: <span className="text-sm">{selectedUser.auth_provider === 'google.com' ? '🔵 Google OAuth' : selectedUser.auth_provider === 'password' ? '🔑 Email / Password' : (selectedUser.auth_provider || '—')}</span> },
                                {
                                    label: 'Email Verified', content: selectedUser.is_verified
                                        ? <span className="flex items-center gap-1 font-semibold text-sm" style={{ color: '#10b981' }}><CheckCircle2 size={13} /> Verified</span>
                                        : <span className="flex items-center gap-1 font-semibold text-sm" style={{ color: '#ef4444' }}><XCircle size={13} /> Unverified</span>
                                },
                            ].map(({ label, content }) => (
                                <div key={label} className="p-3 rounded-xl" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                                    <div className="text-xs font-semibold uppercase tracking-wider mb-1.5" style={{ color: 'var(--text-muted)' }}>{label}</div>
                                    {content}
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* ── Account Status ── */}
                    <div>
                        <div className="text-xs font-bold uppercase tracking-widest mb-2" style={{ color: 'var(--text-muted)' }}>Account Status &amp; Dates</div>
                        <div className="grid grid-cols-2 gap-3">
                            {[
                                { label: 'Status', content: <StatusPill status={selectedUser.account_status} /> },
                                {
                                    label: 'Active', content: selectedUser.is_active
                                        ? <span className="flex items-center gap-1.5 font-semibold text-sm" style={{ color: '#10b981' }}><CheckCircle2 size={14} /> Yes</span>
                                        : <span className="flex items-center gap-1.5 font-semibold text-sm" style={{ color: '#ef4444' }}><XCircle size={14} /> No</span>
                                },
                                { label: 'Registered On', content: <span className="text-xs font-mono">{safeDate(selectedUser.created_at)}</span> },
                                { label: 'Last Updated', content: <span className="text-xs font-mono">{safeDate(selectedUser.updated_at)}</span> },
                                { label: 'Access Expires', content: <span className="text-xs font-mono">{safeDate(selectedUser.access_expires_at)}</span> },
                                { label: 'Approved At', content: <span className="text-xs font-mono">{safeDate(selectedUser.approved_at)}</span> },
                            ].map(({ label, content }) => (
                                <div key={label} className="p-3 rounded-xl" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                                    <div className="text-xs font-semibold uppercase tracking-wider mb-1.5" style={{ color: 'var(--text-muted)' }}>{label}</div>
                                    {content}
                                </div>
                            ))}
                        </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div>
                            <label className="label-text">Duration (days)</label>
                            <input className="input-field" type="number" min={1} max={365} value={actionState.durationDays}
                                onChange={(e) => setActionState((p) => ({ ...p, durationDays: Number(e.target.value || 1) }))} />
                        </div>
                        <div>
                            <label className="label-text">Deactivation Reason</label>
                            <input className="input-field" value={actionState.reason} placeholder="Optional reason" maxLength={500}
                                onChange={(e) => setActionState((p) => ({ ...p, reason: e.target.value }))} />
                        </div>
                        <div>
                            <label className="label-text">TOTP For Deactivate/Delete</label>
                            <input className="input-field" value={actionState.totpCode} placeholder="Required to deactivate" inputMode="numeric"
                                onChange={(e) => setActionState((p) => ({ ...p, totpCode: e.target.value.replace(/\D/g, '').slice(0, 8) }))} />
                        </div>
                    </div>
                    <div className="flex flex-wrap gap-2 pt-1">
                        <button className="admin-action-btn admin-action-btn--primary text-sm" disabled={actionLoading} onClick={() => onAction('approve')}>
                            {actionLoading ? <Loader2 size={14} className="animate-spin" /> : <UserCheck size={14} />} Approve</button>
                        <button className="admin-action-btn admin-action-btn--primary text-sm" disabled={actionLoading} onClick={() => onAction('reactivate')}>
                            {actionLoading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Reactivate</button>
                        <button className="admin-action-btn admin-action-btn--secondary text-sm" disabled={actionLoading} onClick={() => onAction('set-duration')}>
                            {actionLoading ? <Loader2 size={14} className="animate-spin" /> : <Clock size={14} />} Update Duration</button>
                        <button className="flex items-center gap-2 text-sm font-semibold px-5 py-2.5 rounded-full transition-all"
                            style={{ background: actionLoading ? '#6b7280' : 'linear-gradient(135deg, #ef4444, #b91c1c)', color: '#fff', opacity: actionLoading ? 0.6 : 1 }}
                            disabled={actionLoading} onClick={() => onAction('deactivate')}>
                            {actionLoading ? <Loader2 size={14} className="animate-spin" /> : <UserX size={14} />} Deactivate</button>
                        <button
                            className="admin-action-btn admin-action-btn--secondary text-sm"
                            disabled={actionLoading}
                            onClick={() => onAction('force-logout')}
                        >
                            {actionLoading ? <Loader2 size={14} className="animate-spin" /> : <LogOut size={14} />} Force Logout Sessions
                        </button>
                        <button
                            className="flex items-center gap-2 text-sm font-semibold px-5 py-2.5 rounded-full transition-all"
                            style={{ background: actionLoading ? 'rgba(185,28,28,0.4)' : 'rgba(185,28,28,0.18)', color: '#fca5a5', border: '1px solid rgba(239,68,68,0.35)' }}
                            disabled={actionLoading}
                            onClick={() => onAction('delete-user')}
                        >
                            {actionLoading ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />} Delete Permanently
                        </button>
                    </div>
                    <div className="rounded-xl p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                        <h3 className="text-sm font-bold mb-3 flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
                            <Activity size={14} style={{ color: 'var(--brand)' }} /> Detail Snapshot
                        </h3>
                        {detailLoading ? (
                            <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-muted)' }}><Loader2 size={14} className="animate-spin" /> Loading...</div>
                        ) : userDetail ? (
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                                {[
                                    { label: 'Portfolio Value', value: userDetail.portfolio?.current_value != null ? `₹${Number(userDetail.portfolio.current_value).toLocaleString()}` : '—' },
                                    { label: 'Capital', value: userDetail.portfolio?.available_capital != null ? `₹${Number(userDetail.portfolio.available_capital).toLocaleString()}` : '—' },
                                    { label: 'Holdings', value: userDetail.holdings?.length || 0 },
                                    { label: 'Orders', value: userDetail.recent_orders?.length || 0 },
                                    { label: 'Active Devices', value: userDetail.monitoring?.active_devices ?? 0 },
                                    { label: 'Recent Sessions', value: userDetail.monitoring?.recent_sessions ?? 0 },
                                    { label: 'Last Seen', value: safeDate(userDetail.monitoring?.last_seen_at) },
                                ].map(({ label, value }) => (
                                    <div key={label}>
                                        <div className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--text-muted)' }}>{label}</div>
                                        <div className="font-mono font-semibold text-sm">{value}</div>
                                    </div>
                                ))}
                            </div>
                        ) : <div className="text-sm" style={{ color: 'var(--text-muted)' }}>No details available.</div>}
                    </div>

                    <div className="rounded-xl p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                        <h3 className="text-sm font-bold mb-3" style={{ color: 'var(--text-primary)' }}>Session Monitor</h3>
                        {detailLoading ? (
                            <div className="text-sm" style={{ color: 'var(--text-muted)' }}>Loading sessions...</div>
                        ) : (userDetail?.sessions?.length ? (
                            <div className="space-y-2 max-h-44 overflow-y-auto pr-1">
                                {userDetail.sessions.map((s) => (
                                    <div key={s.id} className="p-2.5 rounded-lg" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
                                        <div className="flex items-center justify-between gap-2 text-xs">
                                            <span className="font-mono truncate" style={{ color: 'var(--text-secondary)' }}>{s.ip_address || 'Unknown IP'}</span>
                                            <span className="px-2 py-0.5 rounded-full" style={{
                                                background: s.is_active ? 'rgba(16,185,129,0.12)' : 'rgba(148,163,184,0.12)',
                                                color: s.is_active ? '#10b981' : 'var(--text-muted)'
                                            }}>
                                                {s.is_active ? 'ACTIVE' : 'INACTIVE'}
                                            </span>
                                        </div>
                                        <div className="text-[11px] mt-1 truncate" style={{ color: 'var(--text-muted)' }}>{s.user_agent || 'Unknown device'}</div>
                                        <div className="text-[11px] mt-1 font-mono" style={{ color: 'var(--text-muted)' }}>
                                            Last seen: {safeDate(s.last_seen_at)}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <div className="text-sm" style={{ color: 'var(--text-muted)' }}>No session activity found.</div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}

function RootControlSection({
    users,
    selectedUserId,
    onSelectUser,
    userDetail,
    detailLoading,
    onRefreshDetail,
    onSaveFinancials,
    saving,
}) {
    const [draft, setDraft] = useState({
        available_capital: '',
        virtual_capital: '',
        total_pnl: '',
        total_pnl_percent: '',
        note: '',
    });

    const hasSelectedUser = Boolean(selectedUserId);

    useEffect(() => {
        setDraft({
            available_capital: userDetail?.portfolio?.available_capital ?? '',
            virtual_capital: userDetail?.virtual_capital ?? '',
            total_pnl: userDetail?.portfolio?.total_pnl ?? '',
            total_pnl_percent: userDetail?.portfolio?.total_pnl_percent ?? '',
            note: '',
        });
    }, [userDetail]);

    const performance = userDetail?.performance || {};

    const handleSave = async () => {
        if (!selectedUserId) {
            toast.error('Select a user first');
            return;
        }

        const numericFields = [
            ['available_capital', 'Available Capital'],
            ['virtual_capital', 'Virtual Capital'],
            ['total_pnl', 'Total P&L'],
            ['total_pnl_percent', 'P&L %'],
        ];

        for (const [key, label] of numericFields) {
            const rawValue = draft[key];
            if (rawValue === '' || rawValue === null || rawValue === undefined) continue;
            if (!Number.isFinite(Number(rawValue))) {
                toast.error(`${label} must be a valid number`);
                return;
            }
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
        await onSaveFinancials(payload);
    };

    const recentOrders = userDetail?.recent_orders || [];
    const transactions = userDetail?.transactions || [];
    const holdings = userDetail?.holdings || [];

    return (
        <section className="admin-card p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                <div>
                    <div className="flex items-center gap-2 mb-1">
                        <Crown size={14} style={{ color: '#f59e0b' }} />
                        <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>Root Control Center</h2>
                    </div>
                    <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                        Absolute control for root admins: inspect trades, monitor performance, and override capital or P&amp;L.
                    </p>
                </div>
                <button className="admin-action-btn admin-action-btn--secondary text-xs px-3 py-1.5" style={{ height: 'auto' }} onClick={onRefreshDetail} disabled={detailLoading || !selectedUserId}>
                    {detailLoading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Refresh User
                </button>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 sm:gap-4">
                <div className="xl:col-span-1 space-y-3 sm:space-y-4">
                    <div className="rounded-xl p-3 sm:p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                        <div className="text-xs font-bold uppercase tracking-widest mb-2" style={{ color: 'var(--text-muted)' }}>Pick User</div>
                        <select
                            className="input-field"
                            value={selectedUserId || ''}
                            onChange={(e) => onSelectUser(e.target.value)}
                        >
                            <option value="">Select a user</option>
                            {users.map((u) => (
                                <option key={u.id} value={String(u.id)}>
                                    {u.full_name || u.username || u.email}
                                </option>
                            ))}
                        </select>
                        <div className="text-[11px] mt-2" style={{ color: 'var(--text-muted)' }}>
                            Use the table above or this selector to load a user profile for editing.
                        </div>
                    </div>

                    <div className="rounded-xl p-3 sm:p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                        <div className="grid grid-cols-2 gap-2 sm:gap-3">
                            {[
                                { label: 'Available Capital', value: hasSelectedUser ? formatMoney(userDetail?.portfolio?.available_capital) : '—' },
                                { label: 'Total P&amp;L', value: hasSelectedUser ? formatMoney(userDetail?.portfolio?.total_pnl) : '—' },
                                { label: 'Virtual Capital', value: hasSelectedUser ? formatMoney(userDetail?.virtual_capital) : '—' },
                                { label: 'P&amp;L %', value: hasSelectedUser ? `${Number(userDetail?.portfolio?.total_pnl_percent || 0).toFixed(2)}%` : '—' },
                                { label: 'Holdings', value: hasSelectedUser ? holdings.length : '—' },
                                { label: 'Transactions', value: hasSelectedUser ? transactions.length : '—' },
                                { label: 'Orders', value: hasSelectedUser ? recentOrders.length : '—' },
                                { label: 'Active Sessions', value: hasSelectedUser ? (userDetail?.monitoring?.active_devices ?? 0) : '—' },
                            ].map(({ label, value }) => (
                                <div key={label} className="p-2.5 rounded-lg" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
                                    <div className="text-[11px] font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--text-muted)' }}>{label}</div>
                                    <div className="text-sm font-semibold font-mono break-all" style={{ color: 'var(--text-primary)' }}>{value}</div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

                <div className="xl:col-span-2 space-y-3 sm:space-y-4">
                    <div className="rounded-xl p-3 sm:p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                        <div className="flex items-center justify-between gap-3 mb-3">
                            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>Financial Overrides</h3>
                            <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: 'var(--brand-glow)', color: 'var(--brand)' }}>Root only</span>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-3">
                            {[
                                { key: 'available_capital', label: 'Available Capital', type: 'number' },
                                { key: 'virtual_capital', label: 'Virtual Capital', type: 'number' },
                                { key: 'total_pnl', label: 'Total P&amp;L', type: 'number' },
                                { key: 'total_pnl_percent', label: 'P&amp;L %', type: 'number' },
                            ].map((field) => (
                                <div key={field.key}>
                                    <label className="label-text">{field.label}</label>
                                    <input
                                        className="input-field"
                                        type={field.type}
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
                            <button className="admin-action-btn admin-action-btn--primary text-sm" onClick={handleSave} disabled={saving || !selectedUserId}>
                                {saving ? <Loader2 size={14} className="animate-spin" /> : <Settings2 size={14} />} Save Overrides
                            </button>
                        </div>
                    </div>

                    <div className="rounded-xl p-3 sm:p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                        <h3 className="text-sm font-bold mb-3 flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
                            <FileText size={14} style={{ color: 'var(--brand)' }} /> Trade History
                        </h3>
                        {!hasSelectedUser ? (
                            <div className="text-sm" style={{ color: 'var(--text-muted)' }}>Click a <strong>Control</strong> button in the table to load a user here.</div>
                        ) : detailLoading ? (
                            <div className="text-sm" style={{ color: 'var(--text-muted)' }}>Loading trades...</div>
                        ) : recentOrders.length ? (
                            <div className="overflow-x-auto rounded-xl" style={{ border: '1px solid var(--border)' }}>
                                <table className="w-full" style={{ borderCollapse: 'collapse', tableLayout: 'fixed', minWidth: 780 }}>
                                    <colgroup>
                                        <col style={{ width: '18%' }} /><col style={{ width: '12%' }} /><col style={{ width: '11%' }} />
                                        <col style={{ width: '11%' }} /><col style={{ width: '12%' }} /><col style={{ width: '16%' }} />
                                        <col style={{ width: '10%' }} />
                                    </colgroup>
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
                                                <td className="px-3 py-2 text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>{order.symbol}</td>
                                                <td className="px-3 py-2 text-xs font-semibold" style={{ color: order.side === 'BUY' ? '#10b981' : '#ef4444' }}>{order.side}</td>
                                                <td className="px-3 py-2 text-xs" style={{ color: 'var(--text-secondary)' }}>{order.order_type}</td>
                                                <td className="px-3 py-2 text-xs font-mono" style={{ color: 'var(--text-secondary)' }}>{order.quantity}</td>
                                                <td className="px-3 py-2"><StatusPill status={order.status} /></td>
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
                        <h3 className="text-sm font-bold mb-3 flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
                            <History size={14} style={{ color: 'var(--brand)' }} /> Performance &amp; Transactions
                        </h3>
                        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-3 mb-4">
                            {[
                                { label: 'Filled Orders', value: hasSelectedUser ? (performance.filled_orders ?? 0) : '—' },
                                { label: 'Open Orders', value: hasSelectedUser ? (performance.open_orders ?? 0) : '—' },
                                { label: 'Cancelled', value: hasSelectedUser ? (performance.cancelled_orders ?? 0) : '—' },
                                { label: 'Rejected', value: hasSelectedUser ? (performance.rejected_orders ?? 0) : '—' },
                            ].map(({ label, value }) => (
                                <div key={label} className="p-3 rounded-lg" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
                                    <div className="text-[11px] font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--text-muted)' }}>{label}</div>
                                    <div className="text-lg font-bold font-mono" style={{ color: 'var(--text-primary)' }}>{value}</div>
                                </div>
                            ))}
                        </div>
                        {!hasSelectedUser ? (
                            <div className="text-sm" style={{ color: 'var(--text-muted)' }}>Select a user to see transactions and performance.</div>
                        ) : transactions.length ? (
                            <div className="overflow-x-auto rounded-xl" style={{ border: '1px solid var(--border)' }}>
                                <table className="w-full" style={{ borderCollapse: 'collapse', tableLayout: 'fixed', minWidth: 740 }}>
                                    <colgroup>
                                        <col style={{ width: '20%' }} /><col style={{ width: '14%' }} /><col style={{ width: '10%' }} />
                                        <col style={{ width: '10%' }} /><col style={{ width: '12%' }} /><col style={{ width: '18%' }} />
                                    </colgroup>
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
                                                <td className="px-3 py-2 text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>{tx.symbol}</td>
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
    );
}

/* ── Admin Management Modal (Root Only) ────────────────────────────── */
function AdminManagementModal({ admins, adminsLoading, onClose, onPromote, onUpdateLevel, onRevoke }) {
    const [promoteEmail, setPromoteEmail] = useState('');
    const [promoteLevel, setPromoteLevel] = useState('manage');
    const [promoting, setPromoting] = useState(false);

    async function handlePromote() {
        if (!promoteEmail.trim()) { toast.error('Enter an email address'); return; }
        setPromoting(true);
        try {
            await onPromote(promoteEmail.trim(), promoteLevel);
            setPromoteEmail('');
            setPromoteLevel('manage');
        } finally {
            setPromoting(false);
        }
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }} onClick={onClose}>
            <div className="w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-2xl animate-slide-up admin-card"
                style={{ boxShadow: '0 24px 64px rgba(0,0,0,0.5)' }}
                onClick={(e) => e.stopPropagation()}>
                {/* Header */}
                <div className="flex items-center justify-between p-5" style={{ borderBottom: '1px solid var(--border)' }}>
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: 'rgba(245,158,11,0.12)' }}>
                            <Crown size={20} style={{ color: '#f59e0b' }} />
                        </div>
                        <div>
                            <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>Admin Management</h2>
                            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Create, update, and revoke admin access</p>
                        </div>
                    </div>
                    <button className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors"
                        style={{ color: 'var(--text-muted)' }} onClick={onClose}><X size={18} /></button>
                </div>

                <div className="p-5 flex flex-col gap-5">
                    {/* Add New Admin */}
                    <div className="rounded-xl p-4" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                        <h3 className="text-sm font-bold mb-3 flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
                            <UserPlus size={14} style={{ color: 'var(--brand)' }} /> Add New Admin
                        </h3>
                        <div className="flex flex-wrap gap-3 items-end">
                            <div className="flex-1 min-w-[200px]">
                                <label className="label-text">User Email</label>
                                <input className="input-field" value={promoteEmail} placeholder="user@example.com"
                                    onChange={(e) => setPromoteEmail(e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && handlePromote()} />
                            </div>
                            <div className="w-[160px]">
                                <label className="label-text">Permission Level</label>
                                <select className="input-field" value={promoteLevel} onChange={(e) => setPromoteLevel(e.target.value)}>
                                    <option value="max">Max</option>
                                    <option value="manage">Manage</option>
                                    <option value="view_only">View Only</option>
                                </select>
                            </div>
                            <button className="admin-action-btn admin-action-btn--primary" onClick={handlePromote} disabled={promoting}>
                                {promoting ? <Loader2 size={14} className="animate-spin" /> : <UserPlus size={14} />}
                                Add Admin
                            </button>
                        </div>
                    </div>

                    {/* Admin List */}
                    <div>
                        <h3 className="text-sm font-bold mb-3 flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
                            <Shield size={14} style={{ color: 'var(--brand)' }} /> Current Admins
                        </h3>
                        {adminsLoading ? (
                            <div className="flex items-center gap-2 text-sm py-4" style={{ color: 'var(--text-muted)' }}>
                                <Loader2 size={14} className="animate-spin" /> Loading admins...
                            </div>
                        ) : admins.length === 0 ? (
                            <div className="text-sm py-4" style={{ color: 'var(--text-muted)' }}>No admins found.</div>
                        ) : (
                            <div className="flex flex-col gap-2">
                                {admins.map((a) => (
                                    <div key={a.id} className="flex items-center justify-between gap-3 p-3 rounded-xl transition-colors"
                                        style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                                        <div className="flex items-center gap-3 min-w-0">
                                            <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                                                style={{ background: a.is_root ? 'rgba(245,158,11,0.12)' : 'var(--brand-glow)' }}>
                                                {a.is_root ? <Crown size={16} style={{ color: '#f59e0b' }} /> : <Shield size={16} style={{ color: 'var(--brand)' }} />}
                                            </div>
                                            <div className="min-w-0">
                                                <div className="text-sm font-medium truncate">{a.full_name || a.username}</div>
                                                <div className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>{a.email}</div>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-2 flex-shrink-0">
                                            <LevelPill level={a.effective_level} />
                                            {!a.is_main_root && (
                                                <div className="flex gap-1">
                                                    <select
                                                        className="text-xs px-2 py-1 rounded-lg"
                                                        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
                                                        value={a.effective_level}
                                                        onChange={(e) => onUpdateLevel(a.id, e.target.value)}
                                                    >
                                                        <option value="max">Max</option>
                                                        <option value="manage">Manage</option>
                                                        <option value="view_only">View Only</option>
                                                    </select>
                                                    <button
                                                        className="w-7 h-7 rounded-lg flex items-center justify-center transition-colors"
                                                        style={{ color: '#ef4444', background: 'rgba(239,68,68,0.1)' }}
                                                        title="Revoke admin access"
                                                        onClick={() => {
                                                            if (window.confirm(`Revoke admin access for ${a.email}?`)) {
                                                                onRevoke(a.id);
                                                            }
                                                        }}
                                                    >
                                                        <Trash2 size={14} />
                                                    </button>
                                                </div>
                                            )}
                                            {a.is_main_root && (
                                                <span className="text-xs px-2 py-1 rounded-lg" style={{ color: 'var(--text-muted)' }}>Protected</span>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

/* ── 2FA Setup ─────────────────────────────────────────────────────── */
function AdminAuthSetup({ setupLoading, setupPayload, authCode, setAuthCode, onGenerate, onEnable }) {
    return (
        <section className="admin-card p-6 max-w-3xl animate-fade-in">
            <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: 'var(--brand-glow)' }}>
                    <KeyRound size={20} style={{ color: 'var(--brand)' }} />
                </div>
                <div>
                    <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>Admin 2FA Setup</h2>
                    <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Scan the secret in your authenticator app and verify to activate.</p>
                </div>
            </div>
            {!setupPayload ? (
                <button className="admin-action-btn admin-action-btn--primary" onClick={onGenerate} disabled={setupLoading}>
                    {setupLoading ? <span className="flex items-center gap-2"><Loader2 size={16} className="animate-spin" /> Generating...</span> : 'Generate 2FA Secret'}
                </button>
            ) : (
                <>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                        <div>
                            <label className="label-text">Manual Secret</label>
                            <div className="input-field font-mono text-sm break-all" style={{ height: 'auto', minHeight: 48 }}>{setupPayload.secret}</div>
                        </div>
                        <div>
                            <label className="label-text">Provisioning URI</label>
                            <textarea readOnly value={setupPayload.uri} className="input-field font-mono text-xs" style={{ height: 'auto', minHeight: 92, resize: 'vertical' }} />
                        </div>
                    </div>
                    <div className="flex gap-3 items-center flex-wrap">
                        <input value={authCode} onChange={(e) => setAuthCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
                            placeholder="Enter 6-digit code" className="input-field max-w-[200px]" inputMode="numeric" />
                        <button className="admin-action-btn admin-action-btn--primary" onClick={onEnable} disabled={setupLoading}>
                            {setupLoading ? <span className="flex items-center gap-2"><Loader2 size={16} className="animate-spin" /> Verifying...</span> : 'Enable 2FA'}
                        </button>
                    </div>
                </>
            )}
        </section>
    );
}

/* ── 2FA Verify ────────────────────────────────────────────────────── */
function AdminAuthVerify({ verifyLoading, authCode, setAuthCode, onVerify }) {
    return (
        <section className="admin-card p-6 max-w-xl animate-fade-in">
            <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: 'var(--brand-glow)' }}>
                    <Shield size={20} style={{ color: 'var(--brand)' }} />
                </div>
                <div>
                    <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>Admin 2FA Verification</h2>
                    <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Enter a fresh authenticator code to open a secure admin session.</p>
                </div>
            </div>
            <div className="flex gap-3 items-center flex-wrap">
                <input value={authCode} onChange={(e) => setAuthCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
                    placeholder="Enter 6-digit code" className="input-field max-w-[200px]" inputMode="numeric"
                    onKeyDown={(e) => e.key === 'Enter' && onVerify()} />
                <button className="admin-action-btn admin-action-btn--primary" onClick={onVerify} disabled={verifyLoading}>
                    {verifyLoading ? <span className="flex items-center gap-2"><Loader2 size={16} className="animate-spin" /> Verifying...</span> : 'Verify & Enter'}
                </button>
            </div>
        </section>
    );
}

/* ── Data Feed Configuration Modal (Root Only) ────────────────────────── */
function DataFeedModal({ config, draft, setDraft, loading, saving, onSave, onClose }) {
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }} onClick={onClose}>
            <div className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl animate-slide-up admin-card"
                style={{ boxShadow: '0 24px 64px rgba(0,0,0,0.5)' }}
                onClick={(e) => e.stopPropagation()}>
                {/* Header */}
                <div className="flex items-center justify-between p-5" style={{ borderBottom: '1px solid var(--border)' }}>
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: 'rgba(16,185,129,0.12)' }}>
                            <Activity size={20} style={{ color: '#10b981' }} />
                        </div>
                        <div>
                            <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>Data Feed Configuration</h2>
                            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Configure the live market data feed integration</p>
                        </div>
                    </div>
                    <button className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors hover:bg-white/5"
                        style={{ color: 'var(--text-muted)' }} onClick={onClose}><X size={18} /></button>
                </div>

                <div className="p-5 flex flex-col gap-4">
                    {/* Status panel */}
                    <div className="p-4 rounded-xl flex flex-col gap-1.5" 
                         style={{ 
                             background: 'rgba(255,255,255,0.02)', 
                             border: '1px solid var(--border)' 
                         }}>
                        <div className="flex justify-between items-center">
                            <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Connection Status</span>
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold"
                                  style={{
                                      background: config.connection_status === 'connected' ? 'rgba(16,185,129,0.12)' :
                                                  config.connection_status === 'connecting' ? 'rgba(245,158,11,0.12)' :
                                                  config.connection_status === 'error' ? 'rgba(239,68,68,0.12)' : 'rgba(148,163,184,0.12)',
                                      color: config.connection_status === 'connected' ? '#10b981' :
                                             config.connection_status === 'connecting' ? '#f59e0b' :
                                             config.connection_status === 'error' ? '#ef4444' : 'var(--text-muted)',
                                      border: config.connection_status === 'connected' ? '1px solid rgba(16,185,129,0.22)' :
                                              config.connection_status === 'connecting' ? '1px solid rgba(245,158,11,0.22)' :
                                              config.connection_status === 'error' ? '1px solid rgba(239,68,68,0.22)' : '1px solid var(--border)'
                                  }}>
                                <span className={`w-1.5 h-1.5 rounded-full ${config.connection_status === 'connected' ? 'bg-[#10b981] animate-pulse' : config.connection_status === 'connecting' ? 'bg-[#f59e0b] animate-bounce' : config.connection_status === 'error' ? 'bg-[#ef4444]' : 'bg-[var(--text-muted)]'}`}></span>
                                {config.connection_status ? config.connection_status.toUpperCase() : 'DISCONNECTED'}
                            </span>
                        </div>
                        {config.error_message && (
                            <div className="text-xs p-2.5 rounded-lg font-mono break-all mt-1" style={{ color: '#ef4444', background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.12)' }}>
                                {config.error_message}
                            </div>
                        )}
                    </div>

                    {/* Form fields */}
                    <div className="flex flex-col gap-3">
                        <div className="flex items-center justify-between p-3.5 rounded-xl transition-all" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                            <div>
                                <label className="text-sm font-bold block" style={{ color: 'var(--text-primary)' }}>Enable Live Feed</label>
                                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Toggle between live AMDP feed and local simulation clock.</span>
                            </div>
                            <label className="relative inline-flex items-center cursor-pointer">
                                <input type="checkbox" className="sr-only peer" checked={draft.is_enabled}
                                       onChange={(e) => setDraft(prev => ({ ...prev, is_enabled: e.target.checked }))} />
                                <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[#10b981]"></div>
                            </label>
                        </div>

                        <div>
                            <label className="label-text">API Base URL</label>
                            <input className="input-field" value={draft.base_url} placeholder="http://localhost:3000/api/v1"
                                   onChange={(e) => setDraft(prev => ({ ...prev, base_url: e.target.value }))} />
                        </div>

                        <div>
                            <label className="label-text">API Key</label>
                            <input className="input-field font-mono" value={draft.api_key} placeholder="AK_..."
                                   onChange={(e) => setDraft(prev => ({ ...prev, api_key: e.target.value }))} />
                        </div>

                        <div>
                            <label className="label-text">API Secret</label>
                            <input className="input-field font-mono" type="password" value={draft.api_secret} placeholder={config.api_secret ? "••••••••••••••••" : "sk_..."}
                                   onChange={(e) => setDraft(prev => ({ ...prev, api_secret: e.target.value }))} />
                            {config.api_secret && (
                                <span className="text-[11px] mt-1 block" style={{ color: 'var(--text-muted)' }}>
                                    API Secret is configured and encrypted. Leave blank to keep existing.
                                </span>
                            )}
                        </div>
                    </div>
                </div>

                {/* Footer */}
                <div className="flex items-center justify-end gap-2 p-5" style={{ borderTop: '1px solid var(--border)' }}>
                    <button className="admin-action-btn admin-action-btn--secondary" onClick={onClose} disabled={saving}>
                        Cancel
                    </button>
                    <button className="admin-action-btn admin-action-btn--primary" onClick={onSave} disabled={saving || loading}>
                        {saving ? (
                            <>
                                <Loader2 size={14} className="animate-spin" /> Saving & Connect...
                            </>
                        ) : (
                            'Save & Connect'
                        )}
                    </button>
                </div>
            </div>
        </div>
    );
}

/* ══════════════════════════════════════════════════════════════════════
   Main Admin Panel
   ══════════════════════════════════════════════════════════════════════ */
export default function AdminPanelPage() {
    const navigate = useNavigate();
    const user = useAuthStore((s) => s.user);
    const logout = useAuthStore((s) => s.logout);

    const [bootstrapping, setBootstrapping] = useState(true);
    const [authStage, setAuthStage] = useState('verify');
    const [setupPayload, setSetupPayload] = useState(null);
    const [setupLoading, setSetupLoading] = useState(false);
    const [verifyLoading, setVerifyLoading] = useState(false);
    const [authCode, setAuthCode] = useState('');
    const [adminLevel, setAdminLevel] = useState('manage');
    const [autoApprovalEnabled, setAutoApprovalEnabled] = useState(false);
    const [autoApprovalLoading, setAutoApprovalLoading] = useState(false);
    const [autoApprovalSaving, setAutoApprovalSaving] = useState(false);

    const [stats, setStats] = useState(null);
    const [feedbackSummary, setFeedbackSummary] = useState(null);
    const [usersData, setUsersData] = useState(DEFAULT_USERS_DATA);
    const [usersLoading, setUsersLoading] = useState(false);
    const [filters, setFilters] = useState({ status: '', search: '', groupId: 'normal', page: 1, perPage: 25 });
    const [draftFilters, setDraftFilters] = useState({ status: '', search: '', groupId: 'normal' });
    const [groupsList, setGroupsList] = useState([]);
    const [groupsLoading, setGroupsLoading] = useState(false);
    const [groupNameDraft, setGroupNameDraft] = useState('');
    const [selectedGroupForLink, setSelectedGroupForLink] = useState('');
    const [renameGroupDraft, setRenameGroupDraft] = useState('');
    const [groupActionLoading, setGroupActionLoading] = useState(false);
    const [excelExportLoading, setExcelExportLoading] = useState(false);
    const [userGroupDrafts, setUserGroupDrafts] = useState({});

    const [modalUserId, setModalUserId] = useState(null);
    const [selectedUserDetail, setSelectedUserDetail] = useState(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [actionState, setActionState] = useState(DEFAULT_ACTION_STATE);

    // Data feed configuration state (root only)
    const [showDataFeedModal, setShowDataFeedModal] = useState(false);
    const [dataFeedConfig, setDataFeedConfig] = useState({
        api_key: '',
        api_secret: '',
        base_url: 'http://localhost:3000/api/v1',
        is_enabled: false,
        connection_status: 'disconnected',
        error_message: null
    });
    const [dataFeedDraft, setDataFeedDraft] = useState({
        api_key: '',
        api_secret: '',
        base_url: 'http://localhost:3000/api/v1',
        is_enabled: false
    });
    const [dataFeedLoading, setDataFeedLoading] = useState(false);
    const [dataFeedSaving, setDataFeedSaving] = useState(false);

    const loadDataFeedConfig = useCallback(async () => {
        setDataFeedLoading(true);
        try {
            const { data } = await adminApi.getDataFeedConfig();
            if (data) {
                setDataFeedConfig(data);
                setDataFeedDraft({
                    api_key: data.api_key || '',
                    api_secret: data.api_secret || '',
                    base_url: data.base_url || 'http://localhost:3000/api/v1',
                    is_enabled: Boolean(data.is_enabled)
                });
            }
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to load data feed configuration'));
        } finally {
            setDataFeedLoading(false);
        }
    }, []);

    const openDataFeedModal = useCallback(() => {
        setShowDataFeedModal(true);
        loadDataFeedConfig();
    }, [loadDataFeedConfig]);

    const handleSaveDataFeed = useCallback(async () => {
        setDataFeedSaving(true);
        try {
            const { data } = await adminApi.updateDataFeedConfig(dataFeedDraft);
            if (data?.success) {
                toast.success('Data feed configuration saved and connected!');
            } else if (data?.error) {
                toast.error(`Connected with error: ${data.error}`);
            } else {
                toast.success('Data feed configuration saved');
            }
            if (data?.config) {
                setDataFeedConfig(data.config);
                setDataFeedDraft({
                    api_key: data.config.api_key || '',
                    api_secret: data.config.api_secret || '',
                    base_url: data.config.base_url || 'http://localhost:3000/api/v1',
                    is_enabled: Boolean(data.config.is_enabled)
                });
            }
            setShowDataFeedModal(false);
            await refreshDashboard();
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to save data feed configuration'));
        } finally {
            setDataFeedSaving(false);
        }
    }, [dataFeedDraft, refreshDashboard]);

    // Admin management state (root only)
    const [showAdminModal, setShowAdminModal] = useState(false);
    const [adminsList, setAdminsList] = useState([]);
    const [adminsLoading, setAdminsLoading] = useState(false);
    const [rootControlUserId, setRootControlUserId] = useState('');
    const [rootControlDetail, setRootControlDetail] = useState(null);
    const [rootControlLoading, setRootControlLoading] = useState(false);
    const [rootControlSaving, setRootControlSaving] = useState(false);

    const effectiveAdminLevel = normalizeAdminLevel(adminLevel);
    const isRoot = effectiveAdminLevel === 'root' || effectiveAdminLevel === 'max';
    const canManage = effectiveAdminLevel === 'root' || effectiveAdminLevel === 'max' || effectiveAdminLevel === 'manage';
    const rootControlRef = useRef(null);
    const refreshInFlightRef = useRef(null);

    const usersList = Array.isArray(usersData?.users) ? usersData.users : [];
    const appliedGroup = useMemo(
        () => groupsList.find((group) => String(group.id) === String(filters.groupId)) || null,
        [filters.groupId, groupsList]
    );

    const handleRootControlSelect = useCallback((userId) => {
        const normalized = String(userId || '');
        setRootControlUserId(normalized);
        if (normalized) {
            requestAnimationFrame(() => {
                rootControlRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
        }
    }, []);

    const modalUser = useMemo(
        () => usersList.find((u) => u.id === modalUserId) || null,
        [usersList, modalUserId]
    );

    const clearAdminSession = useCallback(() => { clearAdminSessionToken(); }, []);

    const resetToVerifyStage = useCallback((message = 'Admin session expired. Please verify 2FA again.') => {
        clearAdminSession();
        setAuthStage('verify');
        setSetupPayload(null);
        setAuthCode('');
        setModalUserId(null);
        setShowAdminModal(false);
        if (message) toast.error(message);
    }, [clearAdminSession]);

    const loadStats = useCallback(async () => {
        const { data } = await adminApi.getDashboardStats();
        setStats(data);
        if (data?.admin_level) setAdminLevel(normalizeAdminLevel(data.admin_level));
    }, []);

    const loadFeedbackSummary = useCallback(async () => {
        try {
            const { data } = await adminApi.getFeedbackSummary();
            setFeedbackSummary(data || null);
        } catch {
            setFeedbackSummary(null);
        }
    }, []);

    const loadAutoApprovalSetting = useCallback(async () => {
        setAutoApprovalLoading(true);
        try {
            const { data } = await adminApi.getAutoApprovalSetting();
            setAutoApprovalEnabled(Boolean(data?.enabled));
        } finally {
            setAutoApprovalLoading(false);
        }
    }, []);

    const loadUsers = useCallback(async () => {
        setUsersLoading(true);
        try {
            const { data } = await adminApi.listUsers({
                status: filters.status || undefined,
                search: filters.search || undefined,
                group_id: filters.groupId || undefined,
                page: filters.page,
                per_page: filters.perPage,
            });
            setUsersData(normalizeUsersData(data));
        } finally { setUsersLoading(false); }
    }, [filters.groupId, filters.page, filters.perPage, filters.search, filters.status]);

    const loadGroups = useCallback(async ({ force = false } = {}) => {
        if (!isRoot && !force) {
            setGroupsList([]);
            setSelectedGroupForLink('');
            return;
        }

        setGroupsLoading(true);
        try {
            const { data } = await adminApi.listGroups();
            const incomingGroups = Array.isArray(data?.groups) ? data.groups : [];
            setGroupsList(incomingGroups);
            setSelectedGroupForLink((prev) => {
                if (prev && incomingGroups.some((g) => g.id === prev)) return prev;
                return incomingGroups[0]?.id || '';
            });
            setRenameGroupDraft((prev) => {
                if (prev && incomingGroups.some((g) => g.name === prev)) return prev;
                return incomingGroups[0]?.name || '';
            });
        } catch (err) {
            if ([401, 403].includes(err?.response?.status)) {
                if (!isRoot) {
                    setGroupsList([]);
                    setSelectedGroupForLink('');
                    setRenameGroupDraft('');
                    return;
                }
                throw err;
            }
            toast.error(parseApiError(err, 'Failed to load groups'));
        } finally {
            setGroupsLoading(false);
        }
    }, [isRoot]);

    const loadAdmins = useCallback(async () => {
        setAdminsLoading(true);
        try {
            const { data } = await adminApi.listAdmins();
            setAdminsList(data?.admins || []);
        } catch (err) {
            if (err?.response?.status === 403) return; // not root, ignore
            toast.error(parseApiError(err, 'Failed to load admins'));
        } finally { setAdminsLoading(false); }
    }, []);

    const loadSelectedUserDetail = useCallback(async (userId) => {
        if (!userId) return;
        setDetailLoading(true);
        try {
            const { data } = await adminApi.getUserDetail(userId);
            setSelectedUserDetail(data);
        } finally { setDetailLoading(false); }
    }, []);

    const loadRootControlDetail = useCallback(async (userId) => {
        if (!userId) {
            setRootControlDetail(null);
            return;
        }
        setRootControlLoading(true);
        try {
            const { data } = await adminApi.getUserDetail(userId);
            setRootControlDetail(data);
        } finally {
            setRootControlLoading(false);
        }
    }, []);

    const refreshDashboard = useCallback(async () => {
        if (refreshInFlightRef.current) {
            return await refreshInFlightRef.current;
        }

        const request = (async () => {
            const toLoad = [
                loadStats(),
                loadUsers(),
                loadAutoApprovalSetting(),
                loadGroups({ force: true }),
            ];
            const results = await Promise.allSettled(toLoad);
            const failedSections = [];
            if (results[0]?.status === 'rejected') failedSections.push({ name: 'stats', reason: results[0]?.reason });
            if (results[1]?.status === 'rejected') failedSections.push({ name: 'users', reason: results[1]?.reason });
            if (results[2]?.status === 'rejected') failedSections.push({ name: 'auto-approval', reason: results[2]?.reason });
            if (results[3]?.status === 'rejected') failedSections.push({ name: 'groups', reason: results[3]?.reason });
            if (failedSections.length) {
                const authFailed = failedSections.some((f) => [401, 403].includes(f?.reason?.response?.status));
                if (authFailed) { resetToVerifyStage(); return; }
                toast.error(`Failed to load: ${failedSections.map((f) => f.name).join(', ')}`);
            }
        })();

        refreshInFlightRef.current = request;
        try {
            return await request;
        } finally {
            refreshInFlightRef.current = null;
        }
    }, [loadAutoApprovalSetting, loadGroups, loadStats, loadUsers, resetToVerifyStage]);

    const handleSaveRootFinancials = useCallback(async (payload) => {
        if (!rootControlUserId) {
            toast.error('Select a user first');
            return;
        }
        setRootControlSaving(true);
        try {
            await adminApi.updateUserFinancials(rootControlUserId, payload);
            toast.success('User financial snapshot updated');
            await loadRootControlDetail(rootControlUserId);
            await refreshDashboard();
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to update financials'));
        } finally {
            setRootControlSaving(false);
        }
    }, [loadRootControlDetail, refreshDashboard, rootControlUserId]);

    const bootstrapAdmin = useCallback(async () => {
        if (!user || user.role !== 'admin') { setBootstrapping(false); return; }
        setBootstrapping(true);
        try {
            const existingSession = getAdminSessionToken();
            if (existingSession) {
                try {
                    const { data } = await adminApi.validateSession();
                    if (data?.admin_level) setAdminLevel(normalizeAdminLevel(data.admin_level));
                    setAuthStage('dashboard');
                    await refreshDashboard();
                    return;
                } catch { clearAdminSession(); }
            }
            const statusRes = await adminApi.getTwoFactorStatus();
            setAuthStage(statusRes?.data?.has_2fa ? 'verify' : 'setup');
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to initialize admin access'));
            setAuthStage('verify');
        } finally { setBootstrapping(false); }
    }, [clearAdminSession, refreshDashboard, user]);

    useEffect(() => { bootstrapAdmin(); }, [bootstrapAdmin]);

    useEffect(() => {
        if (authStage !== 'dashboard') return;
        loadFeedbackSummary();
    }, [authStage, loadFeedbackSummary]);

    useEffect(() => {
        if (authStage === 'dashboard' && modalUserId) {
            loadSelectedUserDetail(modalUserId).catch((err) => {
                if ([401, 403].includes(err?.response?.status)) { resetToVerifyStage(); return; }
                toast.error(parseApiError(err, 'Failed to load user detail'));
            });
        } else { setSelectedUserDetail(null); }
    }, [authStage, loadSelectedUserDetail, resetToVerifyStage, modalUserId]);

    useEffect(() => {
        if (authStage !== 'dashboard' || !isRoot) return;
        if (!rootControlUserId) {
            setRootControlDetail(null);
            return;
        }
        loadRootControlDetail(rootControlUserId).catch((err) => {
            if ([401, 403].includes(err?.response?.status)) { resetToVerifyStage(); return; }
            toast.error(parseApiError(err, 'Failed to load root control user'));
        });
    }, [authStage, isRoot, loadRootControlDetail, resetToVerifyStage, rootControlUserId]);

    async function handleGenerateSetup() {
        setSetupLoading(true);
        try { const { data } = await adminApi.setupTwoFactor(); setSetupPayload(data); toast.success('2FA secret generated'); }
        catch (err) { toast.error(parseApiError(err, 'Failed to generate 2FA secret')); }
        finally { setSetupLoading(false); }
    }

    async function handleEnableTwoFactor() {
        if (authCode.length < 6) { toast.error('Enter a valid 2FA code'); return; }
        setSetupLoading(true);
        try { await adminApi.enableTwoFactor(authCode); setAuthCode(''); toast.success('2FA enabled. Verify to continue.'); setAuthStage('verify'); }
        catch (err) { toast.error(parseApiError(err, 'Failed to enable 2FA')); }
        finally { setSetupLoading(false); }
    }

    async function handleVerifySession() {
        if (authCode.length < 6) { toast.error('Enter a valid 2FA code'); return; }
        setVerifyLoading(true);
        try {
            const { data } = await adminApi.verifyTwoFactor(authCode);
            setAdminSessionToken(data?.session_token);
            setAuthCode('');
            setAuthStage('dashboard');
            await refreshDashboard();
            toast.success('Admin session verified');
        } catch (err) {
            const message = parseApiError(err, '2FA verification failed');
            toast.error(message);
            if (
                err?.response?.status === 400
                && /set up 2FA again|2FA is not set up/i.test(message)
            ) {
                setSetupPayload(null);
                setAuthStage('setup');
            }
        } finally { setVerifyLoading(false); }
    }

    function openManageModal(userId) { setModalUserId(userId); setActionState(DEFAULT_ACTION_STATE); }
    function closeManageModal() { setModalUserId(null); setSelectedUserDetail(null); setActionState(DEFAULT_ACTION_STATE); }

    const [actionLoading, setActionLoading] = useState(false);

    async function runUserAction(actionName) {
        if (!modalUser) { toast.error('Select a user first'); return; }
        if (actionLoading) return;
        const durationDays = Number(actionState.durationDays);
        setActionLoading(true);
        try {
            if (actionName === 'approve') { await adminApi.approveUser(modalUser.id, durationDays); toast.success('User approved'); }
            else if (actionName === 'reactivate') { await adminApi.reactivateUser(modalUser.id, durationDays); toast.success('User reactivated'); }
            else if (actionName === 'set-duration') { await adminApi.setDuration(modalUser.id, durationDays); toast.success('Duration updated'); }
            else if (actionName === 'deactivate') {
                if (actionState.totpCode.length < 6) { toast.error('TOTP code required'); setActionLoading(false); return; }
                await adminApi.deactivateUser(modalUser.id, actionState.reason?.trim() || null, actionState.totpCode);
                toast.success('User deactivated');
                setActionState((p) => ({ ...p, reason: '', totpCode: '' }));
            }
            else if (actionName === 'force-logout') {
                await adminApi.forceLogoutUser(modalUser.id);
                toast.success('All active sessions were forced to logout');
            }
            else if (actionName === 'delete-user') {
                const email = modalUser?.email || 'this user';
                if (actionState.totpCode.length < 6) { toast.error('TOTP code required'); setActionLoading(false); return; }
                if (!window.confirm(`Permanently delete ${email}? This removes the account and all data from DB.`)) {
                    setActionLoading(false);
                    return;
                }
                if (!window.confirm('Final confirmation: this action cannot be undone. Continue permanent delete?')) {
                    setActionLoading(false);
                    return;
                }
                await adminApi.deleteUserAccount(modalUser.id, actionState.totpCode);
                toast.success('User account permanently deleted');
                setActionState((p) => ({ ...p, reason: '', totpCode: '' }));
                closeManageModal();
            }
            await refreshDashboard();
            if (modalUserId) await loadSelectedUserDetail(modalUserId);
        } catch (err) {
            if ([401, 403].includes(err?.response?.status)) resetToVerifyStage('Session expired. Please verify 2FA again.');
            else toast.error(parseApiError(err, 'Action failed'));
        } finally {
            setActionLoading(false);
        }
    }

    // Admin management actions (root only)
    async function handlePromoteAdmin(email, level) {
        try {
            await adminApi.promoteToAdmin(email, level);
            toast.success(`${email} promoted to admin (${level})`);
            await loadAdmins();
        } catch (err) { toast.error(parseApiError(err, 'Failed to promote')); }
    }

    async function handleUpdateAdminLevel(adminId, newLevel) {
        try {
            await adminApi.updateAdminLevel(adminId, newLevel);
            toast.success('Admin level updated');
            await loadAdmins();
        } catch (err) { toast.error(parseApiError(err, 'Failed to update level')); }
    }

    async function handleRevokeAdmin(adminId) {
        try {
            await adminApi.revokeAdmin(adminId);
            toast.success('Admin access revoked');
            await loadAdmins();
        } catch (err) { toast.error(parseApiError(err, 'Failed to revoke')); }
    }

    function openAdminManagement() {
        setShowAdminModal(true);
        loadAdmins();
    }

    function openRootControlPage(userId = null) {
        if (userId) {
            navigate(`/admin/root-control?user=${encodeURIComponent(String(userId))}`);
            return;
        }
        navigate('/admin/root-control');
    }

    function openAuditLogPage() {
        navigate('/admin/audit-log');
    }

    function openBugReportsPage() {
        navigate('/admin/bug-reports');
    }

    async function handleEndAdminSession() {
        clearAdminSession(); setAuthStage('verify'); setSetupPayload(null); setAuthCode(''); setModalUserId(null); setShowAdminModal(false);
        toast('Admin session ended');
    }

    async function handleSignOut() { clearAdminSession(); await logout(); navigate('/login', { replace: true }); }

    async function handleToggleAutoApproval() {
        if (!isRoot || autoApprovalSaving) return;
        setAutoApprovalSaving(true);
        try {
            const next = !autoApprovalEnabled;
            const { data } = await adminApi.setAutoApprovalSetting(next);
            setAutoApprovalEnabled(Boolean(data?.enabled));
            toast.success(`Auto approval ${data?.enabled ? 'enabled' : 'disabled'}`);
        } catch (err) {
            if ([401, 403].includes(err?.response?.status)) {
                resetToVerifyStage('Session expired. Please verify 2FA again.');
                return;
            }
            toast.error(parseApiError(err, 'Failed to update auto approval setting'));
        } finally {
            setAutoApprovalSaving(false);
        }
    }

    async function handleCreateGroup() {
        if (!isRoot || groupActionLoading) return;
        const name = groupNameDraft.trim();
        if (name.length < 2) {
            toast.error('Enter a valid group name');
            return;
        }

        setGroupActionLoading(true);
        try {
            const { data } = await adminApi.createGroup(name);
            toast.success(`Group created: ${data?.group?.name || name}`);
            setGroupNameDraft('');
            await loadGroups();
            await refreshDashboard();
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to create group'));
        } finally {
            setGroupActionLoading(false);
        }
    }

    async function handleRenameGroup() {
        if (!isRoot || !selectedGroupForLink || groupActionLoading) return;
        const nextName = renameGroupDraft.trim();
        if (nextName.length < 2) {
            toast.error('Enter a valid group name');
            return;
        }

        setGroupActionLoading(true);
        try {
            await adminApi.renameGroup(selectedGroupForLink, nextName);
            toast.success('Group name updated');
            await loadGroups();
            await refreshDashboard();
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to rename group'));
        } finally {
            setGroupActionLoading(false);
        }
    }

    async function handleDeleteGroup() {
        if (!isRoot || !selectedGroupForLink || groupActionLoading) return;
        const selectedGroup = groupsList.find((group) => group.id === selectedGroupForLink);
        const groupName = selectedGroup?.name || 'this group';

        if (!window.confirm(`Delete ${groupName}? All users in it will move to Normal.`)) return;

        setGroupActionLoading(true);
        try {
            await adminApi.deleteGroup(selectedGroupForLink);
            toast.success('Group deleted and users moved to Normal');
            setFilters((prev) => ({ ...prev, groupId: 'normal', page: 1 }));
            setDraftFilters((prev) => ({ ...prev, groupId: 'normal' }));
            await loadGroups();
            await refreshDashboard();
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to delete group'));
        } finally {
            setGroupActionLoading(false);
        }
    }

    async function handleToggleAppliedGroupAutoApproval() {
        if (!isRoot || !filters.groupId || filters.groupId === 'normal' || !appliedGroup || groupActionLoading) return;

        if (autoApprovalEnabled) {
            toast('Global auto approval is ON. This already enables all groups.');
            return;
        }

        setGroupActionLoading(true);
        try {
            const next = !Boolean(appliedGroup.auto_approval);
            await adminApi.setGroupAutoApproval(appliedGroup.id, next);
            toast.success(`Group auto approval ${next ? 'enabled' : 'disabled'}`);
            await loadGroups();
            await refreshDashboard();
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to update group auto approval'));
        } finally {
            setGroupActionLoading(false);
        }
    }

    function triggerBlobDownload(blobData, fallbackName) {
        if (!blobData) return;
        const blobUrl = window.URL.createObjectURL(blobData);
        const link = document.createElement('a');
        link.href = blobUrl;
        link.download = fallbackName;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(blobUrl);
    }

    function resolveFilenameFromDisposition(disposition, fallbackName) {
        const raw = String(disposition || '');
        const match = raw.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
        const encoded = match?.[1];
        const plain = match?.[2];
        if (encoded) {
            try {
                return decodeURIComponent(encoded);
            } catch {
                return fallbackName;
            }
        }
        return plain || fallbackName;
    }

    async function handleDownloadOverallExcel() {
        if (!isRoot || excelExportLoading) return;
        setExcelExportLoading(true);
        try {
            const response = await adminApi.downloadOverallUsersExcel();
            const filename = resolveFilenameFromDisposition(
                response?.headers?.['content-disposition'],
                'alphasync_users_overall.xlsx'
            );
            triggerBlobDownload(response.data, filename);
            toast.success('Overall users Excel downloaded');
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to download overall users Excel'));
        } finally {
            setExcelExportLoading(false);
        }
    }

    async function handleDownloadAppliedExcel() {
        if (!isRoot || excelExportLoading) return;
        setExcelExportLoading(true);
        try {
            const response = await adminApi.downloadAppliedUsersExcel({
                status: filters.status || undefined,
                search: filters.search || undefined,
                group_id: filters.groupId || undefined,
            });
            const filename = resolveFilenameFromDisposition(
                response?.headers?.['content-disposition'],
                'alphasync_users_applied.xlsx'
            );
            triggerBlobDownload(response.data, filename);
            toast.success('Applied users Excel downloaded');
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to download applied users Excel'));
        } finally {
            setExcelExportLoading(false);
        }
    }

    async function handleGenerateGroupLink() {
        if (!isRoot || !selectedGroupForLink || groupActionLoading) return;
        setGroupActionLoading(true);
        try {
            const { data } = await adminApi.generateGroupLink(selectedGroupForLink);
            const inviteUrl = data?.invite_url;
            if (!inviteUrl) {
                toast.error('Failed to generate invite link');
                return;
            }

            if (navigator?.clipboard?.writeText) {
                await navigator.clipboard.writeText(inviteUrl);
                toast.success('Group link generated and copied');
            } else {
                toast.success('Group link generated');
            }

            await loadGroups();
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to generate link'));
        } finally {
            setGroupActionLoading(false);
        }
    }

    async function handleSetUserGroup(userId, nextGroupId) {
        if (!isRoot || groupActionLoading) return;

        setGroupActionLoading(true);
        try {
            await adminApi.setUserGroup(userId, nextGroupId === 'normal' ? null : nextGroupId);
            toast.success(nextGroupId === 'normal' ? 'User moved to normal section' : 'User moved to group');
            await refreshDashboard();
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to update user group'));
        } finally {
            setGroupActionLoading(false);
        }
    }

    useEffect(() => {
        if (!usersList.length) {
            setUserGroupDrafts({});
            return;
        }

        setUserGroupDrafts((prev) => {
            const next = { ...prev };
            for (const account of usersList) {
                const key = String(account.id);
                if (!Object.prototype.hasOwnProperty.call(next, key)) {
                    next[key] = account.group_id || 'normal';
                }
            }
            return next;
        });
    }, [usersList]);

    useEffect(() => {
        if (!isRoot && (filters.groupId || '').toLowerCase() !== 'normal') {
            setFilters((prev) => ({ ...prev, groupId: 'normal', page: 1 }));
            setDraftFilters((prev) => ({ ...prev, groupId: 'normal' }));
        }
    }, [filters.groupId, isRoot]);

    const statusOptions = [
        { label: 'All statuses', value: '' },
        { label: 'Pending', value: 'pending_approval' },
        { label: 'Active', value: 'active' },
        { label: 'Expired', value: 'expired' },
        { label: 'Deactivated', value: 'deactivated' },
        { label: 'Deleted', value: 'deleted' },
    ];

    if (bootstrapping) {
        return (
            <div className="admin-shell flex flex-col items-center justify-center gap-4 px-4">
                <Loader2 size={40} className="animate-spin" style={{ color: 'var(--brand)' }} />
                <div className="text-sm" style={{ color: 'var(--text-muted)' }}>Preparing secure admin workspace...</div>
            </div>
        );
    }

    return (
        <div className="admin-shell p-3 sm:p-4 md:p-5 lg:p-6">
            {/* Header */}
            <header className="admin-hero p-4 sm:p-5 lg:p-6 mb-4 sm:mb-5">
                <div className="admin-hero-grid lg:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.9fr)] items-start lg:items-center relative z-10">
                    <div className="space-y-4">
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-[11px] font-bold uppercase tracking-[0.2em]" style={{ background: 'rgba(0,188,212,0.12)', color: 'var(--brand)', border: '1px solid rgba(0,188,212,0.24)' }}>
                                <Shield size={13} /> AlphaSync Control Center
                            </span>
                            {authStage === 'dashboard' && <LevelPill level={effectiveAdminLevel} />}
                            {isRoot && (
                                <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] font-semibold uppercase tracking-[0.16em]" style={{ background: 'rgba(245,158,11,0.12)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.22)' }}>
                                    <Crown size={12} /> Root authority
                                </span>
                            )}
                        </div>
                        <div>
                            <h1 className="text-2xl sm:text-3xl lg:text-4xl font-black tracking-tight admin-section-title">Admin Panel</h1>
                            <p className="admin-section-subtitle mt-2 text-sm sm:text-base max-w-2xl">
                                A cleaner control surface for approvals, groups, user actions, and elevated admin workflows — tuned for speed, clarity, and safe decision making.
                            </p>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 max-w-3xl">
                            <div className="admin-mini-stat">
                                <div className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Signed in as</div>
                                <div className="mt-1 text-sm font-semibold truncate" title={user?.email || 'admin'}>{user?.email || 'admin'}</div>
                            </div>
                            <div className="admin-mini-stat">
                                <div className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Workspace</div>
                                <div className="mt-1 text-sm font-semibold">Admin / Secure</div>
                            </div>
                            <div className="admin-mini-stat">
                                <div className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Mode</div>
                                <div className="mt-1 text-sm font-semibold" style={{ color: canManage ? '#10b981' : '#f59e0b' }}>{canManage ? 'Manage enabled' : 'View only'}</div>
                            </div>
                        </div>
                    </div>
                    <div className="space-y-3 lg:pl-4 lg:border-l lg:border-white/10">
                        <div className="admin-card-soft p-3 sm:p-4">
                            <div className="text-[11px] font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--text-muted)' }}>Quick actions</div>
                            <div className="admin-command-bar">
                                {authStage === 'dashboard' && isRoot && (
                                    <button
                                        className={`admin-action-btn ${autoApprovalEnabled ? 'admin-action-btn--success' : 'admin-action-btn--secondary'}`}
                                        style={{ opacity: (autoApprovalLoading || autoApprovalSaving) ? 0.7 : 1 }}
                                        disabled={autoApprovalLoading || autoApprovalSaving}
                                        onClick={handleToggleAutoApproval}
                                        title="When ON, new users are auto-approved at first sync"
                                    >
                                        {(autoApprovalLoading || autoApprovalSaving) ? <Loader2 size={14} className="animate-spin" /> : <UserCheck size={14} />}
                                        Auto Approval {autoApprovalEnabled ? 'ON' : 'OFF'}
                                    </button>
                                )}
                                {authStage === 'dashboard' && isRoot && (
                                    <button className="admin-action-btn admin-action-btn--warning" onClick={openAdminManagement}>
                                        <Crown size={14} /> Manage Admins
                                    </button>
                                )}
                                {authStage === 'dashboard' && isRoot && (
                                    <button className="admin-action-btn" style={{ background: 'rgba(16,185,129,0.12)', color: '#10b981', borderColor: 'rgba(16,185,129,0.24)' }} onClick={openDataFeedModal}>
                                        <Activity size={14} /> Data Feed
                                    </button>
                                )}
                                {authStage === 'dashboard' && isRoot && (
                                    <button className="admin-action-btn" style={{ background: 'rgba(14,165,233,0.12)', color: '#0ea5e9', borderColor: 'rgba(14,165,233,0.24)' }} onClick={() => openRootControlPage()}>
                                        <Settings2 size={14} /> Root Center
                                    </button>
                                )}
                                <button className="admin-action-btn admin-action-btn--secondary" onClick={openAuditLogPage}>
                                    <Activity size={14} /> Audit Log
                                </button>
                                <button className="admin-action-btn admin-action-btn--secondary" onClick={openBugReportsPage}>
                                    <FileText size={14} /> Bug Reports
                                </button>
                                <button className="admin-action-btn admin-action-btn--secondary" onClick={() => refreshDashboard()}>
                                    <RefreshCw size={14} /> Refresh
                                </button>
                                <button className="admin-action-btn admin-action-btn--secondary" onClick={handleEndAdminSession}>
                                    <Shield size={14} /> End Session
                                </button>
                                <button className="admin-action-btn admin-action-btn--danger" onClick={handleSignOut}>
                                    <LogOut size={14} /> Sign Out
                                </button>
                            </div>
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                            <div className="admin-mini-stat">
                                <div className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Security</div>
                                <div className="mt-1 text-sm font-semibold">2FA verified workflow</div>
                            </div>
                            <div className="admin-mini-stat">
                                <div className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Actions</div>
                                <div className="mt-1 text-sm font-semibold">Approve, manage, audit</div>
                            </div>
                        </div>
                    </div>
                </div>
            </header>

            {authStage === 'setup' && <AdminAuthSetup setupLoading={setupLoading} setupPayload={setupPayload} authCode={authCode} setAuthCode={setAuthCode} onGenerate={handleGenerateSetup} onEnable={handleEnableTwoFactor} />}
            {authStage === 'verify' && <AdminAuthVerify verifyLoading={verifyLoading} authCode={authCode} setAuthCode={setAuthCode} onVerify={handleVerifySession} />}

            {authStage === 'dashboard' && (
                <div className="flex flex-col gap-4 sm:gap-5 animate-fade-in">
                    {/* View-only banner */}
                    {!canManage && (
                        <div className="admin-card p-4 flex items-center gap-3" style={{ borderColor: 'rgba(148,163,184,0.28)' }}>
                            <EyeOff size={18} style={{ color: 'var(--text-muted)' }} />
                            <span className="text-sm" style={{ color: 'var(--text-muted)' }}>
                                You have <strong>view-only</strong> access. Contact the root admin for elevated permissions.
                            </span>
                        </div>
                    )}

                    {/* Stats Grid */}
                    <section className="grid grid-cols-2 xl:grid-cols-5 gap-2 sm:gap-3">
                        <StatCard icon={Users} label="Total Users" value={stats?.total_users ?? 0} />
                        <StatCard icon={Clock} label="Pending" value={stats?.pending_approval ?? 0} color="#f59e0b" />
                        <StatCard icon={UserCheck} label="Active" value={stats?.active ?? 0} color="#10b981" />
                        <StatCard icon={AlertTriangle} label="Expired / Deactivated" value={(stats?.expired ?? 0) + (stats?.deactivated ?? 0)} color="#f97316" />
                        <StatCard
                            icon={Star}
                            label="Avg Rating"
                            value={feedbackSummary && Number(feedbackSummary.total_responses || 0) > 0 ? `${Number(feedbackSummary.average_rating || 0).toFixed(1)} ⭐` : '— ⭐'}
                            color="#FBB724"
                            subtext={feedbackSummary ? `from ${Number(feedbackSummary.total_responses || 0)} reviews` : 'from — reviews'}
                        />
                    </section>

                    {isRoot && (
                        <section className="admin-card p-4 sm:p-5">
                            <div className="flex flex-wrap items-start justify-between gap-3 mb-3 sm:mb-4">
                                <div>
                                    <h2 className="text-lg font-bold admin-section-title">User Groups</h2>
                                    <p className="text-xs mt-1 admin-section-subtitle">
                                        Create custom groups and generate onboarding links. Users coming via group links are auto-assigned.
                                    </p>
                                </div>
                                <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>{groupsList.length} custom group{groupsList.length !== 1 ? 's' : ''}</span>
                            </div>
                            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                                <div className="admin-card-soft p-4">
                                    <label className="label-text">Create Group</label>
                                    <div className="flex flex-col sm:flex-row gap-2">
                                        <input
                                            className="input-field"
                                            value={groupNameDraft}
                                            placeholder="e.g. Welcome1"
                                            maxLength={60}
                                            onChange={(e) => setGroupNameDraft(e.target.value)}
                                            onKeyDown={(e) => e.key === 'Enter' && handleCreateGroup()}
                                        />
                                        <button className="admin-action-btn admin-action-btn--primary" disabled={groupActionLoading} onClick={handleCreateGroup}>
                                            {groupActionLoading ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Create
                                        </button>
                                    </div>
                                </div>
                                <div className="admin-card-soft p-4">
                                    <label className="label-text">Generate Group Link</label>
                                    <div className="flex flex-col sm:flex-row gap-2">
                                        <select className="input-field" value={selectedGroupForLink} onChange={(e) => {
                                            const selectedId = e.target.value;
                                            setSelectedGroupForLink(selectedId);
                                            const selectedGroup = groupsList.find((g) => g.id === selectedId);
                                            setRenameGroupDraft(selectedGroup?.name || '');
                                        }}>
                                            {groupsList.length === 0 ? (
                                                <option value="">No groups</option>
                                            ) : (
                                                groupsList.map((group) => (
                                                    <option key={group.id} value={group.id}>{group.name}</option>
                                                ))
                                            )}
                                        </select>
                                        <button
                                            className="admin-action-btn admin-action-btn--primary"
                                            disabled={groupActionLoading || groupsLoading || !selectedGroupForLink}
                                            onClick={handleGenerateGroupLink}
                                        >
                                            {groupActionLoading ? <Loader2 size={14} className="animate-spin" /> : <Link2 size={14} />} Generate & Copy
                                        </button>
                                    </div>
                                    <div className="flex flex-col sm:flex-row gap-2 mt-3">
                                        <input
                                            className="input-field"
                                            value={renameGroupDraft}
                                            maxLength={60}
                                            placeholder="Rename selected group"
                                            onChange={(e) => setRenameGroupDraft(e.target.value)}
                                            onKeyDown={(e) => e.key === 'Enter' && handleRenameGroup()}
                                        />
                                        <button className="admin-action-btn admin-action-btn--secondary" disabled={groupActionLoading || !selectedGroupForLink} onClick={handleRenameGroup}>
                                            <Pencil size={14} /> Rename
                                        </button>
                                        <button
                                            className="admin-action-btn admin-action-btn--danger"
                                            disabled={groupActionLoading || !selectedGroupForLink}
                                            onClick={handleDeleteGroup}
                                        >
                                            <Trash2 size={14} /> Delete
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </section>
                    )}

                    {/* User Accounts Table */}
                    <section className="admin-card p-4 sm:p-5">
                        <div className="flex flex-wrap justify-between items-start gap-3 mb-4">
                            <div>
                                <h2 className="text-lg font-bold admin-section-title">User Accounts</h2>
                                <p className="text-xs mt-1 admin-section-subtitle">Full lifecycle control: approve, activate, deactivate, duration</p>
                            </div>
                            <div className="flex items-center gap-2 flex-wrap justify-end">
                                {isRoot && (
                                    <>
                                        <button
                                            className="admin-action-btn admin-action-btn--secondary text-xs sm:text-sm"
                                            disabled={excelExportLoading}
                                            onClick={handleDownloadOverallExcel}
                                        >
                                            {excelExportLoading ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />} Overall Excel
                                        </button>
                                        <button
                                            className="admin-action-btn admin-action-btn--primary text-xs sm:text-sm"
                                            disabled={excelExportLoading}
                                            onClick={handleDownloadAppliedExcel}
                                        >
                                            {excelExportLoading ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />} Applied Excel
                                        </button>
                                    </>
                                )}
                                <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>{usersData.total} user{usersData.total !== 1 ? 's' : ''}</span>
                            </div>
                        </div>
                        {isRoot && (
                            <div className="flex flex-wrap items-center gap-2 mb-3 p-3 rounded-2xl" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(148,163,184,0.12)' }}>
                                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                                    Applied group: <strong>{filters.groupId === 'normal' ? 'Normal' : (appliedGroup?.name || 'Unknown')}</strong>
                                </span>
                                <button
                                    className="admin-action-btn text-xs sm:text-sm"
                                    style={{
                                        background: (filters.groupId === 'normal'
                                            ? autoApprovalEnabled
                                            : (autoApprovalEnabled || Boolean(appliedGroup?.auto_approval)))
                                            ? 'rgba(16,185,129,0.12)'
                                            : 'rgba(148,163,184,0.12)',
                                        color: (filters.groupId === 'normal'
                                            ? autoApprovalEnabled
                                            : (autoApprovalEnabled || Boolean(appliedGroup?.auto_approval)))
                                            ? '#10b981'
                                            : 'var(--text-muted)',
                                        border: (filters.groupId === 'normal'
                                            ? autoApprovalEnabled
                                            : (autoApprovalEnabled || Boolean(appliedGroup?.auto_approval)))
                                            ? '1px solid rgba(16,185,129,0.3)'
                                            : '1px solid var(--border)',
                                        opacity: groupActionLoading ? 0.7 : 1,
                                    }}
                                    disabled={groupActionLoading || (filters.groupId !== 'normal' && !appliedGroup)}
                                    onClick={filters.groupId === 'normal' ? handleToggleAutoApproval : handleToggleAppliedGroupAutoApproval}
                                    title={filters.groupId === 'normal'
                                        ? 'Normal users use global auto approval setting'
                                        : (autoApprovalEnabled ? 'Global auto approval is ON for all groups' : 'Toggle auto approval for this applied group')}
                                >
                                    {groupActionLoading ? <Loader2 size={14} className="animate-spin" /> : <UserCheck size={14} />}
                                    {filters.groupId === 'normal'
                                        ? `Normal Auto Approval: ${autoApprovalEnabled ? 'ON' : 'OFF'}`
                                        : `Group Auto Approval: ${(autoApprovalEnabled || Boolean(appliedGroup?.auto_approval)) ? 'ON' : 'OFF'}`}
                                </button>
                            </div>
                        )}
                        <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.4fr)_170px_170px_auto] gap-2 sm:gap-3 mb-4 items-end">
                            <div className="relative w-full sm:flex-1 min-w-0">
                                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--text-muted)' }} />
                                <input className="input-field pl-9" placeholder="Search email / username / name" value={draftFilters.search}
                                    onChange={(e) => setDraftFilters((p) => ({ ...p, search: e.target.value }))}
                                    onKeyDown={(e) => e.key === 'Enter' && setFilters((p) => ({ ...p, status: draftFilters.status, search: draftFilters.search, groupId: draftFilters.groupId, page: 1 }))} />
                            </div>
                            <select className="input-field w-full min-w-0" value={draftFilters.status}
                                onChange={(e) => setDraftFilters((p) => ({ ...p, status: e.target.value }))}>
                                {statusOptions.map((opt) => <option key={opt.value || 'all'} value={opt.value}>{opt.label}</option>)}
                            </select>
                            {isRoot && (
                                <select className="input-field w-full min-w-0" value={draftFilters.groupId}
                                    onChange={(e) => setDraftFilters((p) => ({ ...p, groupId: e.target.value }))}>
                                    <option value="normal">Normal</option>
                                    {groupsList.map((group) => (
                                        <option key={group.id} value={group.id}>{group.name}</option>
                                    ))}
                                </select>
                            )}
                            <button className="admin-action-btn admin-action-btn--primary w-full" disabled={usersLoading}
                                onClick={() => setFilters((p) => ({ ...p, status: draftFilters.status, search: draftFilters.search, groupId: draftFilters.groupId, page: 1 }))}>
                                {usersLoading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />} Apply
                            </button>
                        </div>
                        <div className="admin-table-shell overflow-x-auto">
                            <table className="w-full" style={{ borderCollapse: 'collapse', tableLayout: 'auto', minWidth: 1320 }}>
                                <colgroup>
                                    <col style={{ width: '15%' }} /><col style={{ width: '10%' }} /><col style={{ width: '9%' }} />
                                    <col style={{ width: '9%' }} /><col style={{ width: '8%' }} /><col style={{ width: '8%' }} /><col style={{ width: '9%' }} />
                                    <col style={{ width: '9%' }} /><col style={{ width: '10%' }} /><col style={{ width: '14%' }} /><col style={{ width: '5%' }} /><col style={{ width: '12%' }} />
                                </colgroup>
                                <thead>
                                    <tr style={{ background: 'var(--bg-muted)' }}>
                                        {['Email', 'Full Name', 'Mobile', 'Status', 'Group', 'Provider', 'Registered', 'Expires', 'Last Online', 'Action', 'Rating', 'Feedback'].map((h) => (
                                            <th key={h} className="text-left px-3 py-3 text-xs font-semibold uppercase tracking-wider"
                                                style={{ color: 'var(--text-muted)', borderBottom: '1px solid var(--border)' }}>{h}</th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {usersList.length === 0 ? (
                                        <tr><td colSpan={12} className="text-center py-8 text-sm" style={{ color: 'var(--text-muted)' }}>No users found yet.</td></tr>
                                    ) : usersList.map((u) => {
                                        const isAdminRow = u.role === 'admin';
                                        const isDeletedMarker = Boolean(u.deleted_by_user);
                                        const rootSelected = isRoot && rootControlUserId && String(u.id) === String(rootControlUserId);
                                        const currentGroupValue = userGroupDrafts[String(u.id)] || u.group_id || 'normal';
                                        const registered = safeDateTimeParts(u.created_at);
                                        const expires = safeDateTimeParts(u.access_expires_at);
                                        const lastOnline = formatLastOnline(u.last_online_at, u.is_online, u.account_status);
                                        return (
                                            <tr key={u.id} className="admin-row transition-colors" style={{ borderBottom: '1px solid rgba(148,163,184,0.12)', background: rootSelected ? 'rgba(245,158,11,0.08)' : 'transparent' }}>
                                                <td className="px-2.5 sm:px-3 py-2.5 sm:py-3 text-xs font-medium break-all" title={u.email}>
                                                    <span className="inline-flex items-center gap-1.5 flex-wrap">
                                                        {u.email}
                                                        {isAdminRow ? (
                                                            <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full"
                                                                style={{ background: 'rgba(245,158,11,0.16)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.35)' }}
                                                                title={`Admin level: ${u.admin_level || 'unknown'}`}>
                                                                <Crown size={10} /> Admin{u.admin_level ? ` · ${u.admin_level}` : ''}
                                                            </span>
                                                        ) : null}
                                                        {isDeletedMarker ? <Bookmark size={12} style={{ color: '#ec4899' }} title="Self-deleted account marker" /> : null}
                                                    </span>
                                                </td>
                                                <td className="px-2.5 sm:px-3 py-2.5 sm:py-3 text-xs" style={{ color: 'var(--text-secondary)' }} title={u.full_name || u.username}>{u.full_name || u.username || '—'}</td>
                                                <td className="px-2.5 sm:px-3 py-2.5 sm:py-3 text-xs font-mono whitespace-nowrap" style={{ color: u.phone ? 'var(--text-primary)' : '#ef4444' }}>
                                                    {u.phone || <span style={{ color: '#f59e0b', fontStyle: 'italic' }}>Not set</span>}
                                                </td>
                                                <td className="px-2.5 sm:px-3 py-2.5 sm:py-3"><StatusPill status={u.account_status} /></td>
                                                <td className="px-2.5 sm:px-3 py-2.5 sm:py-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                                                    {u.group_name || 'Normal'}
                                                </td>
                                                <td className="px-2.5 sm:px-3 py-2.5 sm:py-3 text-xs whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>
                                                    {u.auth_provider === 'google.com' ? '🔵 Google' : u.auth_provider === 'password' ? '🔑 Email' : (u.auth_provider || '—')}
                                                </td>
                                                <td className="px-2.5 sm:px-3 py-2.5 sm:py-3 text-xs font-mono whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>
                                                    <div className="flex flex-col leading-tight">
                                                        <span>{registered.date}</span>
                                                        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{registered.time}</span>
                                                    </div>
                                                </td>
                                                <td className="px-2.5 sm:px-3 py-2.5 sm:py-3 text-xs font-mono whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>
                                                    <div className="flex flex-col leading-tight">
                                                        <span>{expires.date}</span>
                                                        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{expires.time}</span>
                                                    </div>
                                                </td>
                                                <td className="px-2.5 sm:px-3 py-2.5 sm:py-3 text-xs align-top">
                                                    <div className="flex flex-col leading-tight">
                                                        <span style={{ color: lastOnline.tone === 'online' ? '#10b981' : 'var(--text-secondary)', fontWeight: lastOnline.tone === 'online' ? 700 : 500 }}>
                                                            {lastOnline.label}
                                                        </span>
                                                        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{lastOnline.detail}</span>
                                                    </div>
                                                </td>
                                                <td className="px-2.5 sm:px-3 py-2.5 sm:py-3 align-top">
                                                    {isAdminRow ? (
                                                        <button className="admin-action-btn text-[11px] sm:text-xs"
                                                            style={{
                                                                background: 'rgba(245,158,11,0.12)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.25)',
                                                                cursor: isRoot ? 'pointer' : 'default', opacity: isRoot ? 1 : 0.7,
                                                            }}
                                                            disabled={!isRoot}
                                                            onClick={isRoot ? openAdminManagement : undefined}
                                                            title={isRoot ? 'Open Admin Management' : 'Admin accounts are managed from Admin Management (root only)'}>
                                                            <Crown size={11} /> Managed via Admin Settings
                                                        </button>
                                                    ) : isDeletedMarker ? (
                                                        <span className="inline-flex items-center gap-1 text-[11px] sm:text-xs font-semibold px-2.5 py-1.5 rounded-full"
                                                            style={{ background: 'rgba(236,72,153,0.14)', color: '#ec4899', border: '1px solid rgba(236,72,153,0.3)' }}>
                                                            <Bookmark size={11} /> Self Deleted
                                                        </span>
                                                    ) : canManage ? (
                                                        <div className="flex flex-col gap-2">
                                                            {isRoot && (
                                                                <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap">
                                                                    <select
                                                                        className="text-[11px] sm:text-xs px-2 py-1.5 rounded-full"
                                                                        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', color: 'var(--text-primary)' }}
                                                                        value={currentGroupValue}
                                                                        onChange={(e) => {
                                                                            const value = e.target.value;
                                                                            setUserGroupDrafts((prev) => ({ ...prev, [String(u.id)]: value }));
                                                                        }}
                                                                    >
                                                                        <option value="normal">Normal</option>
                                                                        {groupsList.map((group) => (
                                                                            <option key={group.id} value={group.id}>{group.name}</option>
                                                                        ))}
                                                                    </select>
                                                                    <button
                                                                        className="admin-action-btn admin-action-btn--secondary text-[11px] sm:text-xs"
                                                                        style={{ background: 'rgba(14,165,233,0.12)', color: '#0ea5e9', border: '1px solid rgba(14,165,233,0.3)' }}
                                                                        disabled={groupActionLoading}
                                                                        onClick={() => handleSetUserGroup(u.id, currentGroupValue)}
                                                                    >
                                                                        {groupActionLoading ? <Loader2 size={11} className="animate-spin" /> : <Copy size={11} />} Set Group
                                                                    </button>
                                                                </div>
                                                            )}
                                                            <div className="admin-row-actions">
                                                            {isRoot && (
                                                                <button className="admin-action-btn text-[11px] sm:text-xs"
                                                                    style={{
                                                                        background: rootSelected ? 'rgba(245,158,11,0.22)' : 'rgba(245,158,11,0.12)',
                                                                        color: '#f59e0b',
                                                                        border: rootSelected ? '1px solid rgba(245,158,11,0.45)' : '1px solid rgba(245,158,11,0.25)',
                                                                    }}
                                                                    onClick={() => openRootControlPage(u.id)}>
                                                                    <Settings2 size={11} /> Control
                                                                </button>
                                                            )}
                                                            <button className="admin-action-btn admin-action-btn--secondary text-[11px] sm:text-xs"
                                                                style={{ background: 'var(--brand-glow)', color: 'var(--brand)', border: '1px solid rgba(0,188,212,0.2)' }}
                                                                onClick={() => openManageModal(u.id)}><Eye size={11} /> Manage</button>
                                                            <button
                                                                className="admin-action-btn admin-action-btn--danger text-[11px] sm:text-xs"
                                                                onClick={async () => {
                                                                    const email = u?.email || 'this user';
                                                                    const totpCode = (window.prompt('Enter admin TOTP code to permanently delete this user:') || '').replace(/\D/g, '').slice(0, 8);
                                                                    if (totpCode.length < 6) {
                                                                        toast.error('Valid TOTP code is required');
                                                                        return;
                                                                    }
                                                                    if (!window.confirm(`Permanently delete ${email}? This removes account and all data from DB.`)) return;
                                                                    if (!window.confirm('Final confirmation: this action cannot be undone. Continue?')) return;
                                                                    try {
                                                                        await adminApi.deleteUserAccount(u.id, totpCode);
                                                                        toast.success('User account permanently deleted');
                                                                        await refreshDashboard();
                                                                    } catch (err) {
                                                                        if ([401, 403].includes(err?.response?.status)) {
                                                                            resetToVerifyStage('Session expired. Please verify 2FA again.');
                                                                            return;
                                                                        }
                                                                        toast.error(parseApiError(err, 'Failed to delete user'));
                                                                    }
                                                                }}
                                                            ><Trash2 size={11} /> Delete</button>
                                                            </div>
                                                        </div>
                                                    ) : (
                                                        <button className="admin-action-btn admin-action-btn--secondary text-xs"
                                                            style={{ background: 'rgba(148,163,184,0.08)', color: 'var(--text-muted)', border: '1px solid rgba(148,163,184,0.15)' }}
                                                            onClick={() => openManageModal(u.id)}><Eye size={11} /> View</button>
                                                    )}
                                                </td>
                                                <td className="px-2.5 sm:px-3 py-2.5 sm:py-3 text-xs align-top">
                                                    {u.feedback_rating ? (
                                                        <RatingStars rating={u.feedback_rating} />
                                                    ) : (
                                                        <div className="flex flex-col leading-tight">
                                                            <span style={{ color: 'var(--text-muted)' }}>—</span>
                                                            <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>No feedback</span>
                                                        </div>
                                                    )}
                                                </td>
                                                <td className="px-2.5 sm:px-3 py-2.5 sm:py-3 text-xs align-top">
                                                    <FeedbackCell rating={u.feedback_rating} comment={u.feedback_comment} />
                                                </td>
                                            </tr>
                                        )
                                    })}
                                </tbody>
                            </table>
                        </div>
                        <div className="flex justify-between items-center mt-4">
                            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Page {usersData.page} of {Math.max(1, usersData.total_pages || 1)}</span>
                            <div className="flex gap-2">
                                <button className="admin-action-btn admin-action-btn--secondary text-xs px-3 py-1.5" style={{ height: 'auto' }}
                                    disabled={(usersData.page || 1) <= 1}
                                    onClick={() => setFilters((p) => ({ ...p, page: Math.max(1, p.page - 1) }))}><ChevronLeft size={14} /> Prev</button>
                                <button className="admin-action-btn admin-action-btn--secondary text-xs px-3 py-1.5" style={{ height: 'auto' }}
                                    disabled={(usersData.page || 1) >= Math.max(1, usersData.total_pages || 1)}
                                    onClick={() => setFilters((p) => ({ ...p, page: p.page + 1 }))}> Next <ChevronRight size={14} /></button>
                            </div>
                        </div>
                    </section>

                    {isRoot && (
                        <section className="admin-card p-4 sm:p-5">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                                <div>
                                    <h2 className="text-base sm:text-lg font-bold admin-section-title">Root Control Center</h2>
                                    <p className="text-xs mt-1 admin-section-subtitle">
                                        Open dedicated root workspace for financial overrides, trade history, and advanced controls.
                                    </p>
                                </div>
                                <button className="admin-action-btn admin-action-btn--primary text-sm" onClick={() => openRootControlPage()}>
                                    <Settings2 size={14} /> Open Root Control Center
                                </button>
                            </div>
                        </section>
                    )}

                    <section className="admin-card p-4 sm:p-5">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                                <h2 className="text-base sm:text-lg font-bold admin-section-title">Audit Log</h2>
                                <p className="text-xs mt-1 admin-section-subtitle">
                                    Open dedicated audit page for full action history and pagination.
                                </p>
                            </div>
                            <button className="admin-action-btn admin-action-btn--primary text-sm" onClick={openAuditLogPage}>
                                <Activity size={14} /> Open Audit Log
                            </button>
                        </div>
                    </section>
                </div>
            )}

            {/* Manage User Modal */}
            {modalUser && canManage && (
                <ManageUserModal user={modalUser} userDetail={selectedUserDetail} detailLoading={detailLoading}
                    actionState={actionState} setActionState={setActionState} onAction={runUserAction} onClose={closeManageModal} actionLoading={actionLoading} />
            )}

            {/* View-only user detail modal (read only for view_only admins) */}
            {modalUser && !canManage && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
                    style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }} onClick={closeManageModal}>
                    <div className="w-full max-w-lg max-h-[80vh] overflow-y-auto rounded-2xl animate-slide-up"
                        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', boxShadow: '0 24px 64px rgba(0,0,0,0.5)' }}
                        onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-between p-5" style={{ borderBottom: '1px solid var(--border)' }}>
                            <div className="min-w-0">
                                <h2 className="text-lg font-bold truncate">{modalUser.full_name || modalUser.username}</h2>
                                <p className="text-sm truncate" style={{ color: 'var(--text-secondary)' }}>{modalUser.email}</p>
                            </div>
                            <button className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ color: 'var(--text-muted)' }} onClick={closeManageModal}><X size={18} /></button>
                        </div>
                        <div className="p-5 flex flex-col gap-4">
                            {/* Identity */}
                            <div>
                                <div className="text-xs font-bold uppercase tracking-widest mb-2" style={{ color: 'var(--text-muted)' }}>Identity &amp; Contact</div>
                                <div className="grid grid-cols-2 gap-2">
                                    {[
                                        { label: 'Full Name', value: modalUser.full_name || '—' },
                                        { label: 'Username', value: modalUser.username || '—' },
                                        { label: 'Email', value: modalUser.email },
                                        { label: 'Mobile', value: modalUser.phone || 'Not set' },
                                        { label: 'Auth Provider', value: modalUser.auth_provider === 'google.com' ? '🔵 Google' : modalUser.auth_provider === 'password' ? '🔑 Email' : (modalUser.auth_provider || '—') },
                                        { label: 'Email Verified', value: modalUser.is_verified ? '✅ Yes' : '❌ No' },
                                    ].map(({ label, value }) => (
                                        <div key={label} className="p-2.5 rounded-xl" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                                            <div className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--text-muted)' }}>{label}</div>
                                            <div className="text-xs break-all">{value}</div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                            {/* Account status */}
                            <div>
                                <div className="text-xs font-bold uppercase tracking-widest mb-2" style={{ color: 'var(--text-muted)' }}>Status &amp; Dates</div>
                                <div className="grid grid-cols-2 gap-2">
                                    {[
                                        { label: 'Status', value: <StatusPill status={modalUser.account_status} /> },
                                        { label: 'Active', value: modalUser.is_active ? '✅ Yes' : '❌ No' },
                                        { label: 'Registered', value: safeDate(modalUser.created_at) },
                                        { label: 'Approved At', value: safeDate(modalUser.approved_at) },
                                        { label: 'Expires', value: safeDate(modalUser.access_expires_at) },
                                    ].map(({ label, value }) => (
                                        <div key={label} className="p-2.5 rounded-xl" style={{ background: 'var(--bg-muted)', border: '1px solid var(--border)' }}>
                                            <div className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--text-muted)' }}>{label}</div>
                                            <div className="text-xs font-mono">{value}</div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                            <div className="p-3 rounded-xl text-center text-sm" style={{ background: 'rgba(148,163,184,0.08)', color: 'var(--text-muted)' }}>
                                <EyeOff size={14} className="inline mr-1" /> View-only access. Contact root admin for management permissions.
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Admin Management Modal (root only) */}
            {showAdminModal && (
                <AdminManagementModal admins={adminsList} adminsLoading={adminsLoading}
                    onClose={() => setShowAdminModal(false)} onPromote={handlePromoteAdmin}
                    onUpdateLevel={handleUpdateAdminLevel} onRevoke={handleRevokeAdmin} />
            )}

            {/* Data Feed Modal (root only) */}
            {showDataFeedModal && (
                <DataFeedModal config={dataFeedConfig} draft={dataFeedDraft} setDraft={setDataFeedDraft}
                    loading={dataFeedLoading} saving={dataFeedSaving} onSave={handleSaveDataFeed} onClose={() => setShowDataFeedModal(false)} />
            )}
        </div>
    );
}
