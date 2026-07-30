import React, { useEffect, useMemo, useState } from 'react';
import { Loader2, RefreshCw, Filter, Eye, Pencil, X } from 'lucide-react';
import adminApi from '../services/adminApi';

const STATUS_OPTIONS = [
  { value: 'open', label: 'Open' },
  { value: 'in-review', label: 'In Review' },
  { value: 'in-progress', label: 'Under Process' },
  { value: 'resolved', label: 'Solved' },
  { value: 'closed', label: 'Closed' },
  { value: 'wont-fix', label: "Won't Fix" },
];

function statusLabel(status) {
  return STATUS_OPTIONS.find((item) => item.value === status)?.label || status || 'Unknown';
}

function badgeClass(status) {
  const map = {
    open: 'bg-rose-500/15 text-rose-300 border-rose-500/20',
    'in-review': 'bg-sky-500/15 text-sky-300 border-sky-500/20',
    'in-progress': 'bg-amber-500/15 text-amber-300 border-amber-500/20',
    resolved: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/20',
    closed: 'bg-slate-500/15 text-slate-300 border-slate-500/20',
    'wont-fix': 'bg-violet-500/15 text-violet-300 border-violet-500/20',
  };
  return map[status] || 'bg-white/10 text-white/70 border-white/10';
}

function severityClass(severity) {
  const map = {
    low: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/20',
    medium: 'bg-sky-500/15 text-sky-300 border-sky-500/20',
    high: 'bg-amber-500/15 text-amber-300 border-amber-500/20',
    critical: 'bg-rose-500/15 text-rose-300 border-rose-500/20',
  };
  return map[severity] || 'bg-white/10 text-white/70 border-white/10';
}

export default function AdminBugReports() {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [stats, setStats] = useState(null);
  const [reports, setReports] = useState([]);
  const [filters, setFilters] = useState({ status: '', severity: '', category: '' });
  const [selected, setSelected] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [newStatus, setNewStatus] = useState('open');
  const [notes, setNotes] = useState('');
  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (filters.status) p.set('status', filters.status);
    if (filters.severity) p.set('severity', filters.severity);
    if (filters.category) p.set('category', filters.category);
    p.set('skip', '0');
    p.set('limit', '100');
    return p.toString();
  }, [filters]);

  const fetchData = async () => {
    setLoading(true);
    setError('');
    try {
      const params = Object.fromEntries(new URLSearchParams(query));
      const [statsRes, reportsRes] = await Promise.all([
        adminApi.getBugReportStats(),
        adminApi.listBugReports(params),
      ]);
      setStats(statsRes.data);
      setReports(reportsRes.data.items || []);
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Unable to load bug reports.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, [query]);

  const openDetails = (report) => {
    setSelected(report);
    setDetailOpen(true);
  };

  const openUpdate = (report) => {
    setSelected(report);
    setNewStatus(report.status || 'open');
    setNotes('');
    setStatusOpen(true);
  };

  const submitUpdate = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      await adminApi.updateBugReportStatus(
        selected.id,
        { status: newStatus, admin_notes: notes },
      );
      setStatusOpen(false);
      await fetchData();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat title="Total Reports" value={stats?.total ?? 0} />
        <Stat title="Open" value={stats?.by_status?.open ?? 0} accent="text-rose-300" />
        <Stat title="In Progress" value={stats?.by_status?.['in-progress'] ?? 0} accent="text-amber-300" />
        <Stat title="Critical" value={stats?.by_severity?.critical ?? 0} accent="text-rose-300" />
      </div>

      <div className="rounded-2xl border border-white/10 bg-[var(--bg-surface)] p-4">
        <div className="flex flex-wrap items-center gap-3">
          <Filter className="h-4 w-4 text-cyan-400" />
          <select
            className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-heading"
            style={{ colorScheme: 'dark' }}
            value={filters.status}
            onChange={(e) => setFilters((p) => ({ ...p, status: e.target.value }))}
          >
            <option value="" style={{ backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}>All Status</option>
            {STATUS_OPTIONS.map((item) => (
              <option
                key={item.value}
                value={item.value}
                style={{ backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
              >
                {item.label}
              </option>
            ))}
          </select>
          <select className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm" value={filters.severity} onChange={(e) => setFilters((p) => ({ ...p, severity: e.target.value }))}>
            <option value="">All Severity</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>
          <input className="min-w-0 flex-1 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm" placeholder="Category filter" value={filters.category} onChange={(e) => setFilters((p) => ({ ...p, category: e.target.value }))} />
          <button onClick={fetchData} className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm hover:bg-white/5">
            <RefreshCw className="h-4 w-4" /> Refresh
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-2xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      ) : null}

      <div className="overflow-hidden rounded-2xl border border-white/10 bg-[var(--bg-surface)]">
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-white/[0.03] text-xs uppercase tracking-wider text-gray-400">
              <tr>
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Severity</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Category</th>
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td className="px-4 py-10 text-center text-gray-400" colSpan="7"><Loader2 className="mx-auto h-5 w-5 animate-spin" /></td></tr>
              ) : reports.length ? reports.map((r) => (
                <tr key={r.id} className="border-t border-white/5">
                  <td className="px-4 py-3 font-medium text-heading">{r.title}</td>
                  <td className="px-4 py-3"><span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${severityClass(r.severity)}`}>{r.severity}</span></td>
                  <td className="px-4 py-3"><span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${badgeClass(r.status)}`}>{statusLabel(r.status)}</span></td>
                  <td className="px-4 py-3 text-gray-300">{r.category}</td>
                  <td className="px-4 py-3 text-gray-300">{r.user_email || '—'}</td>
                  <td className="px-4 py-3 text-gray-400">{new Date(r.created_at).toLocaleString()}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-2">
                      <button onClick={() => openDetails(r)} className="inline-flex items-center gap-1 rounded-lg border border-white/10 px-3 py-2 text-xs hover:bg-white/5"><Eye className="h-3.5 w-3.5" /> View</button>
                      <button onClick={() => openUpdate(r)} className="inline-flex items-center gap-1 rounded-lg border border-cyan-500/20 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-300 hover:bg-cyan-500/15"><Pencil className="h-3.5 w-3.5" /> Update</button>
                    </div>
                  </td>
                </tr>
              )) : (
                <tr><td className="px-4 py-10 text-center text-gray-400" colSpan="7">No bug reports found.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {detailOpen && selected && (
        <ModalCard title="Bug Report Details" onClose={() => setDetailOpen(false)}>
          <DetailGrid report={selected} />
        </ModalCard>
      )}

      {statusOpen && selected && (
        <ModalCard title="Update Bug Report" onClose={() => setStatusOpen(false)}>
          <div className="space-y-4">
            <select
              className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm text-heading"
              style={{ colorScheme: 'dark' }}
              value={newStatus}
              onChange={(e) => setNewStatus(e.target.value)}
            >
              {STATUS_OPTIONS.map((item) => (
                <option
                  key={item.value}
                  value={item.value}
                  style={{ backgroundColor: 'var(--bg-surface)', color: 'var(--text-primary)' }}
                >
                  {item.label}
                </option>
              ))}
            </select>
            <textarea className="min-h-[120px] w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm" placeholder="Internal notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            <div className="flex justify-end gap-3">
              <button onClick={() => setStatusOpen(false)} className="rounded-lg border border-white/10 px-4 py-2 text-sm hover:bg-white/5">Cancel</button>
              <button onClick={submitUpdate} disabled={saving} className="inline-flex items-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-600 disabled:opacity-70">
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Save
              </button>
            </div>
          </div>
        </ModalCard>
      )}
    </div>
  );
}

