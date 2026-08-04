// TraderLearnPage.jsx — Non-Institutional Knowledge & Curiosity Hub for Traders
import { useState } from 'react';
import usePageMeta from '../hooks/usePageMeta';
import {
    Lightbulb, ShieldCheck, Flame, Award, BookOpen,
    TrendingUp, BarChart3, HelpCircle, ChevronRight, Zap, Target, Search
} from 'lucide-react';
import { cn } from '../utils/cn';

const CONCEPT_CARDS = [
    {
        id: 'risk-management',
        title: 'Risk Management & Position Sizing',
        category: 'Risk',
        icon: ShieldCheck,
        badge: 'Core Skill',
        summary: 'Never risk more than 1-2% of total virtual capital per trade. Calculate exact lot size based on stop loss distance.',
        details: [
            'Position Size Formula: (Account Risk Amount) / (Entry Price - Stop Loss Price)',
            'Always set a predefined Stop Loss BEFORE executing a trade.',
            'Maintain a minimum 1:2 Risk-to-Reward ratio across all positions.',
        ]
    },
    {
        id: 'price-action',
        title: 'Price Action & Pattern Mechanics',
        category: 'Analysis',
        icon: TrendingUp,
        badge: 'Tactical',
        summary: 'Understand buyer/seller momentum from raw candlestick structures, pin bars, and breakout confirmations.',
        details: [
            'Hammer / Bullish Pinbar: Signals strong rejection of lower prices near support.',
            'Engulfing Candles: Confirms strong institutional volume displacement.',
            'Breakout Validation: Wait for candle close above resistance before entering.',
        ]
    },
    {
        id: 'options-greeks',
        title: 'Options Greeks & Volatility Basics',
        category: 'Derivatives',
        icon: BarChart3,
        badge: 'Advanced',
        summary: 'Greeks measure option price sensitivity to stock movement, time decay, and implied volatility changes.',
        details: [
            'Delta: Rate of change of option price per ₹1 move in the underlying stock.',
            'Theta: Daily time decay cost of holding long option contracts.',
            'Vega: Sensitivity to changes in Implied Volatility (IV).',
        ]
    },
    {
        id: 'order-execution',
        title: 'Order Types & Bracket Orders',
        category: 'Platform',
        icon: Zap,
        badge: 'Platform',
        summary: 'Master Market vs Limit orders, and automate protection using 3-leg Bracket Orders (Entry + Target + Stop Loss).',
        details: [
            'Limit Orders ensure entry at your desired price or better.',
            'Bracket Orders lock in profit targets while strictly capping loss.',
            'Trailing Stop Loss automatically trails rising profits.',
        ]
    }
];

const TRADER_BADGES = [
    { id: 1, title: 'First Trade Executed', desc: 'Executed your first paper trade on live markets', icon: Target, unlocked: true },
    { id: 2, title: '5-Day Trading Streak', desc: 'Active trading journal entries 5 days in a row', icon: Flame, unlocked: true },
    { id: 3, title: 'Risk Guard', desc: 'Executed a Bracket Order with Target & Stop Loss', icon: ShieldCheck, unlocked: true },
    { id: 4, title: 'Portfolio Builder', desc: 'Maintained 3 distinct stock holdings simultaneously', icon: Award, unlocked: false },
];

