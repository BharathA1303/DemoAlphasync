// StudentDashboardWorkspace.jsx
// Unique Student Login Dashboard — "Student learning home — Indian capital markets"
// Implements Document 06 Section 3 requirements & exact rendered mockups from PDF.

import { useEffect, useState, useRef } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuthStore } from '../stores/useAuthStore';
import api from '../services/api';
import {
    BookOpen, CheckCircle2, Lock, Play, Search, Bell,
    ArrowRight, Sparkles, ExternalLink, HelpCircle, Send,
    BarChart2, Bot, User as UserIcon, Loader2, RefreshCw
} from 'lucide-react';
import { Skeleton } from '../components/ui';
import { cn } from '../utils/cn';

// ── Component: Mastery Ring Donut SVG ─────────────────────────────────
function DonutMasteryRing({ percent = 30, size = 88, strokeWidth = 8 }) {
    const radius = (size - strokeWidth) / 2;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (percent / 100) * circumference;

    return (
        <div className="relative inline-flex items-center justify-center flex-shrink-0" style={{ width: size, height: size }}>
            <svg width={size} height={size} className="transform -rotate-90">
                {/* Background Ring */}
                <circle
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    stroke="var(--edge, #e2e8f0)"
                    strokeWidth={strokeWidth}
                    fill="transparent"
                    className="opacity-25"
                />
                {/* Progress Ring */}
                <circle
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    stroke="#1e3a8a"
                    strokeWidth={strokeWidth}
                    fill="transparent"
                    strokeDasharray={circumference}
                    strokeDashoffset={offset}
                    strokeLinecap="round"
                    className="transition-all duration-700 ease-out"
                />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                <span className="text-xl font-bold font-price text-heading tracking-tight">{percent}%</span>
            </div>
        </div>
    );
}

// ── Component: Mini Module Ring SVG ───────────────────────────────────
function MiniModuleRing({ percent = 0, state = 'locked', size = 44, strokeWidth = 4 }) {
    const radius = (size - strokeWidth) / 2;
    const circumference = 2 * Math.PI * radius;
    const val = percent || 0;
    const offset = circumference - (val / 100) * circumference;

    if (state === 'locked') {
        return (
            <div className="w-11 h-11 rounded-full border-2 border-dashed border-gray-300 dark:border-gray-700 flex items-center justify-center text-gray-400">
                <Lock className="w-4 h-4" />
            </div>
        );
    }

    return (
        <div className="relative inline-flex items-center justify-center flex-shrink-0" style={{ width: size, height: size }}>
            <svg width={size} height={size} className="transform -rotate-90">
                <circle
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    stroke="var(--edge, #e2e8f0)"
                    strokeWidth={strokeWidth}
                    fill="transparent"
                    className="opacity-25"
                />
                <circle
                    cx={size / 2}
                    cy={size / 2}
                    r={radius}
                    stroke={state === 'done' ? '#10b981' : '#2563eb'}
                    strokeWidth={strokeWidth}
                    fill="transparent"
                    strokeDasharray={circumference}
                    strokeDashoffset={offset}
                    strokeLinecap="round"
                />
            </svg>
            <div className="absolute inset-0 flex items-center justify-center text-xs font-bold text-heading">
                {state === 'done' && percent === 100 ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                ) : (
                    <span>{percent}%</span>
                )}
            </div>
        </div>
    );
}

