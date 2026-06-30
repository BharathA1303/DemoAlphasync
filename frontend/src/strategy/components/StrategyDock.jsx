import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { cn } from '../../utils/cn';
import { useZeroLossStore } from '../../stores/useZeroLossStore';
import { useTheme } from '../../context/ThemeContext';
import { useStrategyStore } from '../../stores/useStrategyStore';
import { getAvailableStrategies, runEngine } from '../engine';

// ── Colour tokens ────────────────────────────────────────────────────────────
const SIG = {
    Bullish: {
        pill: 'bg-emerald-500/12 text-emerald-600 ring-1 ring-emerald-500/20',
        dot: 'bg-emerald-400',
        bar: 'bg-gradient-to-r from-emerald-500 to-emerald-400',
    },
    Bearish: {
        pill: 'bg-red-500/12 text-red-500 ring-1 ring-red-500/20',
        dot: 'bg-red-400',
        bar: 'bg-gradient-to-r from-red-500 to-red-400',
    },
    Neutral: {
        pill: 'bg-primary-500/10 text-primary-600 ring-1 ring-primary-500/20',
        dot: 'bg-primary-500',
        bar: 'bg-gradient-to-r from-primary-500 to-primary-700',
    },
};

const BIAS = {
    BULLISH: {
        border: 'border-emerald-500/20',
        accent: 'bg-emerald-500',
        text: 'text-emerald-600',
        bg: 'bg-emerald-500/[0.06]',
        label: 'BULLISH',
        icon: (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
                <polyline points="16 7 22 7 22 13" />
            </svg>
        ),
    },
    BEARISH: {
        border: 'border-red-500/20',
        accent: 'bg-red-500',
        text: 'text-red-500',
        bg: 'bg-red-500/[0.06]',
        label: 'BEARISH',
        icon: (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                <polyline points="22 17 13.5 8.5 8.5 13.5 2 7" />
                <polyline points="16 17 22 17 22 11" />
            </svg>
        ),
    },
    NEUTRAL: {
        border: 'border-[#00bcd4]/15',
        accent: 'bg-[#00bcd4]',
        text: 'text-[#00bcd4]',
        bg: 'bg-[#00bcd4]/[0.04]',
        label: 'NEUTRAL',
        icon: (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
        ),
    },
};

const LS_POS_KEY = 'alphasync_strategy_dock_pos';
const loadPos = () => { try { const r = localStorage.getItem(LS_POS_KEY); return r ? JSON.parse(r) : null; } catch { return null; } };
const savePos = (p) => { try { localStorage.setItem(LS_POS_KEY, JSON.stringify(p)); } catch { } };

// ── Signal Badge ─────────────────────────────────────────────────────────────
function SignalBadge({ signal }) {
    const s = SIG[signal] || SIG.Neutral;
    return (
        <span className={cn('inline-flex items-center gap-1.5 text-[10px] font-semibold px-2 py-0.5 rounded-full tracking-wide', s.pill)}>
            <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', s.dot)} />
            {signal}
        </span>
    );
}

// ── Strategy Row ─────────────────────────────────────────────────────────────
function StrategyRow({ meta, result, enabled, onToggle }) {
    const s = SIG[result?.signal] || SIG.Neutral;
    const conf = result?.confidence ?? 0;

    return (
        <div className={cn(
            'rounded-xl border transition-all duration-200',
            enabled
                ? 'border-edge/10 bg-surface-800/60 hover:bg-surface-800 hover:border-edge/20'
                : 'border-edge/5 bg-transparent opacity-40',
        )}>
            {/* Row header */}
            <div className="flex items-center gap-3 px-3.5 py-2.5">
                {/* Toggle */}
                <button
                    onClick={onToggle}
                    className={cn(
                        'relative w-9 h-5 rounded-full flex-shrink-0 transition-all duration-250 focus:outline-none',
                        enabled
                            ? 'bg-blue-500 shadow-lg shadow-blue-500/30'
                            : 'bg-gray-600',
                    )}
                    aria-checked={enabled}
                    role="switch"
                >
                    <span className={cn(
                        'absolute top-[3px] w-[14px] h-[14px] rounded-full bg-white shadow-md transition-all duration-250',
                        enabled ? 'left-[19px]' : 'left-[3px]',
                    )} />
                </button>

                {/* Name */}
                <span className={cn(
                    'flex-1 text-[12px] font-semibold leading-tight truncate',
                    enabled ? 'text-heading' : 'text-gray-500',
                )}>
                    {meta.name}
                </span>

                {/* Weight pill */}
                <span className="text-[10px] text-gray-400 font-mono bg-surface-800 px-1.5 py-0.5 rounded-md flex-shrink-0">
                    {Math.round((meta.weight || 0.1) * 100)}%
                </span>

                {/* Signal badge */}
                {enabled && result && (
                    <div className="flex-shrink-0">
                        <SignalBadge signal={result.signal} />
                    </div>
                )}
            </div>

            {/* Confidence bar + detail */}
            {enabled && result && (
                <div className="px-3.5 pb-3 space-y-1.5">
                    {/* Bar track */}
                    <div className="flex items-center gap-2">
                        <div className="flex-1 h-[3px] rounded-full bg-surface-700 overflow-hidden">
                            <div
                                className={cn('h-full rounded-full transition-all duration-700 ease-out', s.bar)}
                                style={{ width: `${Math.max(conf, 4)}%` }}
                            />
                        </div>
                        <span className={cn('text-[10px] font-mono font-semibold tabular-nums flex-shrink-0', s.dot.replace('bg-', 'text-').replace('-400', '-400'))}>
                            {conf}%
                        </span>
                    </div>
                    {/* Detail text */}
                    {result.detail && (
                        <p className="text-[10px] text-gray-500 leading-relaxed pl-12 truncate">
                            {result.detail}
                        </p>
                    )}
                </div>
            )}
        </div>
    );
}

