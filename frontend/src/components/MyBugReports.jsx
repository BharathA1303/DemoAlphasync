import React, { useEffect, useState } from 'react';
import { Loader2, Bug, Trash2, X } from 'lucide-react';
import api from '../services/api';

const STATUS_LABELS = {
  open: 'Open',
  'in-review': 'In Review',
  'in-progress': 'Under Process',
  resolved: 'Solved',
  closed: 'Closed',
  'wont-fix': "Won't Fix",
};

function statusLabel(status) {
  return STATUS_LABELS[status] || status || 'Unknown';
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

export default function MyBugReports({ refreshToken = 0 }) {
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState('');
  const [reports, setReports] = useState([]);
  const [selected, setSelected] = useState(null);
  const [open, setOpen] = useState(false);

  const fetchReports = async () => {
    setLoading(true);
    try {
      const res = await api.get('/bug-reports/my-reports?skip=0&limit=100');
      setReports(res.data.items || []);
    } finally {
      setLoading(false);
    }
  };

  const deleteReport = async (report) => {
    if (!report) return;
    if (!window.confirm('Delete this bug report? This cannot be undone.')) return;
    setDeletingId(report.id);
    try {
      await api.delete(`/bug-reports/${report.id}`);
      setOpen(false);
      setSelected(null);
      await fetchReports();
    } finally {
      setDeletingId('');
    }
  };

  useEffect(() => { fetchReports(); }, [refreshToken]);

  return (
    <section className="rounded-2xl border border-white/10 bg-[var(--bg-surface)] p-4 sm:p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-heading">My bug reports</h2>
          <p className="text-sm text-gray-500">Track submitted issues and admin responses.</p>
        </div>
        <button onClick={fetchReports} className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm hover:bg-white/5">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bug className="h-4 w-4" />} Refresh
        </button>
      </div>

      {loading ? (
        <div className="py-10 text-center text-gray-400"><Loader2 className="mx-auto h-5 w-5 animate-spin" /></div>
      ) : reports.length ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {reports.map((r) => (
            <button key={r.id} onClick={() => { setSelected(r); setOpen(true); }} className="rounded-xl border border-white/10 bg-white/[0.03] p-4 text-left hover:bg-white/[0.06]">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-heading">{r.title}</div>
                  <div className="mt-1 text-xs text-gray-500">{r.category}</div>
                </div>
                <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${badgeClass(r.status)}`}>{statusLabel(r.status)}</span>
              </div>
              <p className="mt-3 line-clamp-3 text-sm text-gray-400">{r.description}</p>
              <div className="mt-4 flex items-center justify-between text-xs text-gray-500">
                <span>{new Date(r.created_at).toLocaleDateString()}</span>
                <span>{statusLabel(r.status)}</span>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-white/10 p-10 text-center text-gray-400">
          No bug reports submitted yet.
        </div>
      )}

      {open && selected && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-3xl rounded-2xl border border-white/10 bg-[var(--bg-base)] shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
              <h3 className="text-lg font-bold text-heading">Bug report details</h3>
              <button onClick={() => setOpen(false)} className="rounded-lg p-2 text-gray-400 hover:bg-white/5 hover:text-heading"><X className="h-5 w-5" /></button>
            </div>
            <div className="max-h-[80vh] overflow-y-auto p-5 space-y-4">
              <Detail label="Title" value={selected.title} />
              <Detail label="Status" value={statusLabel(selected.status)} />
              <Detail label="Category" value={selected.category} />
              <Detail label="Description" value={selected.description} />
              <Detail label="Expected" value={selected.expected_behavior} />
              <Detail label="Actual" value={selected.actual_behavior} />
              <Detail label="Error" value={selected.error_message} />
              <Detail label="Admin notes" value={selected.admin_notes} />

              <div className="flex justify-end pt-2">
                <button
                  onClick={() => deleteReport(selected)}
                  disabled={deletingId === selected.id}
                  className="inline-flex items-center gap-2 rounded-lg border border-red-500/20 bg-red-500/10 px-4 py-2 text-sm font-semibold text-red-300 hover:bg-red-500/20 disabled:opacity-60"
                >
                  {deletingId === selected.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  Delete report
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function Detail({ label, value }) {
  if (!value) return null;
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
      <div className="text-xs uppercase tracking-wider text-gray-500">{label}</div>
      <div className="mt-1 whitespace-pre-wrap text-sm text-heading">{value}</div>
    </div>
  );
}
