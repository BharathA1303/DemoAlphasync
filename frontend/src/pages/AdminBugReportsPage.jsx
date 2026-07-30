import AdminBugReports from '../components/AdminBugReports';

export default function AdminBugReportsPage() {
  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <section className="rounded-2xl border border-edge/10 bg-[var(--bg-surface)] p-5 shadow-[0_10px_30px_rgba(0,0,0,0.08)]">
          <h1 className="text-2xl font-bold tracking-tight text-heading">Bug Report Admin</h1>
          <p className="mt-1 text-sm text-gray-500">
            Review user reports, update status, and add internal notes.
          </p>
        </section>

        <AdminBugReports />
      </div>
    </div>
  );
}
