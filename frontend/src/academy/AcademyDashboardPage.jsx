// AcademyDashboardPage.jsx - Ultimate Academic LLM Student AI Hub & Curiosity Trading Dashboard
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
    GraduationCap, Clock, TrendingUp, Award, BookOpen,
    CheckCircle2, Circle, ArrowRight, Trophy, Flame, Sparkles,
    Zap, Target, Shield, HelpCircle, Activity, Play, AlertCircle, RefreshCw
} from 'lucide-react';
import academyApi from './api';
import StatTile from './components/StatTile';
import AcademyDonutChart from './components/AcademyDonutChart';
import { Skeleton } from '../components/ui';
import { toast } from 'react-hot-toast';

// Curiosity questions pool to trigger student engagement & LLM interaction
const CURIOSITY_QUESTIONS = [
    {
        title: "Market Mystery: Volatility Crush ⚡",
        question: "Why does Options Implied Volatility (IV) plummet right after an earnings announcement even if the stock price jumps +8%?",
        prompt: "Explain option implied volatility crush after earnings and show me how a trader can profit from it."
    },
    {
        title: "Quant Insight: Delta Hedging 🛡️",
        question: "How do institutional market makers stay delta-neutral when selling 10,000 call options?",
        prompt: "Explain delta neutral hedging for market makers with a concrete numerical example."
    },
    {
        title: "Algo Challenge: Sharpe Ratio Booster 📈",
        question: "What key indicator adjustment reduces false buy signals in a sideways, range-bound market?",
        prompt: "How can I combine ADX and RSI to filter out false breakout signals in an automated algo strategy?"
    }
];

