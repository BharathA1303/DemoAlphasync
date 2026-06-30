import { useState, useEffect, useCallback, useRef } from 'react';
import api from '../services/api';
import toast from 'react-hot-toast';
import { cn } from '../utils/cn';
import { pnlColorClass, cleanSymbol } from '../utils/formatters';
import {
    Zap, Play, Pause, Plus, X, Pencil, Trash2, Clock,
    MoreVertical, TrendingUp, TrendingDown, BarChart2,
    Activity, Target, Shield, ChevronRight, Upload, Wrench,
} from 'lucide-react';

// ── Strategy type definitions ─────────────────────────────────────────────────
const STRATEGY_TYPES = [
    { value: 'SMA_CROSSOVER', label: 'SMA Crossover', desc: 'Golden/death cross + RSI zone + MACD momentum + volume confirmation' },
    { value: 'RSI', label: 'RSI Strategy', desc: 'Oversold/overbought bounce + EMA trend filter + MACD turning + volume surge' },
    { value: 'MACD', label: 'MACD Signal', desc: 'Signal crossover + histogram momentum + RSI zone + zero-line strength' },
    { value: 'BOLLINGER', label: 'Bollinger Bands', desc: 'Band touch + RSI divergence + trend filter (no falling knives) + volume spike' },
    { value: 'EMA_CROSSOVER', label: 'EMA Crossover', desc: 'Fast/slow EMA cross + MACD alignment + RSI confirmation + volume surge' },
    { value: 'VWAP_BOUNCE', label: 'VWAP Bounce', desc: 'VWAP support/resistance bounce + RSI + MACD + volume — best for intraday' },
    { value: 'SUPERTREND', label: 'Supertrend Pullback', desc: 'ATR channel reclaim/reject + EMA trend filter + momentum confirmation' },
    { value: 'ATR_BREAKOUT', label: 'ATR Breakout', desc: 'Breakout beyond ATR-adjusted range with volume expansion confirmation' },
    { value: 'STOCHASTIC_REVERSION', label: 'Stochastic Reversion', desc: 'K/D turn from oversold or overbought zones with momentum filter' },
];

const STRATEGY_PARAMS = {
    SMA_CROSSOVER: [
        { key: 'short_period', label: 'Short SMA', type: 'number', default: 10, min: 2, max: 100, hint: 'Fast moving average period' },
        { key: 'long_period', label: 'Long SMA', type: 'number', default: 20, min: 5, max: 200, hint: 'Slow moving average period' },
    ],
    RSI: [
        { key: 'period', label: 'RSI Period', type: 'number', default: 14, min: 2, max: 50, hint: 'Lookback period for RSI' },
        { key: 'oversold', label: 'Oversold', type: 'number', default: 30, min: 10, max: 45, hint: 'Buy below this RSI level' },
        { key: 'overbought', label: 'Overbought', type: 'number', default: 70, min: 55, max: 90, hint: 'Sell above this RSI level' },
    ],
    MACD: [
        { key: 'fast_period', label: 'Fast EMA', type: 'number', default: 12, min: 2, max: 50, hint: 'Fast EMA period' },
        { key: 'slow_period', label: 'Slow EMA', type: 'number', default: 26, min: 10, max: 100, hint: 'Slow EMA period' },
        { key: 'signal_period', label: 'Signal', type: 'number', default: 9, min: 2, max: 30, hint: 'Signal line smoothing' },
    ],
    BOLLINGER: [
        { key: 'period', label: 'BB Period', type: 'number', default: 20, min: 5, max: 50, hint: 'Moving average period' },
        { key: 'std_dev', label: 'Std Dev', type: 'number', step: 0.1, default: 2.0, min: 0.5, max: 4.0, hint: 'Band width multiplier' },
    ],
    EMA_CROSSOVER: [
        { key: 'fast_period', label: 'Fast EMA', type: 'number', default: 9, min: 2, max: 50, hint: 'Fast EMA period' },
        { key: 'slow_period', label: 'Slow EMA', type: 'number', default: 21, min: 5, max: 100, hint: 'Slow EMA period' },
    ],
    VWAP_BOUNCE: [
        { key: 'bounce_threshold', label: 'Bounce %', type: 'number', step: 0.1, default: 0.2, min: 0.1, max: 1.0, hint: 'Max distance from VWAP (%)' },
    ],
    SUPERTREND: [
        { key: 'atr_period', label: 'ATR Period', type: 'number', default: 10, min: 5, max: 50, hint: 'ATR lookback' },
        { key: 'multiplier', label: 'Multiplier', type: 'number', step: 0.1, default: 3.0, min: 1.0, max: 6.0, hint: 'ATR channel width' },
    ],
    ATR_BREAKOUT: [
        { key: 'period', label: 'ATR Period', type: 'number', default: 14, min: 5, max: 50, hint: 'ATR lookback period' },
        { key: 'breakout_multiplier', label: 'Breakout xATR', type: 'number', step: 0.1, default: 1.2, min: 0.5, max: 3.0, hint: 'Distance to confirm breakout' },
    ],
    STOCHASTIC_REVERSION: [
        { key: 'k_period', label: 'K Period', type: 'number', default: 14, min: 5, max: 30, hint: 'Fast stochastic lookback' },
        { key: 'd_period', label: 'D Smoothing', type: 'number', default: 3, min: 2, max: 10, hint: 'Signal smoothing period' },
        { key: 'oversold', label: 'Oversold', type: 'number', default: 20, min: 5, max: 40, hint: 'Buy when K exits this zone' },
        { key: 'overbought', label: 'Overbought', type: 'number', default: 80, min: 60, max: 95, hint: 'Sell when K exits this zone' },
    ],
};

const TIMEFRAME_MAP = {
    SMA_CROSSOVER: 'Swing', MACD: 'Swing',
    RSI: 'Intraday', EMA_CROSSOVER: 'Intraday', VWAP_BOUNCE: 'Intraday',
    ATR_BREAKOUT: 'Intraday', STOCHASTIC_REVERSION: 'Intraday',
    BOLLINGER: 'Positional', SUPERTREND: 'Positional',
};

const CATEGORY_MAP = {
    SMA_CROSSOVER: 'Momentum', EMA_CROSSOVER: 'Momentum',
    RSI: 'Scalping', STOCHASTIC_REVERSION: 'Mean Reversion',
    MACD: 'Swing', ATR_BREAKOUT: 'Breakout',
    BOLLINGER: 'Positional', SUPERTREND: 'Positional',
    VWAP_BOUNCE: 'Intraday',
};

const DONUT_COLORS = {
    Intraday: '#f59e0b',
    Swing: '#3b82f6',
    Positional: '#8b5cf6',
    Options: '#06b6d4',
};

const TABS = [
    { id: 'overview', label: 'Overview' },
    { id: 'my-strategies', label: 'My Strategies' },
    { id: 'backtesting', label: 'Backtesting' },
    { id: 'marketplace', label: 'Marketplace' },
    { id: 'logs', label: 'Logs & Alerts' },
    { id: 'performance', label: 'Performance' },
    { id: 'risk', label: 'Risk Management' },
];

const CHART_RANGES = ['1D', '1W', '1M', '3M', '1Y', 'All'];