// ── Circular Score Ring ───────────────────────────────────────────────────────
function ScoreRing({ score, confidence, bias }) {
    const b = BIAS[bias] || BIAS.NEUTRAL;
    const radius = 28;
    const circ = 2 * Math.PI * radius;
    const pct = Math.min(Math.abs(confidence) / 100, 1);
    const offset = circ * (1 - pct);

    return (
        <div className="relative flex-shrink-0">
            <svg width="72" height="72" className="-rotate-90">
                <circle cx="36" cy="36" r={radius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="5" />
                <circle
                    cx="36" cy="36" r={radius}
                    fill="none"
                    stroke={bias === 'BULLISH' ? '#10b981' : bias === 'BEARISH' ? '#ef4444' : '#f59e0b'}
                    strokeWidth="5"
                    strokeLinecap="round"
                    strokeDasharray={circ}
                    strokeDashoffset={offset}
                    style={{ transition: 'stroke-dashoffset 0.8s cubic-bezier(0.4,0,0.2,1)' }}
                />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
                <span className={cn('text-base font-black tabular-nums leading-none', b.text)}>
                    {confidence}%
                </span>
                <span className="text-[8px] text-gray-500 font-semibold tracking-wide mt-0.5">CONF</span>
            </div>
        </div>
    );
}

// ══ STRATEGY DOCK ════════════════════════════════════════════════════════════
export default function StrategyDock({ candles = [], isOpen = false, onClose }) {
    const { theme } = useTheme();
    const isDark = theme === 'dark';
    const selectedSymbol = candles?.length > 0 && candles[candles.length - 1]?.symbol
        ? candles[candles.length - 1].symbol
        : null;

    const zeroLossForSymbol = useZeroLossStore((s) =>
        selectedSymbol ? s.confidence[selectedSymbol] || null : null
    );

    const allStrategies = useMemo(() => getAvailableStrategies(), []);

    // Use global strategy store for enabled state
    const storeEnabledMap = useStrategyStore((s) => s.enabledMap);
    const toggleStrategy = useStrategyStore((s) => s.toggleStrategy);
    const initDefaults = useStrategyStore((s) => s.initDefaults);
    const setEngineOutput = useStrategyStore((s) => s.setEngineOutput);

    // Initialize defaults on first mount if store is empty
    useEffect(() => {
        initDefaults(allStrategies);
    }, [allStrategies, initDefaults]);

    // Derive enabled map — use store, fallback to all enabled
    const enabledMap = useMemo(() => {
        if (Object.keys(storeEnabledMap).length > 0) return storeEnabledMap;
        const d = {};
        allStrategies.forEach((s) => { d[s.id] = true; });
        return d;
    }, [storeEnabledMap, allStrategies]);

    const enabledIds = useMemo(
        () => allStrategies.filter((s) => enabledMap[s.id]).map((s) => s.id),
        [allStrategies, enabledMap],
    );

    const engine = useMemo(() => runEngine(candles, enabledIds), [candles, enabledIds]);

    // Write engine output to the global store so the chart badge can read it
    useEffect(() => {
        if (engine && engine.signals.length > 0) {
            setEngineOutput(engine);
        }
    }, [engine, setEngineOutput]);

    const resultMap = useMemo(() => {
        const m = {};
        engine.signals.forEach((s) => { m[s.id] = s; });
        return m;
    }, [engine]);

    const b = BIAS[engine.overall] || BIAS.NEUTRAL;
    const bulls = engine.signals.filter((s) => s.signal === 'Bullish').length;
    const bears = engine.signals.filter((s) => s.signal === 'Bearish').length;
    const neutrals = engine.signals.length - bulls - bears;
    const total = engine.signals.length || 1;

    // ── Dragging ──────────────────────────────────────────────────────────
    const panelRef = useRef(null);
    const drag = useRef({ active: false, sx: 0, sy: 0, ox: 0, oy: 0 });
    const [pos, setPos] = useState(() => loadPos() || { x: Math.max(280, window.innerWidth - 400), y: 80 });

    const clamp = useCallback((p) => ({
        x: Math.max(0, Math.min(window.innerWidth - 360, p.x)),
        y: Math.max(0, Math.min(window.innerHeight - 120, p.y)),
    }), []);

    const onGrab = useCallback((e) => {
        if (e.target.closest('button') || e.target.closest('input')) return;
        e.preventDefault();
        drag.current = { active: true, sx: e.clientX, sy: e.clientY, ox: pos.x, oy: pos.y };
        const move = (ev) => {
            if (!drag.current.active) return;
            setPos(clamp({
                x: drag.current.ox + (ev.clientX - drag.current.sx),
                y: drag.current.oy + (ev.clientY - drag.current.sy),
            }));
        };
        const up = () => {
            drag.current.active = false;
            document.removeEventListener('mousemove', move);
            document.removeEventListener('mouseup', up);
            setPos((p) => { savePos(p); return p; });
        };
        document.addEventListener('mousemove', move);
        document.addEventListener('mouseup', up);
    }, [pos, clamp]);

    useEffect(() => {
        const h = () => setPos((p) => clamp(p));
        window.addEventListener('resize', h);
        return () => window.removeEventListener('resize', h);
    }, [clamp]);

    if (!isOpen) return null;

    const scoreDisplay = `${engine.weightedScore >= 0 ? '+' : ''}${engine.weightedScore}`;

    return (
        <div
            ref={panelRef}
            className="fixed z-50 flex flex-col rounded-2xl select-none bg-surface-900/95 border border-edge/10 shadow-2xl shadow-black/40"
            style={{
                left: pos.x,
                top: pos.y,
                width: 360,
                backdropFilter: 'blur(24px)',
            }}
        >
            {/* ── HEADER ─────────────────────────────────────────────────── */}
            <div
                onMouseDown={onGrab}
                className="flex items-center justify-between px-4 py-3 cursor-move flex-shrink-0 border-b border-edge/10"
            >
                <div className="flex items-center gap-2.5">
                    <div className="w-6 h-6 rounded-lg flex items-center justify-center bg-blue-500/15 border border-blue-500/25">
                        <svg className="w-3.5 h-3.5 text-[#00bcd4]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            <path d="M12 20V10M18 20V4M6 20v-4" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                    </div>
                    <span className="text-[12px] font-semibold text-heading tracking-wide">Strategy Engine</span>
                </div>

                <div className="flex items-center gap-2">
                    <span className="text-[10px] font-semibold text-blue-400 bg-blue-500/20 px-2 py-0.5 rounded-full font-mono">
                        {enabledIds.length}/{allStrategies.length} active
                    </span>
                    <div className="flex flex-col gap-[3px] opacity-30 px-1 cursor-move">
                        <div className="flex gap-[3px]">{[0, 1, 2].map(i => <div key={i} className="w-[3px] h-[3px] rounded-full bg-gray-500" />)}</div>
                        <div className="flex gap-[3px]">{[0, 1, 2].map(i => <div key={i} className="w-[3px] h-[3px] rounded-full bg-gray-500" />)}</div>
                    </div>
                    <button
                        onClick={onClose}
                        className="w-6 h-6 rounded-md flex items-center justify-center text-gray-500 hover:text-heading hover:bg-surface-800 transition-all duration-150"
                        title="Close"
                    >
                        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                    </button>
                </div>
            </div>

            {/* ── MARKET BIAS CARD ────────────────────────────────────────── */}
            <div className="p-3 flex-shrink-0">
                <div className={cn('rounded-xl p-4 border', b.bg, b.border)}>
                    <div className="flex items-center justify-between mb-4">
                        <div className="space-y-1.5">
                            <p className="text-[9px] text-gray-500 uppercase tracking-[0.12em] font-semibold">Market Bias</p>
                            <div className="flex items-center gap-2">
                                <span className={cn('flex items-center justify-center w-6 h-6 rounded-lg', b.bg, b.border)}>
                                    <span className={b.text}>{b.icon}</span>
                                </span>
                                <span className={cn('text-xl font-semibold tracking-tight', b.text)}>
                                    {b.label}
                                </span>
                            </div>
                            <div className="flex items-center gap-1.5 mt-1">
                                <span className="text-[10px] text-gray-500">Score</span>
                                <span className={cn('text-[11px] font-semibold font-mono tabular-nums', b.text)}>
                                    {scoreDisplay}
                                </span>
                            </div>
                        </div>
                        <ScoreRing
                            score={engine.score ?? 0}
                            confidence={engine.confidence}
                            bias={engine.overall}
                        />
                    </div>

                    {/* Signal distribution bar */}
                    <div className="space-y-1.5">
                        <div className="flex h-2 rounded-full overflow-hidden gap-[2px] bg-surface-700">
                            {bulls > 0 && (
                                <div
                                    className="bg-emerald-500 rounded-full transition-all duration-700 ease-out"
                                    style={{ width: `${(bulls / total) * 100}%` }}
                                />
                            )}
                            {neutrals > 0 && (
                                <div
                                    className="bg-[#00bcd4]/60 transition-all duration-700 ease-out"
                                    style={{ width: `${(neutrals / total) * 100}%` }}
                                />
                            )}
                            {bears > 0 && (
                                <div
                                    className="bg-red-500 rounded-full transition-all duration-700 ease-out"
                                    style={{ width: `${(bears / total) * 100}%` }}
                                />
                            )}
                        </div>
                        <div className="flex items-center gap-4">
                            <div className="flex items-center gap-1.5">
                                <div className="w-2 h-2 rounded-full bg-emerald-500" />
                                <span className="text-[10px] font-semibold text-emerald-400">{bulls} Bull</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                                <div className="w-2 h-2 rounded-full bg-red-500" />
                                <span className="text-[10px] font-semibold text-red-400">{bears} Bear</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                                <div className="w-2 h-2 rounded-full bg-[#00bcd4]/60" />
                                <span className="text-[10px] font-semibold text-gray-400">{neutrals} Flat</span>
                            </div>
                        </div>
                    </div>

                    {/* Alpha AutoTrade backend row */}
                    {zeroLossForSymbol && (
                        <div className="mt-3 pt-3 flex items-center justify-between border-t border-edge/10">
                            <div className="flex items-center gap-1.5">
                                <div className="w-1.5 h-1.5 rounded-full bg-[#00bcd4] animate-pulse" />
                                <span className="text-[10px] font-semibold text-gray-500">Alpha AutoTrade Backend</span>
                            </div>
                            <div className="flex items-center gap-2">
                                <span className={cn(
                                    'text-[10px] font-semibold px-2 py-0.5 rounded-full',
                                    zeroLossForSymbol.direction === 'BULLISH'
                                        ? 'bg-emerald-500/15 text-emerald-600'
                                        : 'bg-red-500/15 text-red-500'
                                )}>
                                    {zeroLossForSymbol.direction}
                                </span>
                                <span className="text-[11px] font-semibold font-mono text-heading">
                                    {Math.round(zeroLossForSymbol.score)}%
                                </span>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* ── SECTION LABEL ───────────────────────────────────────────── */}
            <div className="px-4 pb-2 flex items-center gap-2 flex-shrink-0">
                <span className="text-[9px] font-semibold text-gray-500 uppercase tracking-[0.15em]">Strategies</span>
                <div className="flex-1 h-px bg-edge/10" />
            </div>

            {/* ── STRATEGY ROWS ───────────────────────────────────────────── */}
            <div className="px-3 pb-3 space-y-1.5 overflow-y-auto flex-1"
                style={{
                    maxHeight: 300,
                    scrollbarWidth: 'none',
                    msOverflowStyle: 'none',
                }}>
                {allStrategies.map((meta) => (
                    <StrategyRow
                        key={meta.id}
                        meta={meta}
                        result={resultMap[meta.id]}
                        enabled={!!enabledMap[meta.id]}
                        onToggle={() => toggleStrategy(meta.id)}
                    />
                ))}
            </div>

            {/* ── FOOTER ─────────────────────────────────────────────────── */}
            <div className="px-4 py-2.5 flex-shrink-0 border-t border-edge/10">
                <p className="text-[9px] text-gray-500 text-center leading-relaxed tracking-wide">
                    Weighted scoring · &gt;+0.3 Bullish · &lt;−0.3 Bearish
                </p>
            </div>
        </div>
    );
}
