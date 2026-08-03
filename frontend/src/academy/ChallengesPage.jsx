// ChallengesPage.jsx - Financial & Algo-Trading Challenges Hub for Students
import { useEffect, useState } from 'react';
import { Award, Target, TrendingUp, Shield, CheckCircle2, Play, Zap, Flame, Clock, Sparkles } from 'lucide-react';
import academyApi from './api';
import { Skeleton } from '../components/ui';
import { toast } from 'react-hot-toast';

export default function ChallengesPage() {
    const [challenges, setChallenges] = useState([]);
    const [teacherInfo, setTeacherInfo] = useState(null);
    const [loading, setLoading] = useState(true);
    const [enrollingId, setEnrollingId] = useState(null);

    const loadData = async () => {
        try {
            setLoading(true);
            const [chRes, tRes] = await Promise.all([
                academyApi.getChallenges().catch(() => ({ challenges: [] })),
                academyApi.getAssignedTeacherInfo().catch(() => ({ assigned: false })),
            ]);
            setChallenges(chRes.challenges || []);
            setTeacherInfo(tRes);
        } catch (err) {
            toast.error('Could not load challenges catalog.');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadData();
    }, []);

    const handleEnroll = async (challengeId) => {
        try {
            setEnrollingId(challengeId);
            const res = await academyApi.enrollChallenge(challengeId);
            toast.success(res.message || 'Challenge activated!');
            loadData();
        } catch (err) {
            toast.error('Could not enroll in challenge.');
        } finally {
            setEnrollingId(null);
        }
    };

    if (loading) {
        return (
            <div className="p-6 space-y-4 max-w-7xl mx-auto">
                <Skeleton variant="text" width="280px" height="32px" />
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <Skeleton variant="rect" height="180px" />
                    <Skeleton variant="rect" height="180px" />
                </div>
            </div>
        );
    }

    return (
        <div className="p-6 space-y-6 max-w-7xl mx-auto">
            {/* Top Banner Header */}
            <div className="rounded-2xl border border-edge/10 bg-gradient-to-r from-surface-900 via-surface-900 to-violet-950/40 p-6 backdrop-blur-md relative overflow-hidden">
                <div className="absolute right-4 top-4 opacity-10 pointer-events-none">
                    <Award className="w-64 h-64 text-violet-400" />
                </div>
                <div className="relative z-10 space-y-2 max-w-2xl">
                    <div className="flex items-center gap-2">
                        <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 flex items-center gap-1">
                            <Sparkles className="h-3 w-3" />
                            LLM ACADEMY CHALLENGES
                        </span>
                    </div>
                    <h1 className="text-2xl sm:text-3xl font-bold text-heading font-display">
                        Financial & Trading Challenge Hub
                    </h1>
                    <p className="text-sm text-text-secondary">
                        Put your trading knowledge and LLM financial strategies to test. Complete challenges, control drawdown, and earn rewards!
                    </p>

                    {teacherInfo?.assigned && (
                        <div className="pt-2 flex items-center gap-2 text-xs text-brand-primary">
                            <Shield className="h-4 w-4" />
                            <span>Assigned Instructor: <strong>{teacherInfo.teacher?.full_name || teacherInfo.teacher?.email}</strong></span>
                        </div>
                    )}
                </div>
            </div>

            {/* Catalog Grid */}
            <div className="space-y-4">
                <h2 className="text-base font-bold text-heading flex items-center gap-2">
                    <Flame className="h-5 w-5 text-amber-400" />
                    <span>Active & Available Challenges ({challenges.length})</span>
                </h2>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {challenges.map((c) => (
                        <div
                            key={c.id}
                            className={`rounded-xl border p-5 space-y-4 transition-all ${
                                c.user_status === 'completed'
                                    ? 'border-profit/30 bg-profit/5'
                                    : c.user_status === 'in_progress'
                                    ? 'border-brand-primary/40 bg-surface-900/90 shadow-lg shadow-brand-primary/5'
                                    : 'border-edge/10 bg-surface-900/60 hover:border-edge/20'
                            }`}
                        >
                            <div className="flex items-start justify-between gap-3">
                                <div>
                                    <div className="flex items-center gap-2 mb-1">
                                        <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-surface-800 text-text-secondary border border-edge/10">
                                            {c.category}
                                        </span>
                                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                            c.difficulty === 'Beginner' ? 'bg-emerald-500/20 text-emerald-400' :
                                            c.difficulty === 'Intermediate' ? 'bg-amber-500/20 text-amber-400' :
                                            'bg-rose-500/20 text-rose-400'
                                        }`}>
                                            {c.difficulty}
                                        </span>
                                    </div>
                                    <h3 className="text-base font-bold text-heading">{c.title}</h3>
                                </div>
                                <div className="flex items-center gap-1 px-2.5 py-1 rounded-xl bg-amber-500/10 text-amber-300 font-bold text-xs border border-amber-500/20">
                                    <Zap className="h-3.5 w-3.5" />
                                    <span>+{c.reward_points} PTS</span>
                                </div>
                            </div>

                            <p className="text-xs text-text-secondary leading-relaxed">{c.description}</p>

                            {/* Target Metric & Progress */}
                            <div className="p-3 rounded-xl bg-surface-950/60 border border-edge/10 space-y-2">
                                <div className="flex justify-between text-xs font-medium">
                                    <span className="text-text-muted">Target: <strong className="text-heading capitalize">{c.target_metric.replace('_', ' ')} = {c.target_value}</strong></span>
                                    {c.user_status !== 'not_started' && (
                                        <span className="text-brand-primary font-bold">{c.user_progress_percent}% Complete</span>
                                    )}
                                </div>

                                {c.user_status !== 'not_started' && (
                                    <div className="h-2 w-full rounded-full bg-surface-800 overflow-hidden">
                                        <div
                                            className={`h-full rounded-full transition-all duration-500 ${
                                                c.user_status === 'completed' ? 'bg-profit' : 'bg-brand-primary'
                                            }`}
                                            style={{ width: `${c.user_progress_percent}%` }}
                                        />
                                    </div>
                                )}
                            </div>

                            {/* Action Button */}
                            <div className="flex items-center justify-between pt-1">
                                <div className="text-[11px] text-text-muted flex items-center gap-1">
                                    <Clock className="h-3.5 w-3.5" />
                                    <span>Ongoing evaluation</span>
                                </div>

                                {c.user_status === 'completed' ? (
                                    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-profit/20 text-profit text-xs font-bold border border-profit/30">
                                        <CheckCircle2 className="h-4 w-4" />
                                        <span>Challenge Completed</span>
                                    </span>
                                ) : c.user_status === 'in_progress' ? (
                                    <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-brand-primary/10 text-brand-primary text-xs font-semibold border border-brand-primary/20">
                                        <Play className="h-3.5 w-3.5" />
                                        <span>Active & Tracking</span>
                                    </span>
                                ) : (
                                    <button
                                        onClick={() => handleEnroll(c.id)}
                                        disabled={enrollingId === c.id}
                                        className="px-4 py-1.5 rounded-xl bg-brand-primary text-surface-950 text-xs font-bold hover:bg-brand-primary/90 transition-all shadow-md shadow-brand-primary/10 disabled:opacity-50"
                                    >
                                        {enrollingId === c.id ? 'Activating...' : 'Accept Challenge'}
                                    </button>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