// ── Utilities ─────────────────────────────────────────────────────────────────
function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }

function parseApiError(err, fallback = 'Request failed') {
    const detail = err?.response?.data?.detail;
    if (Array.isArray(detail)) return detail.map(d => d?.msg).filter(Boolean).join(', ') || fallback;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (typeof err?.message === 'string' && err.message.trim()) return err.message;
    return fallback;
}

function parseNumericInput(raw, fallback, min, max, decimals = null) {
    const parsed = Number(raw);
    const safe = Number.isFinite(parsed) ? parsed : fallback;
    const bounded = clamp(safe, min, max);
    if (decimals == null) return Math.round(bounded);
    return Number(bounded.toFixed(decimals));
}

function sanitizeParams(type, params = {}) {
    const fields = STRATEGY_PARAMS[type] || [];
    const sanitized = { quantity: parseNumericInput(params.quantity, 1, 1, 1000, null) };
    fields.forEach(field => {
        const decimals = field.step ? 4 : null;
        sanitized[field.key] = parseNumericInput(params[field.key], field.default, field.min, field.max, decimals);
    });
    if (type === 'SMA_CROSSOVER' && sanitized.short_period >= sanitized.long_period)
        sanitized.short_period = Math.max(2, sanitized.long_period - 1);
    if (type === 'EMA_CROSSOVER' && sanitized.fast_period >= sanitized.slow_period)
        sanitized.fast_period = Math.max(2, sanitized.slow_period - 1);
    if (type === 'MACD' && sanitized.fast_period >= sanitized.slow_period)
        sanitized.fast_period = Math.max(2, sanitized.slow_period - 1);
    if ((type === 'RSI' || type === 'STOCHASTIC_REVERSION') && sanitized.oversold >= sanitized.overbought)
        sanitized.oversold = Math.max(5, sanitized.overbought - 1);
    return sanitized;
}

function getDefaultParams(type) {
    const fields = STRATEGY_PARAMS[type] || [];
    const p = { quantity: 1 };
    fields.forEach(f => { p[f.key] = f.default; });
    return p;
}

function getInitialForm() {
    return {
        name: '', strategy_type: 'SMA_CROSSOVER', symbol: 'RELIANCE',
        description: '', max_position_size: 100, stop_loss_percent: 2,
        take_profit_percent: 5, parameters: getDefaultParams('SMA_CROSSOVER'),
    };
}

function buildCreatePayload(form) {
    const strategyType = String(form.strategy_type || 'SMA_CROSSOVER').toUpperCase();
    return {
        name: String(form.name || '').trim(),
        strategy_type: strategyType,
        symbol: String(form.symbol || '').trim().toUpperCase(),
        description: String(form.description || '').trim(),
        max_position_size: parseNumericInput(form.max_position_size, 100, 1, 100000, null),
        stop_loss_percent: parseNumericInput(form.stop_loss_percent, 2, 0.1, 50, 2),
        take_profit_percent: parseNumericInput(form.take_profit_percent, 5, 0.1, 200, 2),
        parameters: sanitizeParams(strategyType, form.parameters || {}),
    };
}

function buildUpdatePayload(strategyType, form) {
    return {
        name: String(form.name || '').trim(),
        description: String(form.description || '').trim(),
        max_position_size: parseNumericInput(form.max_position_size, 100, 1, 100000, null),
        stop_loss_percent: parseNumericInput(form.stop_loss_percent, 2, 0.1, 50, 2),
        take_profit_percent: parseNumericInput(form.take_profit_percent, 5, 0.1, 200, 2),
        parameters: sanitizeParams(strategyType, form.parameters || {}),
    };
}

function fmtPnl(v) {
    const n = Number(v) || 0;
    return `${n >= 0 ? '+' : ''}₹${Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtCompact(v) {
    const n = Number(v) || 0;
    const abs = Math.abs(n);
    const sign = n < 0 ? '-' : '';
    if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toFixed(2)}Cr`;
    if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toFixed(2)}L`;
    if (abs >= 1e3) return `${sign}₹${(abs / 1e3).toFixed(1)}K`;
    return `${sign}₹${abs.toFixed(2)}`;
}

// ── SVG Line Chart ────────────────────────────────────────────────────────────
function PnLChart({ labels = [], values = [] }) {
    const hasData = values.length > 1;
    if (!hasData) {
        return (
            <div className="flex flex-col items-center justify-center h-48 gap-2">
                <BarChart2 className="w-10 h-10 text-gray-700" />
                <p className="text-sm text-gray-500">No performance data yet</p>
                <p className="text-xs text-gray-600">Activate strategies to track P&L</p>
            </div>
        );
    }

    const W = 520, H = 180;
    const pad = { t: 12, r: 16, b: 28, l: 56 };
    const iW = W - pad.l - pad.r;
    const iH = H - pad.t - pad.b;

    const maxV = Math.max(...values, 0);
    const minV = Math.min(...values, 0);
    const range = maxV - minV || 1;

    const x = (i) => pad.l + (i / Math.max(values.length - 1, 1)) * iW;
    const y = (v) => pad.t + iH - ((v - minV) / range) * iH;

    const pathD = values.map((v, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
    const areaD = `${pathD} L ${x(values.length - 1).toFixed(1)} ${(pad.t + iH).toFixed(1)} L ${x(0).toFixed(1)} ${(pad.t + iH).toFixed(1)} Z`;

    const lastVal = values[values.length - 1];
    const color = lastVal >= 0 ? '#059669' : '#ef4444';
    const gradId = lastVal >= 0 ? 'pnlGradG' : 'pnlGradR';

    const yTicks = [minV, (minV + maxV) / 2, maxV];
    const xShow = [0, Math.floor((labels.length - 1) / 2), labels.length - 1].filter(
        (v, i, a) => a.indexOf(v) === i && labels[v]
    );

    return (
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full" style={{ minHeight: 160 }}>
            <defs>
                <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor={color} stopOpacity="0.18" />
                    <stop offset="100%" stopColor={color} stopOpacity="0.02" />
                </linearGradient>
            </defs>
            {yTicks.map((tick, i) => (
                <line key={i} x1={pad.l} x2={W - pad.r} y1={y(tick)} y2={y(tick)}
                    stroke="rgba(255,255,255,0.04)" strokeWidth="1" />
            ))}
            <path d={areaD} fill={`url(#${gradId})`} />
            <path d={pathD} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
            <circle cx={x(values.length - 1)} cy={y(lastVal)} r="3.5" fill={color} />
            {yTicks.map((tick, i) => (
                <text key={i} x={pad.l - 6} y={y(tick) + 4} textAnchor="end"
                    fontSize="9" fill="rgba(156,163,175,0.7)">
                    {fmtCompact(tick)}
                </text>
            ))}
            {xShow.map((i) => (
                <text key={i} x={x(i)} y={H - 5} textAnchor="middle"
                    fontSize="9" fill="rgba(156,163,175,0.7)">
                    {labels[i]}
                </text>
            ))}
        </svg>
    );
}

