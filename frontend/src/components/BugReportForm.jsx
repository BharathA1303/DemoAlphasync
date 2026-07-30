import React, { useMemo, useState } from 'react';
import { Loader2 } from 'lucide-react';
import api from '../services/api';

function getInitialForm() {
  return {
    title: '',
    description: '',
    category: 'General',
    expected_behavior: '',
    actual_behavior: '',
    error_message: '',
  };
}

export default function BugReportForm({ onSuccess }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [form, setForm] = useState(getInitialForm);

  const inputClass = useMemo(() => 'input-field text-heading placeholder:text-gray-500', []);
  const update = (key) => (e) => setForm((p) => ({ ...p, [key]: e.target.value }));

  const normalizeError = (err) => {
    const detail = err?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      const messages = detail.map((item) => item?.msg).filter(Boolean).join(', ');
      return messages || 'Invalid bug report payload.';
    }
    if (detail && typeof detail === 'object') {
      return detail?.message || detail?.error || 'Invalid bug report payload.';
    }
    return 'Failed to submit bug report.';
  };

  const resetAll = () => {
    setForm(getInitialForm());
    setError('');
    setSuccess('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    if (form.title.trim().length < 5) return setError('Title must be at least 5 characters.');
    if (form.description.trim().length < 10) return setError('Description must be at least 10 characters.');

    setLoading(true);
    try {
      await api.post('/bug-reports/submit', {
        title: form.title.trim(),
        description: form.description.trim(),
        category: form.category.trim() || 'General',
        expected_behavior: form.expected_behavior.trim() || null,
        actual_behavior: form.actual_behavior.trim() || null,
        error_message: form.error_message.trim() || null,
      });

      setSuccess('Bug report submitted successfully.');
      onSuccess?.();
      resetAll();
      setTimeout(() => setSuccess(''), 1800);
    } catch (err) {
      setError(normalizeError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="rounded-2xl border border-white/10 bg-[var(--bg-surface)] p-5 sm:p-6 shadow-[0_10px_30px_rgba(0,0,0,0.08)]">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-xl font-bold text-heading">Report a bug</h2>
          <p className="mt-1 text-sm text-gray-500">Share the issue, the expected result, and the actual result.</p>
        </div>
        <div className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs text-gray-400">
          Simple report
        </div>
      </div>

      {error && <div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300">{error}</div>}
      {success && <div className="mt-4 rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">{success}</div>}

      <form onSubmit={handleSubmit} className="mt-4 space-y-4">
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 sm:p-5 space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-heading">Basics</h3>
            <p className="mt-1 text-xs text-gray-500">Title, category, and description are the most important fields.</p>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <label className="lg:col-span-2">
              <span className="label-text">Title *</span>
              <input className={inputClass} value={form.title} onChange={update('title')} placeholder="Short summary of the issue" />
            </label>

            <label>
              <span className="label-text">Category</span>
              <select className={inputClass} value={form.category} onChange={update('category')}>
                <option value="General">General</option>
                <option value="UI Bug">UI Bug</option>
                <option value="Functional Bug">Functional Bug</option>
                <option value="Performance">Performance</option>
                <option value="Data Issue">Data Issue</option>
                <option value="Security">Security</option>
                <option value="Workflow">Workflow</option>
                <option value="Other">Other</option>
              </select>
            </label>

          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 sm:p-5 space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-heading">Details</h3>
            <p className="mt-1 text-xs text-gray-500">Explain what should happen and what happened instead.</p>
          </div>

          <label className="block">
            <span className="label-text">Description *</span>
            <textarea
              className="input-field min-h-[120px] resize-y text-heading placeholder:text-gray-500"
              style={{ height: 'auto' }}
              value={form.description}
              onChange={update('description')}
              placeholder="Describe what happened and what you expected."
            />
          </label>

          <label className="block">
            <span className="label-text">Expected behavior</span>
            <textarea
              className="input-field min-h-[96px] resize-y text-heading placeholder:text-gray-500"
              style={{ height: 'auto' }}
              value={form.expected_behavior}
              onChange={update('expected_behavior')}
              placeholder="What should have happened?"
            />
          </label>

          <label className="block">
            <span className="label-text">Actual behavior</span>
            <textarea
              className="input-field min-h-[96px] resize-y text-heading placeholder:text-gray-500"
              style={{ height: 'auto' }}
              value={form.actual_behavior}
              onChange={update('actual_behavior')}
              placeholder="What actually happened?"
            />
          </label>

          <label className="block">
            <span className="label-text">Error message</span>
            <textarea
              className="input-field min-h-[88px] resize-y font-mono text-sm text-heading placeholder:text-gray-500"
              style={{ height: 'auto' }}
              value={form.error_message}
              onChange={update('error_message')}
              placeholder="Paste any stack trace or error text here"
            />
          </label>
        </div>

        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={resetAll}
            className="rounded-xl border border-white/10 px-5 py-3 text-sm font-medium text-heading hover:bg-white/5"
          >
            Clear
          </button>
          <button
            type="submit"
            disabled={loading}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-cyan-500 px-5 py-3 text-sm font-semibold text-white hover:bg-cyan-600 disabled:opacity-70"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Submit Bug Report
          </button>
        </div>
      </form>
    </section>
  );
}