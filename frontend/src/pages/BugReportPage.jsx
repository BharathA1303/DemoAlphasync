import { useState } from 'react';
import BugReportForm from '../components/BugReportForm';
import MyBugReports from '../components/MyBugReports';

export default function BugReportPage() {
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <section className="rounded-2xl border border-edge/10 bg-[var(--bg-surface)] p-5 shadow-[0_10px_30px_rgba(0,0,0,0.08)]">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-heading">Bug Reports</h1>
              <p className="mt-1 text-sm text-gray-500">
                Report issues, attach screenshots, and track the status of your reports here.
              </p>
            </div>
            <div className="text-xs text-gray-500">
              Submit issues from this page or from Settings.
            </div>
          </div>
        </section>

        <BugReportForm onSuccess={() => setRefreshKey((value) => value + 1)} />

        <MyBugReports refreshToken={refreshKey} />
      </div>
    </div>
  );
}
