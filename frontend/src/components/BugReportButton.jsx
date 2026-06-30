import React, { useState } from 'react';
import { Bug, X } from 'lucide-react';
import BugReportForm from './BugReportForm';

const BugReportButton = ({ onSuccess }) => {
  const [formOpen, setFormOpen] = useState(false);

  return (
    <>
      <div className="fixed bottom-5 right-5 z-[60] group">
        <button
          type="button"
          onClick={() => setFormOpen(true)}
          className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-rose-500 text-white shadow-lg shadow-rose-500/30 transition-transform duration-150 hover:scale-105 hover:bg-rose-600 focus:outline-none focus:ring-2 focus:ring-rose-400"
          aria-label="Report a bug"
          title="Report a bug"
        >
          <Bug className="h-6 w-6" />
        </button>
        <div className="pointer-events-none absolute right-16 top-1/2 -translate-y-1/2 rounded-full bg-slate-900 px-3 py-1 text-xs font-medium text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
          Report a bug
        </div>
      </div>

      <BugReportForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSuccess={onSuccess}
      />
    </>
  );
};

export default BugReportButton;
