// AcademyDashboardPage.jsx - AlphaSync Academy Student Dashboard
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
    GraduationCap, Clock, TrendingUp, Award, BookOpen,
    CheckCircle2, Circle, ArrowRight, Trophy, Flame,
} from 'lucide-react';
import academyApi from './api';
import StatTile from './components/StatTile';
import AcademyDonutChart from './components/AcademyDonutChart';
import { Skeleton } from '../components/ui';

export default function AcademyDashboardPage() {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        let cancelled = false;
        academyApi.getDashboard()
            .then((res) => { if (!cancelled) setData(res); })
            .catch(() => { if (!cancelled) setError('Could not load your dashboard right now.'); })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, []);

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

    const { stats, overall_progress, continue_learning, courses, upcoming_assignments, recent_quiz_scores, achievements } = data;

    const progressDonutData = [
        { name: 'Completed', value: overall_progress.completed_percent },
        { name: 'In Progress', value: overall_progress.in_progress_percent },
        { name: 'Not Started', value: overall_progress.not_started_percent },
    ];

    return (
        <div className="p-6 space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-semibold text-heading font-display">Welcome back, {data.first_name} 👋</h1>
                    <p className="text-sm text-text-secondary">Here's how your learning is going.</p>
                </div>
                <Link
                    to="/academy/mentor"
                    className="flex items-center gap-2 rounded-lg bg-brand-primary/15 px-3 py-2 text-sm font-medium text-brand-primary hover:bg-brand-primary/25 transition-colors"
                >
                    <GraduationCap className="h-4 w-4" /> Ask AI Mentor
                </Link>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <StatTile icon={Trophy} label="Learning Score" value={stats.xp_points} sublabel="XP points" accentClass="text-accent-amber" />
                <StatTile icon={Clock} label="Study Time" value={`${data.total_study_hours}h`} sublabel="Total logged" accentClass="text-accent-blue" />
                <StatTile icon={TrendingUp} label="Course Progress" value={`${overall_progress.percent}%`} sublabel="Overall average" accentClass="text-profit" />
                <StatTile icon={Flame} label="Study Streak" value={`${stats.study_streak_days}d`} sublabel="Consecutive days" accentClass="text-accent-purple" />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="lg:col-span-2 rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <div className="flex items-center justify-between mb-4">
                        <h2 className="text-sm font-semibold text-heading">Continue Learning</h2>
                        <Link to="/academy" className="text-xs text-brand-primary flex items-center gap-1">See all courses <ArrowRight className="h-3 w-3" /></Link>
                    </div>
                    <div className="space-y-3">
                        {continue_learning.length === 0 && <p className="text-sm text-text-secondary">No courses in progress. Start a new one!</p>}
                        {continue_learning.map((c) => (
                            <div key={c.course_id} className="flex items-center gap-4">
                                <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-brand-primary/10">
                                    <BookOpen className="h-5 w-5 text-brand-primary" />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm font-medium text-heading truncate">{c.title}</p>
                                    <div className="mt-1 h-1.5 w-full rounded-full bg-edge/10 overflow-hidden">
                                        <div className="h-full rounded-full bg-brand-primary" style={{ width: `${c.progress_percent}%` }} />
                                    </div>
                                </div>
                                <span className="text-xs text-text-secondary flex-shrink-0">{c.progress_percent}%</span>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <h2 className="text-sm font-semibold text-heading mb-2">Overall Progress</h2>
                    <AcademyDonutChart data={progressDonutData} centerLabel={`${overall_progress.percent}%`} height={200} />
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <h2 className="text-sm font-semibold text-heading mb-3">Upcoming Assignments</h2>
                    <div className="space-y-2">
                        {upcoming_assignments.length === 0 && <p className="text-sm text-text-secondary">Nothing due — you're all caught up.</p>}
                        {upcoming_assignments.map((a, i) => (
                            <div key={i} className="flex items-center justify-between text-sm">
                                <span className="text-text-secondary truncate">{a.title}</span>
                                <span className="text-xs text-accent-amber flex-shrink-0 ml-2">Due in {a.due_in_days}d</span>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <h2 className="text-sm font-semibold text-heading mb-3">Recent Quiz Scores</h2>
                    <div className="space-y-2">
                        {recent_quiz_scores.length === 0 && <p className="text-sm text-text-secondary">No quizzes taken yet.</p>}
                        {recent_quiz_scores.map((q, i) => (
                            <div key={i} className="flex items-center justify-between text-sm">
                                <span className="text-text-secondary truncate">{q.course_title}</span>
                                <span className={`text-xs font-medium flex-shrink-0 ml-2 ${q.score_percent >= 70 ? 'text-profit' : 'text-accent-amber'}`}>{q.score_percent}%</span>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <h2 className="text-sm font-semibold text-heading mb-3">Achievements</h2>
                    <div className="space-y-2">
                        {achievements.map((a, i) => (
                            <div key={i} className="flex items-center gap-2 text-sm">
                                {a.earned
                                    ? <CheckCircle2 className="h-4 w-4 text-profit flex-shrink-0" />
                                    : <Circle className="h-4 w-4 text-text-muted flex-shrink-0" />}
                                <span className={a.earned ? 'text-heading' : 'text-text-muted'}>{a.title}</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-sm font-semibold text-heading">My Courses</h2>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {courses.map((c) => (
                        <div key={c.course_id} className="rounded-lg border border-edge/5 bg-surface-950/40 p-4">
                            <div className="flex items-center gap-2 mb-2">
                                <Award className="h-4 w-4 text-brand-primary" />
                                <span className="text-xs uppercase tracking-wide text-text-muted">{c.category}</span>
                            </div>
                            <p className="text-sm font-medium text-heading">{c.title}</p>
                            <p className="text-xs text-text-secondary mb-2">{c.total_lessons} lessons</p>
                            <div className="h-1.5 w-full rounded-full bg-edge/10 overflow-hidden">
                                <div className="h-full rounded-full bg-brand-primary" style={{ width: `${c.progress_percent}%` }} />
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
