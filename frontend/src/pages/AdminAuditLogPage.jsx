import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Activity, RefreshCw, Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';
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

export default function AdminAuditLogPage() {
    const navigate = useNavigate();

    const [loading, setLoading] = useState(true);
    const [auditData, setAuditData] = useState({ logs: [], total: 0, page: 1, total_pages: 1 });
    const [page, setPage] = useState(1);

    const loadAudit = useCallback(async (targetPage = 1) => {
        setLoading(true);
        try {
            const { data } = await adminApi.getAuditLog({ page: targetPage, per_page: 50 });
            setAuditData(data || { logs: [], total: 0, page: targetPage, total_pages: 1 });
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to load audit log'));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadAudit(page);
    }, [loadAudit, page]);

    return (
        <div className="admin-shell p-3 sm:p-4 md:p-5 lg:p-6">
            <header className="flex flex-wrap items-start sm:items-center justify-between gap-3 mb-4 sm:mb-5">
                <div>
                    <div className="flex items-center gap-2 mb-1">
                        <Activity size={14} style={{ color: 'var(--brand)' }} />
                        <span className="text-xs font-bold uppercase tracking-widest" style={{ color: 'var(--text-muted)' }}>Admin Workspace</span>
                    </div>
                    <h1 className="text-xl sm:text-2xl font-bold">Audit Log</h1>
                    <p className="text-xs sm:text-sm" style={{ color: 'var(--text-muted)' }}>
                        Every admin action is recorded for accountability.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <button className="admin-action-btn admin-action-btn--secondary text-sm" onClick={() => loadAudit(page)} disabled={loading}>
                        {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Refresh
                    </button>
                    <button className="admin-action-btn admin-action-btn--secondary text-sm" onClick={() => navigate('/admin/panel')}>
                        <ArrowLeft size={14} /> Back to Admin Panel
                    </button>
                </div>
            </header>

            <section className="admin-card overflow-hidden">
                <div className="flex items-center justify-between p-4 sm:p-5" style={{ borderBottom: '1px solid var(--border)' }}>
                    <div className="text-sm" style={{ color: 'var(--text-muted)' }}>
                        {auditData.total || 0} entries
                    </div>
                    <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
                        Page {auditData.page || page} of {Math.max(1, auditData.total_pages || 1)}
                    </div>
                </div>

                {loading ? (
                    <div className="p-5 text-sm" style={{ color: 'var(--text-muted)' }}>Loading audit log...</div>
                ) : (auditData.logs?.length ? (
                    <div className="overflow-x-auto">
                        <table className="w-full" style={{ borderCollapse: 'collapse', tableLayout: 'fixed', minWidth: 760 }}>
                            <colgroup>
                                <col style={{ width: '22%' }} /><col style={{ width: '16%' }} /><col style={{ width: '20%' }} />
                                <col style={{ width: '26%' }} /><col style={{ width: '16%' }} />
                            </colgroup>
                            <thead>
                                <tr style={{ background: 'var(--bg-muted)' }}>
                                    {['Time', 'Admin', 'Action', 'Target', 'IP'].map((h) => (
                                        <th key={h} className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider"
                                            style={{ color: 'var(--text-muted)', borderBottom: '1px solid var(--border)' }}>{h}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {auditData.logs.map((log) => (
                                    <tr key={log.id} style={{ borderBottom: '1px solid var(--border)' }}>
                                        <td className="px-4 py-3 text-xs font-mono" style={{ color: 'var(--text-secondary)' }}>{safeDate(log.created_at)}</td>
                                        <td className="px-4 py-3 text-sm truncate">{log.admin_name || 'Unknown'}</td>
                                        <td className="px-4 py-3">
                                            <span className="text-xs font-semibold px-2.5 py-1 rounded-full whitespace-nowrap"
                                                style={{ background: 'var(--brand-glow)', color: 'var(--brand)' }}>{log.action}</span>
                                        </td>
                                        <td className="px-4 py-3 text-sm truncate" style={{ color: 'var(--text-secondary)' }}>{log.target_user_name || '—'}</td>
                                        <td className="px-4 py-3 text-xs font-mono" style={{ color: 'var(--text-muted)' }}>{log.ip_address || '—'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <div className="p-5 text-sm" style={{ color: 'var(--text-muted)' }}>No audit entries found.</div>
                ))}

                <div className="flex justify-between items-center p-4 sm:p-5" style={{ borderTop: '1px solid var(--border)' }}>
                    <button
                        className="admin-action-btn admin-action-btn--secondary text-xs px-3 py-1.5"
                        style={{ height: 'auto' }}
                        disabled={(auditData.page || page) <= 1 || loading}
                        onClick={() => setPage((p) => Math.max(1, p - 1))}
                    >
                        Prev
                    </button>
                    <button
                        className="admin-action-btn admin-action-btn--secondary text-xs px-3 py-1.5"
                        style={{ height: 'auto' }}
                        disabled={(auditData.page || page) >= Math.max(1, auditData.total_pages || 1) || loading}
                        onClick={() => setPage((p) => p + 1)}
                    >
                        Next
                    </button>
                </div>
            </section>
        </div>
    );
}
