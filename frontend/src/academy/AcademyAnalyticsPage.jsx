// AcademyAnalyticsPage.jsx - AI Learning Analytics dashboard
import { useEffect, useState } from 'react';
import {
    Brain, Clock, TrendingUp, Target, Sparkles, Lightbulb, ArrowUpRight, Compass,
} from 'lucide-react';
import academyApi from './api';
import StatTile from './components/StatTile';
import AcademyDonutChart from './components/AcademyDonutChart';
import AcademyLineChart from './components/AcademyLineChart';
import ActivityHeatmap from './components/ActivityHeatmap';
import SkillMasteryCard from './components/SkillMasteryCard';
import { Skeleton } from '../components/ui';

export default function AcademyAnalyticsPage() {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        let cancelled = false;
        academyApi.getAnalytics()
            .then((res) => { if (!cancelled) setData(res); })
            .catch(() => { if (!cancelled) setError('Could not load your analytics right now.'); })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, []);

    if (loading) {
        return (
            <div className="p-6 space-y-4">
                <Skeleton variant="text" width="260px" height="28px" />
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

    const {
        learning_score, total_study_hours, course_progress_percent, average_quiz_score,
        strengths, weaknesses, skill_mastery, time_by_topic, activity_heatmap,
        learning_progress_over_time, performance_trend, insights, recommendations, suggested_actions,
    } = data;

    const strengthWeaknessData = [
        ...strengths.map((s) => ({ name: s.skill, value: s.mastery_percent })),
        ...weaknesses.map((w) => ({ name: w.skill, value: w.mastery_percent })),
    ];
    const timeByTopicData = time_by_topic.map((t) => ({ name: t.topic, value: t.minutes }));

    return (
        <div className="p-6 space-y-6">
            <div>
                <h1 className="text-2xl font-semibold text-heading font-display flex items-center gap-2">
                    <Brain className="h-6 w-6 text-brand-primary" /> AI Learning Analytics
                </h1>
                <p className="text-sm text-text-secondary">Insights into how you're learning, powered by your activity data.</p>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <StatTile icon={Sparkles} label="Learning Score" value={learning_score} sublabel="/ 100" accentClass="text-accent-amber" />
                <StatTile icon={Clock} label="Total Study Time" value={`${total_study_hours}h`} accentClass="text-accent-blue" />
                <StatTile icon={TrendingUp} label="Course Progress" value={`${course_progress_percent}%`} accentClass="text-profit" />
                <StatTile icon={Target} label="Avg Quiz Score" value={`${average_quiz_score}%`} accentClass="text-accent-purple" />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="lg:col-span-2 rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <h2 className="text-sm font-semibold text-heading mb-2">Learning Progress Over Time</h2>
                    <AcademyLineChart data={learning_progress_over_time} lines={[{ dataKey: 'value', name: 'Progress %', color: '#00bcd4' }]} />
                </div>
                <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <h2 className="text-sm font-semibold text-heading mb-2">Strengths vs Weaknesses</h2>
                    <AcademyDonutChart data={strengthWeaknessData} height={200} />
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <h2 className="text-sm font-semibold text-heading mb-2">Time Spent by Topic</h2>
                    <AcademyDonutChart data={timeByTopicData} height={220} />
                </div>
                <div className="lg:col-span-2 rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <h2 className="text-sm font-semibold text-heading mb-4">Learning Activity Heatmap</h2>
                    <ActivityHeatmap weeks={activity_heatmap} />
                </div>
            </div>

            <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                <h2 className="text-sm font-semibold text-heading mb-2">Performance Trend</h2>
                <AcademyLineChart
                    data={performance_trend}
                    lines={[
                        { dataKey: 'quiz_score', name: 'Quiz Score', color: '#00bcd4' },
                        { dataKey: 'course_progress', name: 'Course Progress', color: '#10b981' },
                    ]}
                />
            </div>

            <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                <h2 className="text-sm font-semibold text-heading mb-3">Skill Mastery Breakdown</h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {skill_mastery.map((s) => (
                        <SkillMasteryCard key={s.skill} skill={s.skill} mastery_percent={s.mastery_percent} level={s.level} />
                    ))}
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <h2 className="text-sm font-semibold text-heading mb-3 flex items-center gap-2"><Lightbulb className="h-4 w-4 text-accent-amber" /> AI Learning Insights</h2>
                    <div className="space-y-3">
                        {insights.map((ins, i) => (
                            <div key={i}>
                                <p className="text-sm font-medium text-heading">{ins.title}</p>
                                <p className="text-xs text-text-secondary">{ins.description}</p>
                            </div>
                        ))}
                    </div>
                </div>
                <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <h2 className="text-sm font-semibold text-heading mb-3 flex items-center gap-2"><Compass className="h-4 w-4 text-accent-blue" /> Recommended for You</h2>
                    <div className="space-y-2">
                        {recommendations.length === 0 && <p className="text-sm text-text-secondary">You're doing great across the board!</p>}
                        {recommendations.map((r, i) => (
                            <div key={i}>
                                <p className="text-sm font-medium text-heading">{r.title}</p>
                                <p className="text-xs text-text-secondary">{r.reason}</p>
                            </div>
                        ))}
                    </div>
                </div>
                <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-5">
                    <h2 className="text-sm font-semibold text-heading mb-3 flex items-center gap-2"><ArrowUpRight className="h-4 w-4 text-profit" /> AI Suggested Actions</h2>
                    <div className="space-y-3">
                        {suggested_actions.map((a, i) => (
                            <div key={i} className="flex items-center justify-between gap-2">
                                <p className="text-sm text-text-secondary">{a.action}</p>
                                <span className="text-xs font-medium text-brand-primary flex-shrink-0">{a.cta}</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