function Stat({ title, value, accent = 'text-cyan-300' }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-[var(--bg-surface)] p-4">
      <div className="text-xs uppercase tracking-wider text-gray-400">{title}</div>
      <div className={`mt-2 text-3xl font-extrabold ${accent}`}>{value}</div>
    </div>
  );
}

function ModalCard({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="w-full max-w-4xl rounded-2xl border border-white/10 bg-[var(--bg-base)] shadow-2xl">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <h3 className="text-lg font-bold text-heading">{title}</h3>
          <button onClick={onClose} className="rounded-lg p-2 text-gray-400 hover:bg-white/5 hover:text-heading"><X className="h-5 w-5" /></button>
        </div>
        <div className="max-h-[80vh] overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  );
}

function DetailGrid({ report }) {
  const rows = [
    ['Title', report.title],
    ['Status', statusLabel(report.status)],
    ['Category', report.category],
  ];
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        {rows.map(([k, v]) => (
          <div key={k} className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
            <div className="text-xs uppercase tracking-wider text-gray-500">{k}</div>
            <div className="mt-1 text-sm text-heading break-words">{v}</div>
          </div>
        ))}
      </div>
      <Section title="Description" value={report.description} />
      <Section title="Expected behavior" value={report.expected_behavior} />
      <Section title="Actual behavior" value={report.actual_behavior} />
      <Section title="Error message" value={report.error_message} mono />
      {report.admin_notes ? <Section title="Admin notes" value={report.admin_notes} /> : null}
    </div>
  );
}

function Section({ title, value, mono = false }) {
  if (!value) return null;
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
      <div className="mb-2 text-xs uppercase tracking-wider text-gray-500">{title}</div>
      <div className={`whitespace-pre-wrap text-sm text-heading ${mono ? 'font-mono' : ''}`}>{value}</div>
    </div>
  );
}