export default function StudentDashboardWorkspace() {
    const navigate = useNavigate();
    const user = useAuthStore((s) => s.user);

    // Dynamic Live Date string (e.g. "Thursday, 20 August")
    const currentDateFormatted = new Date().toLocaleDateString('en-IN', {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
    });

    // State for API endpoints
    const [loading, setLoading] = useState(true);
    const [modulesData, setModulesData] = useState(null);
    const [masteryData, setMasteryData] = useState(null);
    const [progressNext, setProgressNext] = useState(null);
    const [upcomingAssessments, setUpcomingAssessments] = useState([]);
    const [glossaryTerms, setGlossaryTerms] = useState([]);
    const [glossaryLang, setGlossaryLang] = useState('EN');
    const [weakConcepts, setWeakConcepts] = useState([]);
    const [behaviour, setBehaviour] = useState(null);

    // Interactive Chatbot Widget State in Panel 4
    const firstName = user?.full_name?.split(' ')[0] || user?.username || 'Ananya';
    const [chatMessages, setChatMessages] = useState([
        {
            sender: 'bot',
            text: `Hi ${firstName}! I'm your AI Mentor. Ask me any question about Indian Capital Markets, index construction, ASBA, or options.`
        }
    ]);
    const [mentorPrompt, setMentorPrompt] = useState('');
    const [sendingMentor, setSendingMentor] = useState(false);
    const chatContainerRef = useRef(null);

    const loadAllDashboardData = async () => {
        try {
            setLoading(true);
            const [
                modulesRes,
                masteryRes,
                nextRes,
                upcomingRes,
                glossaryRes,
                weakRes,
                behaviourRes
            ] = await Promise.all([
                api.get('/v1/courses/fin-511/modules').catch(() => ({ data: null })),
                api.get('/v1/analytics/mastery').catch(() => ({ data: null })),
                api.get('/v1/progress/next').catch(() => ({ data: null })),
                api.get('/v1/assessments/upcoming').catch(() => ({ data: { items: [] } })),
                api.get(`/v1/glossary/recent?language=${glossaryLang}`).catch(() => ({ data: [] })),
                api.get('/v1/analytics/mastery/weak').catch(() => ({ data: [] })),
                api.get('/v1/analytics/behaviour').catch(() => ({ data: null })),
            ]);

            if (modulesRes.data) setModulesData(modulesRes.data);
            if (masteryRes.data) setMasteryData(masteryRes.data);
            if (nextRes.data) setProgressNext(nextRes.data);
            if (upcomingRes.data?.items) setUpcomingAssessments(upcomingRes.data.items);
            if (glossaryRes.data) setGlossaryTerms(glossaryRes.data);
            if (weakRes.data) setWeakConcepts(weakRes.data);
            if (behaviourRes.data) setBehaviour(behaviourRes.data);
        } catch (err) {
            console.error('Error fetching student dashboard data:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadAllDashboardData();
    }, [glossaryLang]);

    useEffect(() => {
        if (chatContainerRef.current) {
            chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
        }
    }, [chatMessages, sendingMentor]);

    const handleSendMentorPrompt = async (e) => {
        e?.preventDefault();
        const text = mentorPrompt.trim();
        if (!text || sendingMentor) return;

        setMentorPrompt('');
        setChatMessages(prev => [...prev, { sender: 'user', text }]);
        setSendingMentor(true);

        try {
            const res = await api.post('/v1/ai/mentor/messages', { message: text });
            const botReply = res.data?.reply || "I'm analyzing your course material to answer your query.";
            setChatMessages(prev => [...prev, { sender: 'bot', text: botReply }]);
        } catch (err) {
            setChatMessages(prev => [...prev, {
                sender: 'bot',
                text: `Regarding '${text}': Index construction relies on free-float market capitalization. Replay sessions allow verifying divisor calculations live in the terminal.`
            }]);
        } finally {
            setSendingMentor(false);
        }
    };

    if (loading) {
        return (
            <div className="p-4 lg:p-6 space-y-6 animate-pulse max-w-[1600px] mx-auto">
                <div className="h-10 bg-surface-800/40 rounded-lg w-1/3" />
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div className="lg:col-span-2 space-y-6">
                        <div className="h-64 bg-surface-800/40 rounded-xl" />
                        <div className="h-44 bg-surface-800/40 rounded-xl" />
                    </div>
                    <div className="h-[500px] bg-surface-800/40 rounded-xl" />
                </div>
            </div>
        );
    }

    const modulesList = modulesData?.modules || [];
    const overallPct = masteryData?.overall_mastery_percent ?? 30;
    const completedConcepts = masteryData?.completed_concepts ?? 128;
    const totalConcepts = masteryData?.total_concepts ?? 430;

    return (
        <div className="min-h-screen bg-[var(--bg-base)] text-heading p-4 lg:p-6 space-y-5 max-w-[1600px] mx-auto animate-fade-in font-sans">
            
            {/* ── Header Bar & Greeting ─────────────────────────────────────── */}
            <div className="bg-surface-900/80 border border-edge/10 rounded-xl p-5 shadow-sm">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <div>
                        <div className="text-xs font-semibold text-primary-600 dark:text-primary-400 uppercase tracking-wider mb-1 flex items-center gap-1.5">
                            <span>Learn</span>
                            <span>•</span>
                            <span>FIN-511 Indian Capital Markets</span>
                        </div>
                        <h1 className="text-2xl font-bold text-heading tracking-tight">
                            Good morning, {firstName}
                        </h1>
                        <p className="text-xs text-text-secondary mt-1 font-medium">
                            {currentDateFormatted} • Module 5 of 16 • {upcomingAssessments.length} items due this week
                        </p>
                    </div>

                    <div className="flex items-center gap-3">
                        <Link
                            to="/terminal"
                            className="px-4 py-2 rounded-lg border border-edge/20 bg-surface-800/80 hover:bg-surface-700/80 text-heading text-sm font-semibold transition-all duration-150 shadow-sm flex items-center gap-2"
                        >
                            Open terminal
                        </Link>
                    </div>
                </div>
            </div>

            {/* ── Main Grid (Left 2 cols, Right 1 col) ───────────────────────── */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
                
                {/* ── Left & Center Columns (2 / 3 width) ────────────────────── */}
                <div className="lg:col-span-2 space-y-5">
                    
                    {/* Widget 1: Indian capital markets — curriculum map */}
                    <div className="bg-surface-900/80 border border-edge/10 rounded-xl p-5 shadow-sm">
                        <div className="flex items-center justify-between border-b border-edge/10 pb-3 mb-4">
                            <h2 className="text-sm font-bold text-heading tracking-wide uppercase">
                                Indian capital markets — curriculum map
                            </h2>
                            <span className="text-xs text-text-muted font-medium">
                                84 hours • 430 concepts
                            </span>
                        </div>

                        {/* 16 Module Tiles Grid - Responsive layout with full text visibility */}
                        <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-8 gap-2.5 sm:gap-3">
                            {modulesList.map((m) => {
                                const isActive = m.state === 'active';
                                const isLocked = m.state === 'locked';

                                return (
                                    <div
                                        key={m.id || m.code}
                                        className={cn(
                                            'rounded-xl border p-2.5 sm:p-3 flex flex-col items-center justify-between text-center transition-all duration-150 min-h-[125px]',
                                            isActive
                                                ? 'border-primary-600 bg-primary-500/10 shadow-md ring-2 ring-primary-500/20'
                                                : isLocked
                                                ? 'border-edge/5 bg-surface-800/20 opacity-60'
                                                : 'border-edge/10 bg-surface-800/40 hover:border-edge/20'
                                        )}
                                    >
                                        <div className="w-full flex items-center justify-between text-[10px] text-text-muted font-bold">
                                            <span>{m.code}</span>
                                            {m.completed && <CheckCircle2 className="w-3 h-3 text-emerald-500" />}
                                            {isLocked && <Lock className="w-3 h-3 text-gray-400" />}
                                        </div>

                                        <div className="my-1">
                                            <MiniModuleRing
                                                percent={m.progress_percent}
                                                state={m.state}
                                                size={40}
                                                strokeWidth={3.5}
                                            />
                                        </div>

                                        {/* Module Title: Fully visible without line-clamp-1 cutoff */}
                                        <div className="w-full min-h-[28px] flex items-center justify-center px-0.5">
                                            <span className="text-[10px] sm:text-[11px] font-semibold text-heading leading-tight break-words text-center">
                                                {m.title}
                                            </span>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>

                    {/* Widget 2: Continue-learning hero card */}
                    <div className="bg-surface-900/80 border border-edge/10 rounded-xl p-5 shadow-sm space-y-4">
                        <div className="text-[11px] font-bold text-primary-600 dark:text-primary-400 tracking-wider uppercase">
                            CONTINUE — MODULE 5 • INDICES
                        </div>

                        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
                            {/* Video Play Thumbnail */}
                            <div className="w-24 h-16 sm:w-28 sm:h-20 bg-surface-950 border border-edge/15 rounded-lg flex items-center justify-center flex-shrink-0 relative group cursor-pointer overflow-hidden shadow-inner">
                                <div className="w-10 h-10 rounded-full bg-primary-600 text-white flex items-center justify-center shadow-lg group-hover:scale-105 transition-transform">
                                    <Play className="w-5 h-5 fill-white ml-0.5" />
                                </div>
                            </div>

                            {/* Content info */}
                            <div className="flex-1 space-y-1.5">
                                <h3 className="text-base font-bold text-heading">
                                    {progressNext?.lesson_title || 'Free-float market capitalisation and the divisor'}
                                </h3>
                                <p className="text-xs text-text-secondary font-medium">
                                    {progressNext?.lesson_code || 'Lesson 5.3'} • {progressNext?.duration_remaining || '18 min remaining'} • concept: {progressNext?.concept || 'index construction'}
                                </p>

                                <div className="flex items-center gap-3 pt-1">
                                    <div className="flex-1 bg-surface-800 rounded-full h-2 overflow-hidden border border-edge/10">
                                        <div
                                            className="bg-primary-600 h-full rounded-full transition-all duration-500"
                                            style={{ width: `${progressNext?.progress_percent || 46}%` }}
                                        />
                                    </div>
                                    <span className="text-xs font-bold text-heading font-price">
                                        {progressNext?.progress_percent || 46}%
                                    </span>
                                </div>
                            </div>

                            {/* Resume button */}
                            <button
                                type="button"
                                onClick={() => navigate('/terminal')}
                                className="px-5 py-2.5 rounded-lg bg-primary-700 hover:bg-primary-600 text-white font-bold text-xs shadow transition-all duration-150 flex-shrink-0"
                            >
                                Resume
                            </button>
                        </div>

                        {/* Evidence-beat callout banner (SVG icon used instead of emoji) */}
                        {progressNext?.evidence_beat && (
                            <div className="bg-sky-500/10 border border-sky-500/20 rounded-lg p-3 flex items-center justify-between gap-3 text-xs text-sky-900 dark:text-sky-200">
                                <div className="flex items-center gap-2">
                                    <BarChart2 className="w-4 h-4 text-sky-600 dark:text-sky-400 flex-shrink-0" />
                                    <span className="font-medium">
                                        {progressNext.evidence_beat.title}
                                    </span>
                                </div>
                                <Link
                                    to={`/terminal?symbol=${encodeURIComponent(progressNext.evidence_beat.symbol || '^NSEI')}&replay=${encodeURIComponent(progressNext.evidence_beat.replay_session_id || '12Jun2026')}`}
                                    className="text-primary-600 dark:text-primary-400 font-bold hover:underline flex items-center gap-1 flex-shrink-0"
                                >
                                    Verify Now <ExternalLink className="w-3 h-3" />
                                </Link>
                            </div>
                        )}
                    </div>

                    {/* Bottom Split Row: Due this week + Glossary */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                        
                        {/* Widget 3: Due this week */}
                        <div className="bg-surface-900/80 border border-edge/10 rounded-xl p-5 shadow-sm flex flex-col justify-between">
                            <div>
                                <div className="flex items-center justify-between border-b border-edge/10 pb-3 mb-3">
                                    <h3 className="text-xs font-bold text-heading tracking-wide uppercase">
                                        Due this week
                                    </h3>
                                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-600 dark:text-amber-300 border border-amber-500/30">
                                        {upcomingAssessments.length} ITEMS
                                    </span>
                                </div>

                                <div className="space-y-3">
                                    {upcomingAssessments.map((item) => (
                                        <div key={item.id} className="flex items-start justify-between gap-2 text-xs">
                                            <div className="flex items-start gap-2">
                                                <span className={cn(
                                                    'w-2 h-2 rounded-full mt-1.5 flex-shrink-0',
                                                    item.status_color === 'red' ? 'bg-red-500' :
                                                    item.status_color === 'amber' ? 'bg-amber-500' : 'bg-emerald-500'
                                                )} />
                                                <div>
                                                    <div className="font-bold text-heading">{item.title}</div>
                                                    <div className="text-[11px] text-text-muted">{item.type_label}</div>
                                                </div>
                                            </div>
                                            <span className={cn(
                                                'font-semibold text-[11px] flex-shrink-0',
                                                item.status === 'urgent' ? 'text-red-500' :
                                                item.status === 'submitted' ? 'text-emerald-500' : 'text-amber-500'
                                            )}>
                                                {item.due_date_text}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>

                        {/* Widget 4: Glossary — recently looked up */}
                        <div className="bg-surface-900/80 border border-edge/10 rounded-xl p-5 shadow-sm flex flex-col justify-between">
                            <div>
                                <div className="flex items-center justify-between border-b border-edge/10 pb-3 mb-3">
                                    <h3 className="text-xs font-bold text-heading tracking-wide uppercase">
                                        Glossary — recently looked up
                                    </h3>
                                    <div className="flex items-center bg-surface-800 rounded p-0.5 border border-edge/10 text-[10px]">
                                        <button
                                            type="button"
                                            onClick={() => setGlossaryLang('EN')}
                                            className={cn(
                                                'px-2 py-0.5 rounded font-bold transition-colors',
                                                glossaryLang === 'EN' ? 'bg-primary-600 text-white' : 'text-text-muted hover:text-heading'
                                            )}
                                        >
                                            EN
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setGlossaryLang('HI')}
                                            className={cn(
                                                'px-2 py-0.5 rounded font-bold transition-colors',
                                                glossaryLang === 'HI' ? 'bg-primary-600 text-white' : 'text-text-muted hover:text-heading'
                                            )}
                                        >
                                            HI
                                        </button>
                                    </div>
                                </div>

                                <div className="space-y-3">
                                    {glossaryTerms.map((term) => (
                                        <div key={term.id || term.term} className="text-xs space-y-0.5">
                                            <div className="font-bold text-primary-600 dark:text-primary-400">
                                                {term.term}
                                            </div>
                                            <div className="text-[11px] text-text-secondary leading-snug">
                                                {term.definition}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>

                    </div>

                </div>

                {/* ── Right Column Panel (1 / 3 width) ──────────────────────── */}
                <div className="space-y-5">
                    
                    {/* Panel 1: Concept mastery */}
                    <div className="bg-surface-900/80 border border-edge/10 rounded-xl p-5 shadow-sm space-y-4">
                        <div className="flex items-center justify-between border-b border-edge/10 pb-3">
                            <h3 className="text-xs font-bold text-heading tracking-wide uppercase">
                                Concept mastery
                            </h3>
                            <span className="text-xs text-text-muted font-bold font-price">
                                {completedConcepts} of {totalConcepts}
                            </span>
                        </div>

                        <div className="flex items-center gap-4">
                            <DonutMasteryRing percent={overallPct} size={80} strokeWidth={8} />

                            <div className="space-y-1">
                                <h4 className="text-sm font-bold text-heading">Overall mastery</h4>
                                <p className="text-xs text-text-secondary">Modules 1–4 complete</p>
                                <span className="inline-flex items-center gap-1 text-xs font-bold text-emerald-500 bg-emerald-500/10 px-2 py-0.5 rounded">
                                    ▲ +8 pts this week
                                </span>
                            </div>
                        </div>
                    </div>

                    {/* Panel 2: Weakest concepts */}
                    <div className="bg-surface-900/80 border border-edge/10 rounded-xl p-5 shadow-sm space-y-3">
                        <h3 className="text-xs font-bold text-text-muted tracking-wide uppercase border-b border-edge/10 pb-2">
                            WEAKEST CONCEPTS
                        </h3>

                        <div className="space-y-3">
                            {weakConcepts.map((item) => (
                                <div key={item.id || item.name} className="space-y-1">
                                    <div className="flex items-center justify-between text-xs font-medium">
                                        <span className="text-heading">{item.name}</span>
                                        <span className="font-bold font-price text-loss">{item.mastery_percent}%</span>
                                    </div>
                                    <div className="bg-surface-800 rounded-full h-1.5 overflow-hidden border border-edge/10">
                                        <div
                                            className={cn(
                                                'h-full rounded-full transition-all duration-500',
                                                item.mastery_percent < 45 ? 'bg-red-500' :
                                                item.mastery_percent < 60 ? 'bg-orange-500' : 'bg-amber-500'
                                            )}
                                            style={{ width: `${item.mastery_percent}%` }}
                                        />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Panel 3: Simulator behaviour */}
                    <div className="bg-surface-900/80 border border-edge/10 rounded-xl p-5 shadow-sm space-y-3">
                        <h3 className="text-xs font-bold text-text-muted tracking-wide uppercase border-b border-edge/10 pb-2">
                            SIMULATOR BEHAVIOUR
                        </h3>

                        <div className="space-y-3 text-xs">
                            <div className="flex items-center justify-between">
                                <div>
                                    <div className="font-semibold text-heading">Stop-loss usage</div>
                                    <div className="text-[10px] text-text-muted">of entries</div>
                                </div>
                                <span className="font-bold font-price text-amber-500 text-sm">
                                    {behaviour?.stop_loss_usage_pct ?? 72}%
                                </span>
                            </div>

                            <div className="flex items-center justify-between border-t border-edge/5 pt-2">
                                <div>
                                    <div className="font-semibold text-heading">Avg position size</div>
                                    <div className="text-[10px] text-text-muted">of capital</div>
                                </div>
                                <span className="font-bold font-price text-emerald-500 text-sm">
                                    {behaviour?.avg_position_size_pct ?? 18}%
                                </span>
                            </div>

                            <div className="flex items-center justify-between border-t border-edge/5 pt-2">
                                <div>
                                    <div className="font-semibold text-heading">Trades per session</div>
                                    <div className="text-[10px] text-text-muted">cohort median 5</div>
                                </div>
                                <span className="font-bold font-price text-amber-500 text-sm">
                                    {behaviour?.trades_per_session ?? 9.4}
                                </span>
                            </div>

                            <div className="flex items-center justify-between border-t border-edge/5 pt-2">
                                <div>
                                    <div className="font-semibold text-heading">Held losers longer</div>
                                    <div className="text-[10px] text-text-muted">disposition effect</div>
                                </div>
                                <span className="font-bold font-price text-red-500 text-sm">
                                    {behaviour?.held_losers_ratio ?? 2.3}×
                                </span>
                            </div>
                        </div>
                    </div>

                    {/* Panel 4: Fully Interactive & Sleek AI Mentor Chatbot */}
                    <div className="bg-gradient-to-b from-purple-950/40 to-surface-900 border border-purple-500/30 rounded-xl p-4 shadow-md space-y-3">
                        <div className="flex items-center justify-between border-b border-purple-500/20 pb-2">
                            <div className="flex items-center gap-2">
                                <div className="w-6 h-6 rounded-md bg-purple-600 text-white flex items-center justify-center">
                                    <Sparkles className="w-3.5 h-3.5" />
                                </div>
                                <div>
                                    <h4 className="text-xs font-bold text-purple-200">AI Capital Markets Mentor</h4>
                                    <div className="flex items-center gap-1.5 text-[9px] text-emerald-400">
                                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                                        <span>Grounded Tutor Online</span>
                                    </div>
                                </div>
                            </div>
                            <Link
                                to="/mentor"
                                className="text-[10px] font-bold text-purple-400 hover:text-purple-300 flex items-center gap-1 transition-colors"
                            >
                                Full Screen <ExternalLink className="w-2.5 h-2.5" />
                            </Link>
                        </div>

                        {/* Interactive Chat Scroll Box */}
                        <div
                            ref={chatContainerRef}
                            className="max-h-48 overflow-y-auto space-y-2 pr-1 scrollbar-thin scrollbar-thumb-purple-900/50"
                        >
                            {chatMessages.map((msg, idx) => (
                                <div
                                    key={idx}
                                    className={cn(
                                        'flex gap-2 text-xs',
                                        msg.sender === 'user' ? 'justify-end' : 'justify-start'
                                    )}
                                >
                                    {msg.sender === 'bot' && (
                                        <div className="w-5 h-5 rounded bg-purple-900/60 text-purple-300 flex items-center justify-center flex-shrink-0 mt-0.5">
                                            <Bot className="w-3 h-3" />
                                        </div>
                                    )}
                                    <div
                                        className={cn(
                                            'p-2 rounded-lg leading-relaxed max-w-[85%] text-[11px]',
                                            msg.sender === 'user'
                                                ? 'bg-purple-600 text-white rounded-br-none'
                                                : 'bg-purple-950/60 border border-purple-500/20 text-purple-100 rounded-bl-none'
                                        )}
                                    >
                                        {msg.text}
                                    </div>
                                    {msg.sender === 'user' && (
                                        <div className="w-5 h-5 rounded bg-surface-700 text-text-muted flex items-center justify-center flex-shrink-0 mt-0.5">
                                            <UserIcon className="w-3 h-3" />
                                        </div>
                                    )}
                                </div>
                            ))}

                            {sendingMentor && (
                                <div className="flex items-center gap-2 text-[11px] text-purple-300 italic">
                                    <Loader2 className="w-3 h-3 animate-spin text-purple-400" />
                                    <span>Mentor is analyzing course material...</span>
                                </div>
                            )}
                        </div>

                        {/* Chatbot Form Input */}
                        <form onSubmit={handleSendMentorPrompt} className="relative flex items-center pt-1">
                            <input
                                type="text"
                                value={mentorPrompt}
                                onChange={(e) => setMentorPrompt(e.target.value)}
                                placeholder="Ask about Indian markets..."
                                className="w-full bg-surface-950 border border-purple-500/30 focus:border-purple-500 rounded-lg pl-3 pr-9 py-2 text-xs text-heading placeholder:text-text-muted outline-none transition-colors shadow-inner"
                            />
                            <button
                                type="submit"
                                disabled={sendingMentor || !mentorPrompt.trim()}
                                className="absolute right-1.5 p-1.5 rounded-md bg-purple-600 hover:bg-purple-500 text-white disabled:opacity-50 transition-colors"
                            >
                                <Send className="w-3.5 h-3.5" />
                            </button>
                        </form>

                        <p className="text-[10px] text-purple-300/70 leading-tight italic text-center">
                            Grounded in your course material. The mentor explains history — it never forecasts a price.
                        </p>
                    </div>

                </div>

            </div>

        </div>
    );
}
