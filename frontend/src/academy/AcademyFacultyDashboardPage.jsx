// AcademyFacultyDashboardPage.jsx - AlphaSync Academy Faculty Dashboard
// Teacher-facing: their own courses, student roster with progress, and a
// quiz/grading overview. Gated by FacultyRoute (academy_role in
// faculty/institution_admin/super_admin) — see components/FacultyRoute.jsx.
import { useEffect, useMemo, useState } from 'react';
import { Users, BookOpen, TrendingUp, Target, Search } from 'lucide-react';
import academyApi from './api';
import StatTile from './components/StatTile';
import { Skeleton } from '../components/ui';

export default function AcademyFacultyDashboardPage() {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [query, setQuery] = useState('');

    useEffect(() => {
        let cancelled = false;
        academyApi.getFacultyDashboard()
            .then((res) => { if (!cancelled) setData(res); })
            .catch(() => { if (!cancelled) setError('Could not load your faculty dashboard right now.'); })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, []);

    const filteredRoster = useMemo(() => {
        if (!data) return [];
        const q = query.trim().toLowerCase();
        if (!q) return data.roster;
        return data.roster.filter((r) =>
            r.student_name?.toLowerCase().includes(q) ||
            r.student_email?.toLowerCase().includes(q) ||
            r.course_title?.toLowerCase().includes(q)
        );
    }, [data, query]);

    if (loading) {
        return (
            <div className="p-6 space-y-4">
                <Skeleton variant="text" width="240px" height="28px" />
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} variant="rect" height="90px" />)}
                </div>
                <Skeleton variant="rect" height="300px" />
            </div>
        );
    }

    if (error || !data) {
        return <div className="p-6 text-text-secondary">{error || 'No data available.'}</div>;
    }

    const { stats, courses, roster } = data;

    return (
        <div className="p-6 space-y-6">
            <div>
                <h1 className="text-2xl font-semibold text-heading font-display">Faculty Dashboard</h1>
                <p className="text-sm text-text-secondary">Your courses, students, and their progress at a glance.</p>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <StatTile icon={Users} label="Total Students" value={stats.total_students} accentClass="text-accent-blue" />
                <StatTile icon={BookOpen} label="Active Courses" value={stats.active_courses} accentClass="text-brand-primary" />
                <StatTile icon={TrendingUp} label="Avg Class Progress" value={`${stats.avg_class_progress}%`} accentClass="text-profit" />
                <StatTile icon={Target} label="Avg Quiz Score" value={`${stats.avg_quiz_score}%`} accentClass="text-accent-purple" />
            </div>

            <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                <h2 className="text-sm font-semibold text-heading mb-3">My Courses</h2>
                {courses.length === 0 ? (
                    <p className="text-sm text-text-secondary">You aren't assigned to any courses yet.</p>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                        {courses.map((c) => (
                            <div key={c.course_id} className="rounded-lg border border-edge/5 bg-surface-950/40 p-4">
                                <div className="flex items-center gap-2 mb-2">
                                    <BookOpen className="h-4 w-4 text-brand-primary" />
                                    <span className="text-xs uppercase tracking-wide text-text-muted">{c.category}</span>
                                </div>
                                <p className="text-sm font-medium text-heading">{c.title}</p>
                                <p className="text-xs text-text-secondary mb-2">
                                    {c.student_count} student{c.student_count === 1 ? '' : 's'} • Avg quiz {c.avg_quiz_score}%
                                </p>
                                <div className="h-1.5 w-full rounded-full bg-edge/10 overflow-hidden">
                                    <div className="h-full rounded-full bg-brand-primary" style={{ width: `${c.avg_progress}%` }} />
                                </div>
                                <span className="mt-1 block text-xs text-text-secondary">{c.avg_progress}% avg progress</span>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                <div className="flex items-center justify-between mb-3 gap-3">
                    <h2 className="text-sm font-semibold text-heading">Student Roster</h2>
                    <div className="relative w-56">
                        <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
                        <input
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="Search students or courses"
                            className="w-full h-8 pl-8 pr-2 rounded-lg border border-edge/10 bg-surface-950/40 text-xs text-heading placeholder:text-text-muted focus:outline-none"
                        />
                    </div>
                </div>
                {filteredRoster.length === 0 ? (
                    <p className="text-sm text-text-secondary">No students enrolled in your courses yet.</p>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="text-left text-xs uppercase tracking-wide text-text-muted border-b border-edge/10">
                                    <th className="pb-2 pr-4 font-medium">Student</th>
                                    <th className="pb-2 pr-4 font-medium">Course</th>
                                    <th className="pb-2 pr-4 font-medium">Progress</th>
                                    <th className="pb-2 font-medium">Last Activity</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredRoster.map((r, i) => (
                                    <tr key={i} className="border-b border-edge/5 last:border-0">
                                        <td className="py-2.5 pr-4">
                                            <div className="text-heading font-medium">{r.student_name}</div>
                                            <div className="text-xs text-text-secondary">{r.student_email}</div>
                                        </td>
                                        <td className="py-2.5 pr-4 text-text-secondary">{r.course_title}</td>
                                        <td className="py-2.5 pr-4">
                                            <div className="flex items-center gap-2">
                                                <div className="h-1.5 w-20 rounded-full bg-edge/10 overflow-hidden">
                                                    <div className="h-full rounded-full bg-brand-primary" style={{ width: `${r.progress_percent}%` }} />
                                                </div>
                                                <span className="text-xs text-text-secondary">{r.progress_percent}%</span>
                                            </div>
                                        </td>
                                        <td className="py-2.5 text-xs text-text-secondary">
                                            {r.last_activity_at ? new Date(r.last_activity_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : '—'}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );
}