export default function AcademyDashboardPage() {
    const navigate = useNavigate();
    const [data, setData] = useState(null);
    const [challenges, setChallenges] = useState([]);
    const [teacherInfo, setTeacherInfo] = useState(null);
    const [loading, setLoading] = useState(true);

    // Scenario simulator state
    const [selectedScenario, setSelectedScenario] = useState(null);
    const [simulating, setSimulating] = useState(false);

    // Curiosity card index
    const [curiosityIdx, setCuriosityIdx] = useState(0);

    const loadAllStudentData = async () => {
        try {
            setLoading(true);
            const [dashRes, chRes, tRes] = await Promise.all([
                academyApi.getDashboard().catch(() => null),
                academyApi.getChallenges().catch(() => ({ challenges: [] })),
                academyApi.getAssignedTeacherInfo().catch(() => ({ assigned: false })),
            ]);
            setData(dashRes);
            setChallenges(chRes.challenges || []);
            setTeacherInfo(tRes);
        } catch (err) {
            toast.error('Could not load student hub data.');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadAllStudentData();
    }, []);

    const handleRunScenario = (scenario) => {
        setSelectedScenario(scenario);
        setSimulating(true);
        setTimeout(() => {
            setSimulating(false);
        }, 600);
    };

    const handleAskAICuriosty = (promptText) => {
        navigate('/academy/mentor', { state: { initialPrompt: promptText } });
    };

    if (loading) {
        return (
            <div className="p-6 space-y-4 max-w-7xl mx-auto">
                <Skeleton variant="text" width="240px" height="28px" />
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} variant="rect" height="90px" />)}
                </div>
                <Skeleton variant="rect" height="300px" />
            </div>
        );
    }

    if (!data) {
        return <div className="p-6 text-text-secondary">Dashboard unavailable right now. Please refresh.</div>;
    }

    const { stats, overall_progress, continue_learning, courses, upcoming_assignments, recent_quiz_scores, achievements } = data;

    const progressDonutData = [
        { name: 'Completed', value: overall_progress.completed_percent },
        { name: 'In Progress', value: overall_progress.in_progress_percent },
        { name: 'Not Started', value: overall_progress.not_started_percent },
    ];

    const currentCuriosity = CURIOSITY_QUESTIONS[curiosityIdx];
    const activeChallenges = challenges.filter(c => c.user_status === 'in_progress' || c.user_status === 'completed');

    // Calculate level (every 1000 XP is 1 Level)
    const currentLevel = Math.floor((stats?.xp_points || 1200) / 1000) + 1;
    const currentLevelXP = (stats?.xp_points || 1200) % 1000;

    return (
        <div className="p-6 space-y-6 max-w-7xl mx-auto">
            {/* GAMIFIED HEADER BANNER */}
            <div className="rounded-2xl border border-edge/10 bg-gradient-to-r from-surface-900 via-surface-900 to-indigo-950/50 p-6 backdrop-blur-md relative overflow-hidden shadow-xl">
                <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6 relative z-10">
                    <div className="space-y-2 max-w-xl">
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="px-3 py-1 rounded-full text-xs font-extrabold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 flex items-center gap-1.5">
                                <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
                                STUDENT TRADER & STRATEGEST
                            </span>
                            <span className="px-3 py-1 rounded-full text-xs font-extrabold bg-amber-500/20 text-amber-300 border border-amber-500/30 flex items-center gap-1">
                                <Flame className="h-3.5 w-3.5 text-amber-400" />
                                {stats.study_streak_days}-DAY STREAK 🔥
                            </span>
                        </div>
                        <h1 className="text-2xl sm:text-3xl font-bold text-heading font-display">
                            Welcome back, {data.first_name || 'Student'} 👋
                        </h1>
                        <p className="text-xs sm:text-sm text-text-secondary leading-relaxed">
                            Master quantitative trading, prompt AI strategies, and execute paper trades to rank up your financial level.
                        </p>

                        {teacherInfo?.assigned && (
                            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-surface-950/80 border border-edge/10 text-xs text-brand-primary">
                                <Shield className="h-4 w-4 text-violet-400" />
                                <span>Assigned Teacher: <strong>{teacherInfo.teacher?.full_name || teacherInfo.teacher?.email}</strong></span>
                            </div>
                        )}
                    </div>

                    {/* Level & XP Progress Meter */}
                    <div className="bg-surface-950/80 border border-edge/10 rounded-2xl p-4 min-w-[260px] space-y-3 shadow-lg">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <Trophy className="h-5 w-5 text-amber-400" />
                                <div>
                                    <div className="text-xs font-bold text-heading">LEVEL {currentLevel}</div>
                                    <div className="text-[10px] text-text-secondary">Quant Apprentice</div>
                                </div>
                            </div>
                            <span className="text-xs font-bold text-amber-300">{stats.xp_points} XP</span>
                        </div>
                        <div className="space-y-1">
                            <div className="flex justify-between text-[10px] text-text-muted">
                                <span>Next Level: L{currentLevel + 1}</span>
                                <span>{currentLevelXP} / 1000 XP</span>
                            </div>
                            <div className="h-2 w-full rounded-full bg-surface-800 overflow-hidden">
                                <div className="h-full rounded-full bg-gradient-to-r from-amber-500 to-emerald-400 transition-all duration-500" style={{ width: `${(currentLevelXP / 1000) * 100}%` }} />
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* QUICK STAT TILES */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <StatTile icon={Trophy} label="Total XP Points" value={stats.xp_points} sublabel="Rank Points" accentClass="text-accent-amber" />
                <StatTile icon={Clock} label="Study Time" value={`${data.total_study_hours}h`} sublabel="Hours Logged" accentClass="text-accent-blue" />
                <StatTile icon={TrendingUp} label="Course Mastery" value={`${overall_progress.percent}%`} sublabel="Completed" accentClass="text-profit" />
                <StatTile icon={Target} label="Active Challenges" value={activeChallenges.length || challenges.length} sublabel="Enrolled" accentClass="text-violet-400" />
            </div>

            {/* CURIOSITY OF THE DAY (AI Financial Mystery Card) */}
            <div className="rounded-2xl border border-amber-500/20 bg-gradient-to-r from-amber-950/20 via-surface-900 to-surface-900 p-5 space-y-3 relative">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <HelpCircle className="h-5 w-5 text-amber-400" />
                        <span className="text-xs font-extrabold uppercase tracking-wider text-amber-300">Market Curiosity of the Day</span>
                    </div>
                    <button
                        onClick={() => setCuriosityIdx((curiosityIdx + 1) % CURIOSITY_QUESTIONS.length)}
                        className="text-xs text-text-muted hover:text-heading flex items-center gap-1"
                    >
                        <RefreshCw className="h-3.5 w-3.5" /> Next Question
                    </button>
                </div>
                <div>
                    <h3 className="text-base font-bold text-heading mb-1">{currentCuriosity.title}</h3>
                    <p className="text-xs sm:text-sm text-text-secondary">{currentCuriosity.question}</p>
                </div>
                <div className="pt-2 flex items-center gap-3">
                    <button
                        onClick={() => handleAskAICuriosty(currentCuriosity.prompt)}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-500 text-surface-950 font-bold text-xs hover:bg-amber-400 transition-all shadow-md shadow-amber-500/10"
                    >
                        <Sparkles className="h-4 w-4" />
                        <span>Ask AI Copilot for Explanation</span>
                    </button>
                    <Link
                        to="/terminal"
                        className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-surface-800 border border-edge/10 text-heading font-medium text-xs hover:bg-surface-700 transition-all"
                    >
                        <Play className="h-3.5 w-3.5 text-emerald-400" />
                        <span>Test in Trading Terminal</span>
                    </Link>
                </div>
            </div>

            {/* 2-COLUMN MAIN HUB: Challenges HUD & What-If Scenario Simulator */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Active Challenges HUD */}
                <div className="rounded-2xl border border-edge/10 bg-surface-900/80 p-5 space-y-4">
                    <div className="flex items-center justify-between border-b border-edge/10 pb-3">
                        <div className="flex items-center gap-2">
                            <Zap className="h-5 w-5 text-amber-400" />
                            <h2 className="text-base font-bold text-heading">Trading Challenges HUD</h2>
                        </div>
                        <Link to="/academy/challenges" className="text-xs font-semibold text-brand-primary hover:underline flex items-center gap-1">
                            View All <ArrowRight className="h-3.5 w-3.5" />
                        </Link>
                    </div>

                    <div className="space-y-3">
                        {challenges.slice(0, 3).map((c) => (
                            <div key={c.id} className="p-3.5 rounded-xl border border-edge/10 bg-surface-950/60 space-y-2">
                                <div className="flex items-center justify-between">
                                    <span className="text-xs font-bold text-heading">{c.title}</span>
                                    <span className="text-[10px] font-extrabold px-2 py-0.5 rounded bg-amber-500/10 text-amber-300">+{c.reward_points} PTS</span>
                                </div>
                                <div className="flex justify-between text-[11px] text-text-secondary">
                                    <span>Target: {c.target_metric} = {c.target_value}</span>
                                    <span className="font-semibold text-brand-primary">{c.user_progress_percent}%</span>
                                </div>
                                <div className="h-1.5 w-full rounded-full bg-surface-800 overflow-hidden">
                                    <div className="h-full rounded-full bg-brand-primary" style={{ width: `${c.user_progress_percent}%` }} />
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* What-If Market Scenario AI Simulator */}
                <div className="rounded-2xl border border-edge/10 bg-surface-900/80 p-5 space-y-4">
                    <div className="flex items-center justify-between border-b border-edge/10 pb-3">
                        <div className="flex items-center gap-2">
                            <Activity className="h-5 w-5 text-violet-400" />
                            <h2 className="text-base font-bold text-heading">What-If Market Stress Simulator</h2>
                        </div>
                        <span className="text-[10px] uppercase font-bold text-text-muted">Interactive AI Tool</span>
                    </div>
                    <p className="text-xs text-text-secondary">
                        Simulate market macro shocks on your virtual portfolio to observe drawdown resilience.
                    </p>

                    <div className="grid grid-cols-3 gap-2">
                        <button
                            onClick={() => handleRunScenario({ name: 'Market Crash (-10%)', impact: '-$1,240', advice: 'Hedge using NIFTY OTM Puts' })}
                            className="p-3 rounded-xl border border-rose-500/20 bg-rose-500/10 hover:bg-rose-500/20 text-left transition-all"
                        >
                            <div className="text-xs font-bold text-rose-400">Crash (-10%)</div>
                            <div className="text-[10px] text-text-muted mt-1">High Volatility</div>
                        </button>

                        <button
                            onClick={() => handleRunScenario({ name: 'Bull Rally (+15%)', impact: '+$2,850', advice: 'Use Trailing Stop Loss to lock gains' })}
                            className="p-3 rounded-xl border border-emerald-500/20 bg-emerald-500/10 hover:bg-emerald-500/20 text-left transition-all"
                        >
                            <div className="text-xs font-bold text-emerald-400">Rally (+15%)</div>
                            <div className="text-[10px] text-text-muted mt-1">Bullish Momentum</div>
                        </button>

                        <button
                            onClick={() => handleRunScenario({ name: 'VIX Spike (+40%)', impact: '-$450', advice: 'Sell Covered Calls for IV crush' })}
                            className="p-3 rounded-xl border border-amber-500/20 bg-amber-500/10 hover:bg-amber-500/20 text-left transition-all"
                        >
                            <div className="text-xs font-bold text-amber-400">VIX Spike</div>
                            <div className="text-[10px] text-text-muted mt-1">Options Volatility</div>
                        </button>
                    </div>

                    {selectedScenario && (
                        <div className="p-3.5 rounded-xl border border-edge/10 bg-surface-950 space-y-2 animate-fade-in">
                            <div className="flex items-center justify-between text-xs">
                                <span className="font-bold text-heading">Simulated Scenario: {selectedScenario.name}</span>
                                <span className={selectedScenario.impact.startsWith('+') ? 'text-profit font-bold' : 'text-loss font-bold'}>
                                    Est. PnL: {selectedScenario.impact}
                                </span>
                            </div>
                            <p className="text-xs text-text-secondary">
                                💡 <strong>AI Copilot Advice:</strong> {selectedScenario.advice}
                            </p>
                        </div>
                    )}
                </div>
            </div>

            {/* CONTINUE LEARNING & COURSE MASTERY */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-2 rounded-2xl border border-edge/10 bg-surface-900/80 p-5 space-y-4">
                    <div className="flex items-center justify-between">
                        <h2 className="text-base font-bold text-heading">Continue Course Roadmap</h2>
                        <span className="text-xs text-text-muted">{continue_learning.length} Courses in progress</span>
                    </div>

                    <div className="space-y-3">
                        {continue_learning.map((c) => (
                            <div key={c.course_id} className="p-4 rounded-xl border border-edge/10 bg-surface-950/60 flex items-center justify-between gap-4">
                                <div className="flex items-center gap-3">
                                    <div className="h-10 w-10 rounded-xl bg-brand-primary/10 flex items-center justify-center flex-shrink-0">
                                        <BookOpen className="h-5 w-5 text-brand-primary" />
                                    </div>
                                    <div>
                                        <h3 className="text-sm font-semibold text-heading">{c.title}</h3>
                                        <div className="text-xs text-text-secondary mt-0.5">{c.progress_percent}% completed</div>
                                    </div>
                                </div>

                                <div className="flex items-center gap-3">
                                    <div className="w-24 hidden sm:block">
                                        <div className="h-1.5 w-full rounded-full bg-surface-800 overflow-hidden">
                                            <div className="h-full rounded-full bg-brand-primary" style={{ width: `${c.progress_percent}%` }} />
                                        </div>
                                    </div>
                                    <Link
                                        to="/academy/mentor"
                                        className="px-3 py-1.5 rounded-lg bg-brand-primary/15 text-brand-primary text-xs font-semibold hover:bg-brand-primary/25 transition-all"
                                    >
                                        Resume
                                    </Link>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="rounded-2xl border border-edge/10 bg-surface-900/80 p-5 space-y-4">
                    <h2 className="text-base font-bold text-heading">Overall Mastery Breakdown</h2>
                    <AcademyDonutChart data={progressDonutData} centerLabel={`${overall_progress.percent}%`} height={200} />
                </div>
            </div>
        </div>
    );
}