// ── SVG Donut Chart ───────────────────────────────────────────────────────────
function DonutChart({ segments, total }) {
    if (!segments || segments.length === 0) {
        return (
            <div className="flex items-center justify-center w-32 h-32 rounded-full border-4 border-surface-700/50">
                <span className="text-xs text-gray-600">No data</span>
            </div>
        );
    }
    const r = 44;
    const cx = 60, cy = 60;
    const circ = 2 * Math.PI * r;
    let cumulativePct = 0;

    return (
        <svg viewBox="0 0 120 120" className="w-32 h-32 flex-shrink-0">
            {segments.map((seg, i) => {
                const dashLen = (seg.pct / 100) * circ;
                const dashOffset = circ / 4 - (cumulativePct / 100) * circ;
                cumulativePct += seg.pct;
                return (
                    <circle key={i} cx={cx} cy={cy} r={r}
                        fill="none" stroke={seg.color} strokeWidth="16"
                        strokeDasharray={`${dashLen} ${circ - dashLen}`}
                        strokeDashoffset={dashOffset} />
                );
            })}
            <text x={cx} y={cy - 5} textAnchor="middle"
                fontSize="16" fontWeight="700" fill="white">{total}</text>
            <text x={cx} y={cy + 10} textAnchor="middle"
                fontSize="8" fill="rgba(156,163,175,0.8)">Total</text>
        </svg>
    );
}

// ── Stat Card ─────────────────────────────────────────────────────────────────
function StatCard({ icon: Icon, iconBg, label, value, sub, subColor, trend }) {
    return (
        <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-4 flex items-start gap-3">
            <div className={cn('w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0', iconBg)}>
                <Icon className="w-5 h-5" />
            </div>
            <div className="min-w-0 flex-1">
                <p className="text-[11px] text-gray-500 font-medium truncate">{label}</p>
                <p className="text-lg font-display font-bold text-heading leading-tight mt-0.5 truncate">{value}</p>
                {sub && (
                    <p className={cn('text-[11px] mt-0.5 font-medium', subColor || 'text-gray-500')}>{sub}</p>
                )}
            </div>
        </div>
    );
}

// ── Status Badge ──────────────────────────────────────────────────────────────
function StatusBadge({ isActive }) {
    return (
        <span className={cn(
            'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide',
            isActive
                ? 'bg-emerald-500/10 text-emerald-400'
                : 'bg-gray-500/10 text-gray-400'
        )}>
            <span className={cn('w-1.5 h-1.5 rounded-full', isActive ? 'bg-emerald-400 animate-pulse' : 'bg-gray-500')} />
            {isActive ? 'Running' : 'Paused'}
        </span>
    );
}