export default function TraderLearnPage() {
    usePageMeta('Trader Curiosity Hub | AlphaSync', 'Non-institutional trading concept cards, risk management docs, and activity badges.');

    const [searchQuery, setSearchQuery] = useState('');
    const [selectedCategory, setSelectedCategory] = useState('All');
    const [activeConcept, setActiveConcept] = useState(null);

    const categories = ['All', 'Risk', 'Analysis', 'Derivatives', 'Platform'];

    const filteredCards = CONCEPT_CARDS.filter((card) => {
        const matchesCategory = selectedCategory === 'All' || card.category === selectedCategory;
        const matchesSearch = card.title.toLowerCase().includes(searchQuery.toLowerCase()) || card.summary.toLowerCase().includes(searchQuery.toLowerCase());
        return matchesCategory && matchesSearch;
    });

    return (
        <div className="min-h-screen p-4 sm:p-6 lg:p-8 space-y-6 max-w-7xl mx-auto">
            {/* Header Banner */}
            <div className="relative overflow-hidden rounded-2xl border border-indigo-500/20 bg-gradient-to-r from-slate-950 via-indigo-950/40 to-slate-950 p-6 sm:p-8 shadow-2xl">
                <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
                    <div className="space-y-2">
                        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-extrabold uppercase tracking-wider bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                            <Lightbulb className="w-3.5 h-3.5 text-amber-400" /> Individual Trader Curiosity Hub
                        </div>
                        <h1 className="text-2xl sm:text-3xl font-display font-bold text-white tracking-tight">
                            Trader Knowledge &amp; Strategy Guides
                        </h1>
                        <p className="text-xs sm:text-sm text-slate-300 max-w-2xl leading-relaxed">
                            Master market mechanics, risk management, and order execution without institutional course clutter. Build trading discipline and earn activity badges.
                        </p>
                    </div>

                    {/* Trader Activity XP Card */}
                    <div className="flex items-center gap-4 bg-white/5 border border-white/10 rounded-xl p-4 flex-shrink-0">
                        <div className="w-12 h-12 rounded-xl bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-amber-400 font-bold text-lg">
                            <Flame className="w-6 h-6 animate-pulse" />
                        </div>
                        <div>
                            <div className="text-xs text-slate-400 font-semibold uppercase tracking-wider">Trading Activity</div>
                            <div className="text-xl font-bold text-white">1,250 <span className="text-amber-400 text-xs font-mono">XP</span></div>
                            <div className="text-[10px] text-emerald-400 font-semibold">🔥 5-Day Active Streak</div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Filter & Search Bar */}
            <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
                <div className="flex items-center gap-2 overflow-x-auto w-full sm:w-auto pb-1 sm:pb-0">
                    {categories.map((cat) => (
                        <button
                            key={cat}
                            onClick={() => setSelectedCategory(cat)}
                            className={cn(
                                "px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all cursor-pointer whitespace-nowrap",
                                selectedCategory === cat
                                    ? "bg-indigo-500/25 text-indigo-300 border border-indigo-500/40 shadow-sm"
                                    : "bg-surface-800/40 text-slate-400 hover:text-white border border-edge/10"
                            )}
                        >
                            {cat}
                        </button>
                    ))}
                </div>

                <div className="relative w-full sm:w-64">
                    <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                        type="text"
                        placeholder="Search guides & concepts..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="w-full pl-9 pr-3 py-1.5 text-xs bg-surface-800/40 border border-edge/10 rounded-xl text-white placeholder-slate-400 focus:outline-none focus:border-indigo-500/50"
                    />
                </div>
            </div>

            {/* Concept Cards Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {filteredCards.map((card) => {
                    const Icon = card.icon;
                    return (
                        <div
                            key={card.id}
                            className="rounded-xl border border-white/10 bg-slate-900/60 p-5 space-y-4 hover:border-indigo-500/30 transition-all flex flex-col justify-between"
                        >
                            <div className="space-y-3">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2.5">
                                        <div className="w-9 h-9 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center text-indigo-300">
                                            <Icon className="w-5 h-5" />
                                        </div>
                                        <div>
                                            <h3 className="text-sm font-bold text-white">{card.title}</h3>
                                            <span className="text-[10px] font-mono text-indigo-400 uppercase">{card.category}</span>
                                        </div>
                                    </div>
                                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-300 border border-amber-500/20">
                                        {card.badge}
                                    </span>
                                </div>
                                <p className="text-xs text-slate-300 leading-relaxed">{card.summary}</p>
                            </div>

                            <div className="space-y-2 border-t border-white/5 pt-3">
                                <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1">
                                    <BookOpen className="w-3.5 h-3.5 text-indigo-400" /> Key Insights
                                </span>
                                <ul className="space-y-1 text-xs text-slate-300">
                                    {card.details.map((item, idx) => (
                                        <li key={idx} className="flex items-start gap-2">
                                            <ChevronRight className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0 mt-0.5" />
                                            <span>{item}</span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Trading Milestone Badges Section */}
            <div className="rounded-xl border border-white/10 bg-slate-900/60 p-5 space-y-4">
                <div className="flex items-center justify-between">
                    <div>
                        <h2 className="text-base font-bold text-white flex items-center gap-2">
                            <Award className="w-5 h-5 text-amber-400" /> Trading Activity Badges
                        </h2>
                        <p className="text-xs text-slate-400 mt-0.5">Earn milestone badges by executing paper trades and maintaining discipline</p>
                    </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                    {TRADER_BADGES.map((b) => {
                        const Icon = b.icon;
                        return (
                            <div
                                key={b.id}
                                className={cn(
                                    "p-3.5 rounded-xl border flex items-center gap-3 transition-all",
                                    b.unlocked
                                        ? "bg-amber-500/10 border-amber-500/30 text-amber-200"
                                        : "bg-white/[0.02] border-white/5 text-slate-500 opacity-60"
                                )}
                            >
                                <div className={cn(
                                    "w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0",
                                    b.unlocked ? "bg-amber-500/20 text-amber-300 border border-amber-500/30" : "bg-white/5 text-slate-600"
                                )}>
                                    <Icon className="w-5 h-5" />
                                </div>
                                <div className="min-w-0">
                                    <div className="text-xs font-bold truncate">{b.title}</div>
                                    <div className="text-[10px] text-slate-400 truncate mt-0.5">{b.desc}</div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