// ── Strategy Table Row ────────────────────────────────────────────────────────
function StrategyRow({ s, onToggle, onEdit, onDelete, onViewLogs, menuOpen, onMenuOpen }) {
    const tMeta = STRATEGY_TYPES.find(t => t.value === s.strategy_type) || {};
    const timeframe = TIMEFRAME_MAP[s.strategy_type] || 'Intraday';
    const todayPnl = Number(s.today_pnl) || 0;
    const totalPnl = Number(s.total_pnl) || 0;
    const sharpe = Number(s.sharpe_ratio) || 0;
    const ref = useRef(null);

    useEffect(() => {
        if (!menuOpen) return;
        function handler(e) {
            if (ref.current && !ref.current.contains(e.target)) onMenuOpen(null);
        }
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [menuOpen, onMenuOpen]);

    return (
        <tr className="border-b border-edge/[0.04] hover:bg-surface-800/30 transition-colors group">
            <td className="px-4 py-3">
                <div className="flex items-center gap-2.5">
                    <div className="w-7 h-7 rounded-lg bg-primary-500/10 flex items-center justify-center flex-shrink-0">
                        <Zap className="w-3.5 h-3.5 text-primary-500" />
                    </div>
                    <div>
                        <p className="text-sm font-semibold text-heading leading-tight">{s.name}</p>
                        <p className="text-[10px] text-gray-500">
                            {tMeta.label || s.strategy_type} · {timeframe}
                        </p>
                    </div>
                </div>
            </td>
            <td className="px-4 py-3">
                <StatusBadge isActive={s.is_active} />
            </td>
            <td className="px-4 py-3">
                <p className={cn('text-sm font-price font-semibold tabular-nums', pnlColorClass(totalPnl))}>
                    {fmtPnl(totalPnl)}
                </p>
                {s.total_trades > 0 && (
                    <p className="text-[10px] text-gray-600">{s.total_trades} trades</p>
                )}
            </td>
            <td className="px-4 py-3">
                <p className={cn('text-sm font-price font-semibold tabular-nums', pnlColorClass(todayPnl))}>
                    {todayPnl === 0 ? '₹0.00' : fmtPnl(todayPnl)}
                </p>
                {todayPnl !== 0 && (
                    <p className={cn('text-[10px]', todayPnl >= 0 ? 'text-emerald-600' : 'text-red-500')}>
                        Today
                    </p>
                )}
            </td>
            <td className="px-4 py-3">
                <p className="text-sm font-price text-heading tabular-nums">
                    {Number(s.win_rate).toFixed(2)}%
                </p>
            </td>
            <td className="px-4 py-3">
                <p className="text-sm font-price text-heading tabular-nums">
                    {sharpe.toFixed(2)}
                </p>
            </td>
            <td className="px-4 py-3">
                <div className="flex items-center gap-1.5">
                    <button
                        onClick={() => onToggle(s.id)}
                        title={s.is_active ? 'Pause' : 'Start'}
                        className={cn(
                            'w-7 h-7 rounded-lg flex items-center justify-center transition-all',
                            s.is_active
                                ? 'bg-amber-500/10 text-amber-400 hover:bg-amber-500/20'
                                : 'bg-primary-500/10 text-primary-500 hover:bg-primary-500/20'
                        )}>
                        {s.is_active ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                    </button>

                    <div ref={ref} className="relative">
                        <button
                            onClick={() => onMenuOpen(menuOpen ? null : s.id)}
                            className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-500 hover:text-gray-300 hover:bg-surface-700/50 transition-all">
                            <MoreVertical className="w-3.5 h-3.5" />
                        </button>
                        {menuOpen && (
                            <div className="absolute right-0 top-8 z-30 w-40 bg-surface-800 border border-edge/10 rounded-xl shadow-2xl overflow-hidden">
                                <button
                                    onClick={() => { onEdit(s); onMenuOpen(null); }}
                                    className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-gray-300 hover:bg-surface-700/50 transition-colors">
                                    <Pencil className="w-3.5 h-3.5" /> Edit Strategy
                                </button>
                                <button
                                    onClick={() => { onViewLogs(s.id); onMenuOpen(null); }}
                                    className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-gray-300 hover:bg-surface-700/50 transition-colors">
                                    <Clock className="w-3.5 h-3.5" /> View Logs
                                </button>
                                {!s.is_active && (
                                    <button
                                        onClick={() => { onDelete(s.id); onMenuOpen(null); }}
                                        className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-red-400 hover:bg-red-500/10 transition-colors">
                                        <Trash2 className="w-3.5 h-3.5" /> Delete
                                    </button>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </td>
        </tr>
    );
}

// ── Param Fields ──────────────────────────────────────────────────────────────
function ParamFields({ type, params, onChange }) {
    const fields = STRATEGY_PARAMS[type] || [];
    return (
        <>
            <div>
                <label className="label-text">Trade Qty</label>
                <input type="number" min="1" max="1000"
                    value={params.quantity ?? 1}
                    onChange={e => onChange({ ...params, quantity: parseNumericInput(e.target.value, 1, 1, 1000, null) })}
                    className="input-field" />
            </div>
            {fields.map(f => (
                <div key={f.key}>
                    <label className="label-text">{f.label}</label>
                    <input type="number" step={f.step || 1} min={f.min} max={f.max}
                        value={params[f.key] ?? f.default}
                        onChange={e => onChange({
                            ...params,
                            [f.key]: parseNumericInput(e.target.value, f.default, f.min, f.max, f.step ? 4 : null),
                        })}
                        className="input-field" />
                    {f.hint && <p className="text-[10px] text-gray-600 mt-0.5">{f.hint}</p>}
                </div>
            ))}
        </>
    );
}

// ── Edit Modal ────────────────────────────────────────────────────────────────
function EditModal({ strategy, onClose, onSave }) {
    const [form, setForm] = useState({
        name: strategy.name,
        description: strategy.description || '',
        max_position_size: strategy.max_position_size,
        stop_loss_percent: strategy.stop_loss_percent,
        take_profit_percent: strategy.take_profit_percent,
        parameters: { ...getDefaultParams(strategy.strategy_type), ...(strategy.parameters || {}) },
    });
    const [saving, setSaving] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSaving(true);
        try { await onSave(strategy.id, buildUpdatePayload(strategy.strategy_type, form)); }
        finally { setSaving(false); }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
            <div className="relative w-full max-w-lg bg-surface-800 border border-edge/10 rounded-2xl shadow-2xl animate-slide-up">
                <div className="flex items-center justify-between px-5 py-3.5 border-b border-edge/5">
                    <h3 className="text-sm font-semibold text-heading">Edit Strategy</h3>
                    <button onClick={onClose} className="p-1 rounded hover:bg-surface-700 text-gray-500 hover:text-heading transition-colors">
                        <X className="w-4 h-4" />
                    </button>
                </div>
                <form onSubmit={handleSubmit} className="p-5 space-y-4 max-h-[70vh] overflow-y-auto">
                    <div className="grid grid-cols-2 gap-3">
                        <div className="col-span-2">
                            <label className="label-text">Name</label>
                            <input type="text" value={form.name} required
                                onChange={e => setForm(f => ({ ...f, name: e.target.value }))} className="input-field" />
                        </div>
                        <div>
                            <label className="label-text">Max Position Size</label>
                            <input type="number" value={form.max_position_size}
                                onChange={e => setForm(f => ({ ...f, max_position_size: parseNumericInput(e.target.value, 100, 1, 100000, null) }))} className="input-field" />
                        </div>
                        <div>
                            <label className="label-text">Stop Loss %</label>
                            <input type="number" step="0.1" value={form.stop_loss_percent}
                                onChange={e => setForm(f => ({ ...f, stop_loss_percent: parseNumericInput(e.target.value, 2, 0.1, 50, 2) }))} className="input-field" />
                        </div>
                        <div>
                            <label className="label-text">Take Profit %</label>
                            <input type="number" step="0.1" value={form.take_profit_percent}
                                onChange={e => setForm(f => ({ ...f, take_profit_percent: parseNumericInput(e.target.value, 5, 0.1, 200, 2) }))} className="input-field" />
                        </div>
                    </div>
                    <div>
                        <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">
                            {STRATEGY_TYPES.find(t => t.value === strategy.strategy_type)?.label} Parameters
                        </p>
                        <div className="grid grid-cols-2 gap-3">
                            <ParamFields type={strategy.strategy_type} params={form.parameters}
                                onChange={p => setForm(f => ({ ...f, parameters: p }))} />
                        </div>
                    </div>
                    <div>
                        <label className="label-text">Description</label>
                        <textarea value={form.description} rows="2"
                            onChange={e => setForm(f => ({ ...f, description: e.target.value }))} className="input-field resize-none" />
                    </div>
                    <div className="flex gap-3 pt-1">
                        <button type="submit" disabled={saving} className="btn-primary text-sm inline-flex items-center gap-2">
                            {saving ? 'Saving…' : 'Save Changes'}
                        </button>
                        <button type="button" onClick={onClose} className="btn-secondary text-sm">Cancel</button>
                    </div>
                </form>
            </div>
        </div>
    );
}

// ── New Strategy Modal ────────────────────────────────────────────────────────
function NewStrategyModal({ onClose, onCreate }) {
    const [form, setForm] = useState(getInitialForm());
    const [creating, setCreating] = useState(false);

    const handleTypeChange = (type) => {
        setForm(f => ({ ...f, strategy_type: type, parameters: getDefaultParams(type) }));
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        const payload = buildCreatePayload(form);
        if (!payload.name) { toast.error('Strategy name is required'); return; }
        if (!payload.symbol) { toast.error('Symbol is required'); return; }
        setCreating(true);
        try { await onCreate(payload); }
        finally { setCreating(false); }
    };

    const typeMeta = STRATEGY_TYPES.find(t => t.value === form.strategy_type) || {};

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
            <div className="relative w-full max-w-2xl bg-surface-800 border border-edge/10 rounded-2xl shadow-2xl animate-slide-up">
                <div className="flex items-center justify-between px-6 py-4 border-b border-edge/5">
                    <div>
                        <h3 className="text-base font-semibold text-heading">New Strategy</h3>
                        <p className="text-xs text-gray-500 mt-0.5">Configure your algo trading strategy</p>
                    </div>
                    <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-surface-700 text-gray-500 hover:text-heading transition-colors">
                        <X className="w-4 h-4" />
                    </button>
                </div>
                <form onSubmit={handleSubmit} className="p-6 space-y-5 max-h-[75vh] overflow-y-auto">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                            <label className="label-text">Strategy Name *</label>
                            <input type="text" value={form.name} required
                                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                                placeholder="e.g. Nifty EMA Scalper"
                                className="input-field" />
                        </div>
                        <div>
                            <label className="label-text">Symbol *</label>
                            <input type="text" value={form.symbol} required
                                onChange={e => setForm(f => ({ ...f, symbol: e.target.value }))}
                                placeholder="e.g. RELIANCE, HDFCBANK"
                                className="input-field" />
                        </div>
                        <div>
                            <label className="label-text">Strategy Type</label>
                            <select value={form.strategy_type}
                                onChange={e => handleTypeChange(e.target.value)}
                                className="input-field cursor-pointer">
                                {STRATEGY_TYPES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                            </select>
                        </div>
                        <div>
                            <label className="label-text">Max Position Size</label>
                            <input type="number" value={form.max_position_size}
                                onChange={e => setForm(f => ({ ...f, max_position_size: parseNumericInput(e.target.value, 100, 1, 100000, null) }))}
                                className="input-field" />
                        </div>
                        <div>
                            <label className="label-text">Stop Loss %</label>
                            <input type="number" step="0.1" value={form.stop_loss_percent}
                                onChange={e => setForm(f => ({ ...f, stop_loss_percent: parseNumericInput(e.target.value, 2, 0.1, 50, 2) }))}
                                className="input-field" />
                        </div>
                        <div>
                            <label className="label-text">Take Profit %</label>
                            <input type="number" step="0.1" value={form.take_profit_percent}
                                onChange={e => setForm(f => ({ ...f, take_profit_percent: parseNumericInput(e.target.value, 5, 0.1, 200, 2) }))}
                                className="input-field" />
                        </div>
                    </div>

                    <div className="rounded-xl border border-edge/5 bg-surface-900/50 p-4">
                        <div className="flex items-center justify-between mb-3">
                            <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
                                {typeMeta.label} Parameters
                            </p>
                        </div>
                        {typeMeta.desc && (
                            <p className="text-[11px] text-gray-500 mb-3 leading-relaxed">{typeMeta.desc}</p>
                        )}
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                            <ParamFields type={form.strategy_type} params={form.parameters}
                                onChange={p => setForm(f => ({ ...f, parameters: p }))} />
                        </div>
                    </div>

                    <div>
                        <label className="label-text">Description</label>
                        <textarea value={form.description} rows="2"
                            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                            placeholder="Describe your strategy logic..."
                            className="input-field resize-none" />
                    </div>

                    <div className="flex gap-3 pt-1">
                        <button type="submit" disabled={creating}
                            className="btn-primary text-sm inline-flex items-center gap-2">
                            <Zap className="w-4 h-4" />
                            {creating ? 'Creating…' : 'Create Strategy'}
                        </button>
                        <button type="button" onClick={onClose} className="btn-secondary text-sm">Cancel</button>
                    </div>
                </form>
            </div>
        </div>
    );
}

// ── Logs Modal ────────────────────────────────────────────────────────────────
function LogsModal({ strategyName, logs, onClose }) {
    const levelStyle = {
        ERROR: 'bg-red-500/10 text-red-400',
        TRADE: 'bg-primary-500/10 text-primary-500',
        WARNING: 'bg-amber-500/10 text-amber-400',
        INFO: 'bg-surface-700 text-gray-400',
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
            <div className="relative w-full max-w-xl bg-surface-800 border border-edge/10 rounded-2xl shadow-2xl">
                <div className="flex items-center justify-between px-5 py-3.5 border-b border-edge/5">
                    <div>
                        <h3 className="text-sm font-semibold text-heading">Strategy Logs</h3>
                        <p className="text-xs text-gray-500">{strategyName}</p>
                    </div>
                    <button onClick={onClose} className="p-1 rounded hover:bg-surface-700 text-gray-500 hover:text-heading transition-colors">
                        <X className="w-4 h-4" />
                    </button>
                </div>
                <div className="p-4 max-h-[60vh] overflow-y-auto space-y-1">
                    {logs.length === 0 ? (
                        <div className="text-center py-10 text-gray-600">
                            <Clock className="w-8 h-8 mx-auto mb-2 opacity-40" />
                            <p className="text-sm">No logs available</p>
                        </div>
                    ) : logs.map(l => (
                        <div key={l.id} className="flex items-start gap-2.5 py-2 text-sm border-b border-edge/[0.03]">
                            <span className={cn('text-[10px] font-price px-1.5 py-0.5 rounded flex-shrink-0 tabular-nums',
                                levelStyle[l.level] || levelStyle.INFO)}>
                                {l.level}
                            </span>
                            <span className="text-gray-400 flex-1 text-xs">{l.message}</span>
                            <span className="text-gray-600 text-[10px] ml-auto flex-shrink-0 font-mono">
                                {l.created_at ? new Date(l.created_at).toLocaleTimeString() : ''}
                            </span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

// ── Coming Soon Panel ─────────────────────────────────────────────────────────
function ComingSoon({ label }) {
    return (
        <div className="flex flex-col items-center justify-center py-24 gap-3">
            <div className="w-14 h-14 rounded-2xl bg-surface-800 border border-edge/5 flex items-center justify-center">
                <Wrench className="w-6 h-6 text-gray-600" />
            </div>
            <p className="text-base font-semibold text-gray-400">{label} — Coming Soon</p>
            <p className="text-sm text-gray-600 max-w-xs text-center">
                This feature is under active development and will be available soon.
            </p>
        </div>
    );
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function AlgoTradingPage() {
    const [tab, setTab] = useState('overview');
    const [strategies, setStrategies] = useState([]);
    const [stats, setStats] = useState(null);
    const [chartData, setChartData] = useState({ labels: [], values: [] });
    const [chartRange, setChartRange] = useState('1W');
    const [signals, setSignals] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showNewStrategy, setShowNewStrategy] = useState(false);
    const [editStrategy, setEditStrategy] = useState(null);
    const [logsData, setLogsData] = useState(null); // { strategyName, logs }
    const [openMenu, setOpenMenu] = useState(null);

    // ── Data loading ────────────────────────────────────────────────────────
    const loadData = useCallback(async (range = '1W') => {
        try {
            // Use allSettled so a single failing endpoint doesn't block the rest
            const [strategiesRes, statsRes, chartRes, signalsRes] = await Promise.allSettled([
                api.get('/algo/strategies'),
                api.get('/algo/overview-stats'),
                api.get(`/algo/performance-chart?range=${range}`),
                api.get('/algo/recent-signals'),
            ]);

            if (strategiesRes.status === 'fulfilled')
                setStrategies(strategiesRes.value.data.strategies || []);
            if (statsRes.status === 'fulfilled')
                setStats(statsRes.value.data);
            if (chartRes.status === 'fulfilled')
                setChartData(chartRes.value.data || { labels: [], values: [] });
            if (signalsRes.status === 'fulfilled')
                setSignals(signalsRes.value.data.signals || []);

            // Show error only if strategies (the primary endpoint) failed
            if (strategiesRes.status === 'rejected') {
                toast.error(parseApiError(strategiesRes.reason, 'Failed to load strategies'));
            }
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to load algo data'));
        } finally {
            setLoading(false);
        }
    }, []);

    const initPage = useCallback(async () => {
        try {
            await api.post('/algo/ensure-defaults');
        } catch {
            // Non-fatal — defaults already exist or seeding failed gracefully
        }
        await loadData(chartRange);
    }, [loadData, chartRange]);

    useEffect(() => { initPage(); }, [initPage]);

    const handleRangeChange = async (range) => {
        setChartRange(range);
        try {
            const res = await api.get(`/algo/performance-chart?range=${range}`);
            setChartData(res.data || { labels: [], values: [] });
        } catch { /* silent */ }
    };

    // ── Actions ─────────────────────────────────────────────────────────────
    const handleToggle = async (id) => {
        try {
            const res = await api.put(`/algo/strategies/${id}/toggle`);
            toast.success(res.data.message);
            await loadData(chartRange);
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to toggle strategy'));
        }
    };

    const handleDelete = async (id) => {
        try {
            await api.delete(`/algo/strategies/${id}`);
            toast.success('Strategy deleted');
            await loadData(chartRange);
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to delete strategy'));
        }
    };

    const handleUpdate = async (id, data) => {
        try {
            await api.put(`/algo/strategies/${id}`, data);
            toast.success('Strategy updated');
            setEditStrategy(null);
            await loadData(chartRange);
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to update strategy'));
        }
    };

    const handleCreate = async (payload) => {
        try {
            const res = await api.post('/algo/strategies', payload);
            toast.success('Strategy created!');
            setShowNewStrategy(false);
            const created = res?.data?.strategy;
            if (created?.id) setStrategies(prev => [created, ...prev]);
            await loadData(chartRange);
        } catch (err) {
            toast.error(parseApiError(err, 'Failed to create strategy'));
            throw err;
        }
    };

    const handleViewLogs = async (id) => {
        const s = strategies.find(x => x.id === id);
        try {
            const res = await api.get(`/algo/strategies/${id}/logs`);
            setLogsData({ strategyName: s?.name || 'Strategy', logs: res.data.logs || [] });
        } catch {
            toast.error('Failed to load logs');
        }
    };

    // ── Computed ─────────────────────────────────────────────────────────────
    const activeStrategies = strategies.filter(s => s.is_active);
    const topPerformers = [...strategies].sort((a, b) => Number(b.total_pnl) - Number(a.total_pnl)).slice(0, 5);

    const donutSegments = (() => {
        const counts = {};
        strategies.forEach(s => {
            const tf = TIMEFRAME_MAP[s.strategy_type] || 'Intraday';
            counts[tf] = (counts[tf] || 0) + 1;
        });
        const total = strategies.length || 1;
        return Object.entries(counts).map(([label, count]) => ({
            label,
            count,
            pct: Math.round((count / total) * 100),
            color: DONUT_COLORS[label] || '#6b7280',
        }));
    })();

    const totalPnl = stats?.total_pnl ?? 0;
    const isProfit = totalPnl >= 0;

    if (loading) {
        return (
            <div className="flex items-center justify-center h-[60vh]">
                <div className="w-10 h-10 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    // ── Render ───────────────────────────────────────────────────────────────
    return (
        <div className="p-4 lg:p-6 space-y-5 animate-fade-in">

            {/* ── Header ── */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div>
                    <h1 className="text-2xl font-display font-bold text-heading">Algo Trading</h1>
                    <p className="text-sm text-gray-500 mt-0.5">Build, deploy and automate your trading strategies.</p>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                        onClick={() => toast('Import functionality coming soon', { icon: '📥' })}
                        className="btn-secondary text-sm inline-flex items-center gap-2 py-2 px-4">
                        <Upload className="w-4 h-4" /> Import Strategy
                    </button>
                    <button
                        onClick={() => setShowNewStrategy(true)}
                        className="btn-primary text-sm inline-flex items-center gap-2 py-2 px-4">
                        <Plus className="w-4 h-4" /> New Strategy
                    </button>
                </div>
            </div>

            {/* ── Stats Row ── */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                <StatCard
                    icon={Activity}
                    iconBg="bg-emerald-500/10 text-emerald-400"
                    label="Active Strategies"
                    value={activeStrategies.length}
                    sub="Running live"
                    subColor="text-emerald-500"
                />
                <StatCard
                    icon={Zap}
                    iconBg="bg-primary-500/10 text-primary-500"
                    label="Total Strategies"
                    value={strategies.length}
                    sub="All time"
                    subColor="text-gray-500"
                />
                <StatCard
                    icon={isProfit ? TrendingUp : TrendingDown}
                    iconBg={isProfit ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}
                    label="Total P&L"
                    value={fmtCompact(totalPnl)}
                    sub={totalPnl === 0 ? 'No trades yet' : `${totalPnl >= 0 ? '+' : ''}${((totalPnl / (Math.abs(totalPnl) + 1)) * 100).toFixed(2)}%`}
                    subColor={isProfit ? 'text-emerald-500' : 'text-red-500'}
                />
                <StatCard
                    icon={Target}
                    iconBg="bg-amber-500/10 text-amber-400"
                    label="Win Rate (Avg.)"
                    value={`${(stats?.avg_win_rate ?? 0).toFixed(2)}%`}
                    sub={strategies.length > 0 ? 'Across all strategies' : 'No data yet'}
                    subColor="text-gray-500"
                />
                <StatCard
                    icon={Shield}
                    iconBg="bg-red-500/10 text-red-400"
                    label="Max Drawdown (Avg.)"
                    value={`${(stats?.avg_max_drawdown ?? 0).toFixed(2)}%`}
                    sub={stats?.avg_max_drawdown > 0 ? 'Risk exposure' : 'No drawdown'}
                    subColor="text-red-500"
                />
                <StatCard
                    icon={BarChart2}
                    iconBg="bg-blue-500/10 text-blue-400"
                    label="Sharpe Ratio (Avg.)"
                    value={(stats?.avg_sharpe_ratio ?? 0).toFixed(2)}
                    sub={stats?.avg_sharpe_ratio > 1 ? 'Excellent' : stats?.avg_sharpe_ratio > 0 ? 'Positive' : 'No data yet'}
                    subColor={stats?.avg_sharpe_ratio > 1 ? 'text-emerald-500' : 'text-gray-500'}
                />
            </div>

            {/* ── Tab Navigation ── */}
            <div className="flex border-b border-edge/10 gap-0 overflow-x-auto scrollbar-hide">
                {TABS.map(t => (
                    <button key={t.id} onClick={() => setTab(t.id)}
                        className={cn(
                            'flex-shrink-0 px-4 py-2.5 text-sm font-medium relative transition-colors whitespace-nowrap',
                            tab === t.id
                                ? 'text-primary-500 after:absolute after:bottom-0 after:left-0 after:right-0 after:h-0.5 after:bg-primary-500 after:rounded-t'
                                : 'text-gray-500 hover:text-gray-300'
                        )}>
                        {t.label}
                    </button>
                ))}
            </div>

            {/* ── Overview Tab ── */}
            {tab === 'overview' && (
                <div className="space-y-5">
                    {/* Main 2-col layout */}
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
                        {/* Active Strategies Table */}
                        <div className="lg:col-span-2 rounded-xl border border-edge/5 bg-surface-900/60 overflow-hidden">
                            <div className="flex items-center justify-between px-5 py-3.5 border-b border-edge/5">
                                <div className="flex items-center gap-2">
                                    <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                                    <h2 className="text-sm font-semibold text-heading">My Active Strategies</h2>
                                </div>
                                <button
                                    onClick={() => setTab('my-strategies')}
                                    className="text-xs text-primary-500 hover:text-primary-400 flex items-center gap-1 transition-colors">
                                    View All <ChevronRight className="w-3 h-3" />
                                </button>
                            </div>

                            {activeStrategies.length === 0 ? (
                                <div className="flex flex-col items-center justify-center py-16 gap-3">
                                    <div className="w-12 h-12 rounded-xl bg-surface-800 border border-edge/5 flex items-center justify-center">
                                        <Zap className="w-6 h-6 text-gray-600" />
                                    </div>
                                    <p className="text-sm font-medium text-gray-400">No active strategies</p>
                                    <p className="text-xs text-gray-600 text-center max-w-xs">
                                        Start a strategy to see it here. {strategies.length > 0 ? 'Press the play button on any strategy.' : 'Create a new strategy to get started.'}
                                    </p>
                                    {strategies.length === 0 && (
                                        <button onClick={() => setShowNewStrategy(true)} className="btn-primary text-xs mt-1 inline-flex items-center gap-1.5">
                                            <Plus className="w-3.5 h-3.5" /> New Strategy
                                        </button>
                                    )}
                                </div>
                            ) : (
                                <>
                                    <div className="overflow-x-auto">
                                        <table className="w-full">
                                            <thead>
                                                <tr className="border-b border-edge/5">
                                                    {['Strategy Name', 'Status', 'PnL', "Today's P&L", 'Win Rate', 'Sharpe', 'Actions'].map(h => (
                                                        <th key={h} className="px-4 py-2.5 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                                                            {h}
                                                        </th>
                                                    ))}
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {activeStrategies.slice(0, 5).map(s => (
                                                    <StrategyRow
                                                        key={s.id} s={s}
                                                        onToggle={handleToggle}
                                                        onEdit={setEditStrategy}
                                                        onDelete={handleDelete}
                                                        onViewLogs={handleViewLogs}
                                                        menuOpen={openMenu === s.id}
                                                        onMenuOpen={setOpenMenu}
                                                    />
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                    {activeStrategies.length > 5 && (
                                        <div className="px-5 py-3 border-t border-edge/5 text-center">
                                            <button onClick={() => setTab('my-strategies')}
                                                className="text-xs text-primary-500 hover:text-primary-400 flex items-center gap-1 mx-auto transition-colors">
                                                View All {activeStrategies.length} Strategies <ChevronRight className="w-3 h-3" />
                                            </button>
                                        </div>
                                    )}
                                </>
                            )}
                        </div>

                        {/* P&L Chart */}
                        <div className="rounded-xl border border-edge/5 bg-surface-900/60 overflow-hidden">
                            <div className="flex items-center justify-between px-5 py-3.5 border-b border-edge/5">
                                <h2 className="text-sm font-semibold text-heading">Strategy Performance (P&L)</h2>
                            </div>
                            <div className="px-4 pt-4 pb-2">
                                <PnLChart labels={chartData.labels} values={chartData.values} />
                            </div>
                            <div className="flex items-center justify-center gap-1 px-4 pb-4">
                                {CHART_RANGES.map(r => (
                                    <button key={r} onClick={() => handleRangeChange(r)}
                                        className={cn(
                                            'px-2.5 py-1 rounded-lg text-[11px] font-medium transition-colors',
                                            chartRange === r
                                                ? 'bg-primary-500/15 text-primary-500 border border-primary-500/30'
                                                : 'text-gray-500 hover:text-gray-300 hover:bg-surface-700/50'
                                        )}>
                                        {r}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>

                    {/* Bottom 4-col row */}
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                        {/* Top Performing */}
                        <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-4">
                            <div className="flex items-center justify-between mb-3">
                                <h3 className="text-xs font-semibold text-heading">Top Performing</h3>
                                <button onClick={() => setTab('my-strategies')}
                                    className="text-[10px] text-primary-500 hover:text-primary-400 flex items-center gap-0.5 transition-colors">
                                    View All <ChevronRight className="w-3 h-3" />
                                </button>
                            </div>
                            {topPerformers.length === 0 ? (
                                <p className="text-xs text-gray-600 text-center py-4">No strategies yet</p>
                            ) : (
                                <div className="space-y-2">
                                    {topPerformers.map((s, i) => (
                                        <div key={s.id} className="flex items-center gap-2.5">
                                            <span className={cn(
                                                'w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0',
                                                i === 0 ? 'bg-amber-500/20 text-amber-400' :
                                                    i === 1 ? 'bg-gray-500/20 text-gray-400' :
                                                        i === 2 ? 'bg-orange-700/20 text-orange-600' :
                                                            'bg-surface-700/50 text-gray-600'
                                            )}>{i + 1}</span>
                                            <div className="flex-1 min-w-0">
                                                <p className="text-xs font-medium text-heading truncate">{s.name}</p>
                                            </div>
                                            <div className="text-right flex-shrink-0">
                                                <p className={cn('text-xs font-price font-semibold tabular-nums', pnlColorClass(s.total_pnl))}>
                                                    {fmtCompact(s.total_pnl)}
                                                </p>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        {/* Recent Signals */}
                        <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-4">
                            <div className="flex items-center justify-between mb-3">
                                <h3 className="text-xs font-semibold text-heading">Recent Signals</h3>
                                <button onClick={() => setTab('logs')}
                                    className="text-[10px] text-primary-500 hover:text-primary-400 flex items-center gap-0.5 transition-colors">
                                    View All <ChevronRight className="w-3 h-3" />
                                </button>
                            </div>
                            {signals.length === 0 ? (
                                <div className="text-center py-4">
                                    <p className="text-xs text-gray-600">No signals yet</p>
                                    <p className="text-[10px] text-gray-700 mt-0.5">Activate strategies to generate signals</p>
                                </div>
                            ) : (
                                <div className="space-y-2.5">
                                    {signals.map((sig, i) => (
                                        <div key={i} className="flex items-start gap-2">
                                            <div className={cn(
                                                'w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0',
                                                sig.side === 'BUY' ? 'bg-emerald-500/10' : 'bg-red-500/10'
                                            )}>
                                                {sig.side === 'BUY'
                                                    ? <TrendingUp className="w-3 h-3 text-emerald-400" />
                                                    : <TrendingDown className="w-3 h-3 text-red-400" />
                                                }
                                            </div>
                                            <div className="flex-1 min-w-0">
                                                <div className="flex items-center gap-1.5">
                                                    <p className="text-xs font-medium text-heading truncate">{sig.strategy_name}</p>
                                                    <span className={cn(
                                                        'text-[9px] font-bold px-1.5 py-0.5 rounded uppercase',
                                                        sig.side === 'BUY' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
                                                    )}>{sig.side}</span>
                                                </div>
                                                <p className="text-[10px] text-gray-500">{cleanSymbol(sig.symbol)}</p>
                                                <p className="text-[10px] font-price text-gray-400 tabular-nums">₹{Number(sig.price).toFixed(2)}</p>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        {/* Strategies by Type */}
                        <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-4">
                            <h3 className="text-xs font-semibold text-heading mb-3">Strategies by Type</h3>
                            {strategies.length === 0 ? (
                                <div className="text-center py-4">
                                    <p className="text-xs text-gray-600">No strategies yet</p>
                                </div>
                            ) : (
                                <div className="flex items-center gap-3">
                                    <DonutChart segments={donutSegments} total={strategies.length} />
                                    <div className="space-y-1.5 min-w-0">
                                        {donutSegments.map((seg, i) => (
                                            <div key={i} className="flex items-center gap-2">
                                                <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: seg.color }} />
                                                <span className="text-[11px] text-gray-400 truncate">{seg.label}</span>
                                                <span className="text-[11px] font-semibold text-heading ml-auto">{seg.count}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                            <p className="text-[10px] text-gray-600 mt-3">Total Strategies: {strategies.length}</p>
                        </div>

                        {/* Quick Actions */}
                        <div className="rounded-xl border border-edge/5 bg-surface-900/60 p-4">
                            <h3 className="text-xs font-semibold text-heading mb-3">Quick Actions</h3>
                            <div className="space-y-2">
                                {[
                                    {
                                        icon: Plus, label: 'Create New Strategy',
                                        sub: 'Build a new algo strategy',
                                        action: () => setShowNewStrategy(true),
                                        primary: true,
                                    },
                                    {
                                        icon: BarChart2, label: 'Backtest Strategy',
                                        sub: 'Test on historical data',
                                        action: () => setTab('backtesting'),
                                    },
                                    {
                                        icon: Zap, label: 'Deploy Strategy',
                                        sub: 'Go live with your strategy',
                                        action: () => toast('Select a strategy and press Play to deploy', { icon: '⚡' }),
                                    },
                                    {
                                        icon: Activity, label: 'Strategy Marketplace',
                                        sub: 'Explore community strategies',
                                        action: () => setTab('marketplace'),
                                    },
                                ].map((item, i) => (
                                    <button key={i} onClick={item.action}
                                        className={cn(
                                            'w-full flex items-center gap-3 p-2.5 rounded-lg transition-all text-left group',
                                            item.primary
                                                ? 'bg-primary-500/10 border border-primary-500/20 hover:bg-primary-500/15'
                                                : 'bg-surface-800/50 hover:bg-surface-700/50 border border-edge/5'
                                        )}>
                                        <div className={cn('w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0',
                                            item.primary ? 'bg-primary-500/20' : 'bg-surface-700/80')}>
                                            <item.icon className={cn('w-3.5 h-3.5', item.primary ? 'text-primary-500' : 'text-gray-400')} />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <p className={cn('text-xs font-medium', item.primary ? 'text-primary-500' : 'text-gray-300')}>{item.label}</p>
                                            <p className="text-[10px] text-gray-600">{item.sub}</p>
                                        </div>
                                        <ChevronRight className="w-3.5 h-3.5 text-gray-600 group-hover:text-gray-400 transition-colors" />
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* ── My Strategies Tab ── */}
            {tab === 'my-strategies' && (
                <div className="rounded-xl border border-edge/5 bg-surface-900/60 overflow-hidden">
                    <div className="flex items-center justify-between px-5 py-3.5 border-b border-edge/5">
                        <h2 className="text-sm font-semibold text-heading">All Strategies ({strategies.length})</h2>
                        <button onClick={() => setShowNewStrategy(true)}
                            className="btn-primary text-xs inline-flex items-center gap-1.5 py-1.5 px-3">
                            <Plus className="w-3.5 h-3.5" /> New
                        </button>
                    </div>

                    {strategies.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-20 gap-4">
                            <div className="w-14 h-14 rounded-2xl bg-surface-800 border border-edge/5 flex items-center justify-center">
                                <Zap className="w-7 h-7 text-gray-600" />
                            </div>
                            <div className="text-center">
                                <p className="text-sm font-semibold text-gray-400">No strategies yet</p>
                                <p className="text-xs text-gray-600 mt-1 max-w-xs">
                                    Create your first algo trading strategy to get started.
                                </p>
                            </div>
                            <button onClick={() => setShowNewStrategy(true)} className="btn-primary text-sm inline-flex items-center gap-2">
                                <Plus className="w-4 h-4" /> Create Strategy
                            </button>

                            {/* Template gallery */}
                            <div className="w-full max-w-2xl mt-4 px-5">
                                <p className="text-[11px] text-gray-500 uppercase tracking-wider mb-3">Strategy Templates</p>
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                                    {STRATEGY_TYPES.map(st => (
                                        <button key={st.value}
                                            onClick={() => { setShowNewStrategy(true); }}
                                            className="rounded-xl border border-edge/5 bg-surface-900/40 hover:border-primary-500/25 hover:bg-surface-900/80 transition-all p-3.5 text-left group">
                                            <div className="flex items-center gap-2 mb-1">
                                                <span className="w-6 h-6 rounded-lg bg-primary-500/10 flex items-center justify-center">
                                                    <Zap className="w-3 h-3 text-primary-600" />
                                                </span>
                                                <span className="text-xs font-semibold text-heading group-hover:text-primary-500 transition-colors">{st.label}</span>
                                            </div>
                                            <p className="text-[10px] text-gray-500 leading-relaxed">{st.desc}</p>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full">
                                <thead>
                                    <tr className="border-b border-edge/5">
                                        {['Strategy Name', 'Status', 'PnL', "Today's P&L", 'Win Rate', 'Sharpe', 'Actions'].map(h => (
                                            <th key={h} className="px-4 py-2.5 text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                                                {h}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {strategies.map(s => (
                                        <StrategyRow
                                            key={s.id} s={s}
                                            onToggle={handleToggle}
                                            onEdit={setEditStrategy}
                                            onDelete={handleDelete}
                                            onViewLogs={handleViewLogs}
                                            menuOpen={openMenu === s.id}
                                            onMenuOpen={setOpenMenu}
                                        />
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            )}

            {/* ── Logs Tab ── */}
            {tab === 'logs' && (
                <div className="space-y-3">
                    {strategies.length === 0 ? (
                        <div className="rounded-xl border border-edge/5 bg-surface-900/60 flex flex-col items-center justify-center py-20 gap-3">
                            <Clock className="w-10 h-10 text-gray-600 opacity-50" />
                            <p className="text-sm text-gray-500">No strategies to show logs for</p>
                        </div>
                    ) : (
                        strategies.map(s => (
                            <div key={s.id} className="rounded-xl border border-edge/5 bg-surface-900/60 overflow-hidden">
                                <div className="flex items-center justify-between px-5 py-3 border-b border-edge/5">
                                    <div className="flex items-center gap-2">
                                        <StatusBadge isActive={s.is_active} />
                                        <span className="text-sm font-semibold text-heading">{s.name}</span>
                                        <span className="text-xs text-gray-500">· {cleanSymbol(s.symbol)}</span>
                                    </div>
                                    <button onClick={() => handleViewLogs(s.id)}
                                        className="text-xs text-primary-500 hover:text-primary-400 flex items-center gap-1 transition-colors">
                                        View Logs <ChevronRight className="w-3 h-3" />
                                    </button>
                                </div>
                                <div className="px-5 py-3 text-xs text-gray-600">
                                    {s.total_trades} trades · {fmtPnl(s.total_pnl)} total P&L · {s.win_rate}% win rate
                                </div>
                            </div>
                        ))
                    )}
                </div>
            )}

            {/* ── Coming Soon Tabs ── */}
            {tab === 'backtesting' && <ComingSoon label="Backtesting" />}
            {tab === 'marketplace' && <ComingSoon label="Strategy Marketplace" />}
            {tab === 'performance' && <ComingSoon label="Performance Analytics" />}
            {tab === 'risk' && <ComingSoon label="Risk Management" />}

            {/* ── Modals ── */}
            {showNewStrategy && (
                <NewStrategyModal
                    onClose={() => setShowNewStrategy(false)}
                    onCreate={handleCreate}
                />
            )}
            {editStrategy && (
                <EditModal
                    strategy={editStrategy}
                    onClose={() => setEditStrategy(null)}
                    onSave={handleUpdate}
                />
            )}
            {logsData && (
                <LogsModal
                    strategyName={logsData.strategyName}
                    logs={logsData.logs}
                    onClose={() => setLogsData(null)}
                />
            )}
        </div>
    );
}
