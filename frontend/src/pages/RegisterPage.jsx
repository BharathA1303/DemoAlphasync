// RegisterPage.jsx
import { useState, useEffect, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuthStore } from "../stores/useAuthStore";
import { useMarketIndicesStore } from "../stores/useMarketIndicesStore";
import { Mail, Lock, User, Eye, EyeOff, ArrowRight, ShieldCheck, LayoutDashboard } from "lucide-react";
import toast from "react-hot-toast";
import usePageMeta from "../hooks/usePageMeta";
import AuthPanelLeft from "../components/layout/AuthPanelLeft";

/* ─── Password Strength Bar ───────────────────────────────────── */
function StrengthBar({ password }) {
  if (!password) return null;
  const score = [
    password.length >= 8,
    /[A-Z]/.test(password),
    /[0-9]/.test(password),
    /[^A-Za-z0-9]/.test(password),
  ].filter(Boolean).length;
  const configs = [
    { label: "Too short", bar: "bg-red-500/60", text: "text-red-500/60" },
    { label: "Weak", bar: "bg-red-500", text: "text-red-500" },
    { label: "Fair", bar: "bg-primary-500", text: "text-primary-600" },
    { label: "Good", bar: "bg-sky-400", text: "text-sky-600" },
    { label: "Strong", bar: "bg-emerald-400", text: "text-emerald-600" },
  ];
  const cfg = configs[score];
  return (
    <div className="mt-2 space-y-1">
      <div className="flex gap-1">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className={`h-[3px] flex-1 rounded-full transition-all duration-300 ${i <= score ? cfg.bar : "bg-slate-200"}`}
          />
        ))}
      </div>
      <p className={`text-[10px] font-bold ${cfg.text}`}>
        {cfg.label} password
      </p>
    </div>
  );
}

/* ─── Simulated holdings config (qty & avg offset from live price) ── */
const HOLDINGS_CONFIG = [
  { match: "Reliance", sym: "RELIANCE", qty: 10, avgOffset: -0.028 },
  { match: "TCS", sym: "TCS", qty: 5, avgOffset: -0.042 },
  { match: "HDFC Bank", sym: "HDFCBANK", qty: 20, avgOffset: 0.016 },
  { match: "Infosys", sym: "INFY", qty: 15, avgOffset: 0.022 },
  { match: "Bharti Airtel", sym: "AIRTEL", qty: 3, avgOffset: -0.032 },
];

/* ─── Left Panel: Animated Portfolio Visual ───────────────────── */
function RegisterAnimation() {
  const tickerItems = useMarketIndicesStore((s) => s.tickerItems);
  const startPolling = useMarketIndicesStore((s) => s.startPolling);
  const stopPolling = useMarketIndicesStore((s) => s.stopPolling);

  useEffect(() => {
    startPolling(30_000);
    return () => stopPolling();
  }, [startPolling, stopPolling]);

  const portfolioItems = useMemo(() => {
    if (tickerItems.length === 0) return [];
    return HOLDINGS_CONFIG.map((cfg) => {
      const tick = tickerItems.find((t) => (t.name || "").includes(cfg.match));
      if (!tick) return null;
      const ltp = tick.price || 0;
      const avg = Math.round(ltp * (1 + cfg.avgOffset));
      const pnlVal = (ltp - avg) * cfg.qty;
      const pctVal = avg ? ((ltp - avg) / avg) * 100 : 0;
      const up = pnlVal >= 0;
      return {
        sym: cfg.sym,
        qty: cfg.qty,
        avg,
        ltp: Math.round(ltp),
        pnl: `${up ? "+" : "-"}₹${Math.abs(Math.round(pnlVal)).toLocaleString("en-IN")}`,
        up,
        pct: `${up ? "+" : ""}${pctVal.toFixed(1)}%`,
      };
    }).filter(Boolean);
  }, [tickerItems]);

  const totalValue = portfolioItems.reduce((s, i) => s + i.ltp * i.qty, 0);
  const totalPnl = portfolioItems.reduce((s, i) => s + (i.ltp - i.avg) * i.qty, 0);
  const totalPnlPct = totalValue ? (totalPnl / (totalValue - totalPnl)) * 100 : 0;

  const donutData = [
    { label: "IT", pct: 34, col: "#00bcd4" },
    { label: "Banking", pct: 28, col: "#1E6FA8" },
    { label: "Finance", pct: 20, col: "#1A2B4A" },
    { label: "Others", pct: 18, col: "#2E9E6B" },
  ];

  // Simple donut math
  let offset = 0;
  const r = 36,
    circ = 2 * Math.PI * r;
  const donutSlices = donutData.map((d) => {
    const len = (d.pct / 100) * circ;
    const gap = 3;
    const slice = {
      ...d,
      dasharray: `${len - gap} ${circ - len + gap}`,
      dashoffset: -offset,
    };
    offset += len;
    return slice;
  });

  return (
    <div className="relative w-full h-full flex flex-col overflow-hidden select-none">
      {/* Glows */}
      <div
        className="absolute -top-20 -left-20 w-72 h-72 rounded-full blur-3xl"
        style={{ background: 'rgba(14,165,233,0.12)', animation: "pulse 4s ease-in-out infinite" }}
      />
      <div
        className="absolute bottom-20 right-0 w-64 h-64 rounded-full blur-3xl"
        style={{ background: 'rgba(30,111,168,0.10)', animation: "pulse 5s ease-in-out infinite" }}
      />

      <div className="relative z-10 flex-1 flex flex-col justify-center px-7 py-3 gap-3 overflow-hidden">
        {/* Portfolio card */}
        <div
          className="rounded-2xl overflow-hidden shadow-2xl"
          style={{
            background: "rgba(15,26,48,0.85)",
            border: '1px solid rgba(255,255,255,0.10)',
            backdropFilter: "blur(20px)",
            boxShadow: '0 25px 50px -12px rgba(0,0,0,0.3)',
          }}
        >
          {/* Header */}
          <div
            className="flex items-center justify-between px-5 py-3"
            style={{ background: "rgba(15,26,48,0.5)", borderBottom: '1px solid rgba(255,255,255,0.06)' }}
          >
            <span className="text-[11px] font-bold text-gray-300 tracking-widest uppercase">
              Portfolio
            </span>
            <span className="flex items-center gap-1.5 text-[11px] text-emerald-600 font-bold">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
              </span>
              LIVE
            </span>
          </div>

          {/* PnL summary row */}
          <div className="flex items-center justify-between px-5 py-3" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <div>
              <div className="text-[10px] text-gray-400 font-semibold uppercase tracking-wider">
                Total Value
              </div>
              <div className="text-lg font-black text-white font-mono tracking-tight mt-0.5">
                ₹{totalValue.toLocaleString('en-IN')}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[10px] text-gray-400 font-semibold uppercase tracking-wider">
                Day P&amp;L
              </div>
              <div className={`text-base font-black font-mono mt-0.5 ${totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {totalPnl >= 0 ? '+' : '-'}₹{Math.abs(Math.round(totalPnl)).toLocaleString('en-IN')}
              </div>
              <div className={`text-[10px] font-mono ${totalPnl >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                {totalPnl >= 0 ? '+' : ''}{totalPnlPct.toFixed(2)}%
              </div>
            </div>
            {/* Mini donut */}
            <div className="relative w-16 h-16">
              <svg viewBox="0 0 88 88" className="w-full h-full -rotate-90">
                {donutSlices.map((s, i) => (
                  <circle
                    key={i}
                    cx="44"
                    cy="44"
                    r={r}
                    fill="none"
                    stroke={s.col}
                    strokeWidth="10"
                    strokeDasharray={s.dasharray}
                    strokeDashoffset={s.dashoffset}
                    opacity="0.85"
                  />
                ))}
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-[9px] font-black text-gray-300">MIX</span>
              </div>
            </div>
          </div>

          {/* Holdings */}
          <div className="divide-y divide-white/[0.06]">
            {portfolioItems.map((item, i) => (
              <div
                key={item.sym}
                className="flex items-center px-5 py-2.5 hover:bg-white/[0.04] transition-colors"
                style={{
                  animation: `fadeInUp 0.3s ease-out ${i * 0.07}s both`,
                }}
              >
                <div className="w-16">
                  <div className="text-[11px] font-black text-gray-300 tracking-wide">
                    {item.sym}
                  </div>
                  <div className="text-[9px] text-gray-500 mt-0.5">
                    {item.qty} shares
                  </div>
                </div>
                <div className="flex-1 text-center">
                  <div className="text-[11px] font-mono text-gray-300">
                    ₹{item.ltp.toLocaleString()}
                  </div>
                </div>
                <div className="text-right">
                  <div
                    className={`text-[11px] font-black font-mono ${item.up ? "text-emerald-400" : "text-red-400"}`}
                  >
                    {item.pnl}
                  </div>
                  <div
                    className={`text-[9px] font-mono ${item.up ? "text-emerald-400" : "text-red-400"}`}
                  >
                    {item.pct}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Sector legend row */}
        <div className="flex gap-2 flex-wrap">
          {donutData.map((d) => (
            <div
              key={d.label}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full"
              style={{ border: '1px solid rgba(255,255,255,0.10)', background: 'rgba(255,255,255,0.05)' }}
            >
              <span
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ background: d.col }}
              />
              <span className="text-[10px] text-gray-400 font-semibold">
                {d.label} {d.pct}%
              </span>
            </div>
          ))}
        </div>
      </div>

      <style>{`
                @keyframes fadeInUp { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
                @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.5; } }
            `}</style>
    </div>
  );
}

/* ─── Main Page ────────────────────────────────────────────────── */
export default function RegisterPage() {
  usePageMeta(
    "Create Free Account — Start Paper Trading Today",
    "Register for AlphaSync — India's best paper trading platform. Get ₹10 lakh virtual capital instantly. No KYC, no broker account needed."
  );
  const [formData, setFormData] = useState({
    email: "",
    username: "",
    password: "",
    full_name: "",
  });
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const registerWithEmail = useAuthStore((s) => s.registerWithEmail);
  const loginWithGoogle = useAuthStore((s) => s.loginWithGoogle);
  const existingUser = useAuthStore((s) => s.user);
  const navigate = useNavigate();

  // Check if user already has an active session with onboarding complete
  const hasActiveSession = existingUser && localStorage.getItem('alphasync_onboarded');

  // Auto-redirect to dashboard if already authenticated (e.g. demo mode)
  useEffect(() => {
    if (hasActiveSession) {
      navigate('/dashboard', { replace: true });
    }
  }, [hasActiveSession, navigate]);

  const set = (key) => (e) =>
    setFormData((prev) => ({ ...prev, [key]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (formData.password.length < 6)
      return toast.error("Password must be at least 6 characters");
    setLoading(true);
    try {
      const result = await registerWithEmail(formData.email, formData.password, formData.full_name, formData.username);
      if (result.needsVerification) {
        // Redirect to verify email page
        navigate("/verify-email", { state: { email: formData.email, password: formData.password } });
      } else {
        navigate("/select-mode");
      }
    } catch (err) {
      const code = err.code;
      if (code === "auth/email-already-in-use") {
        toast.error("Email already registered. Try signing in.");
      } else if (code === "auth/weak-password") {
        toast.error("Password is too weak. Use at least 6 characters.");
      } else {
        toast.error(err.message || "Registration failed");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleSignUp = async () => {
    setGoogleLoading(true);
    try {
      const result = await loginWithGoogle("register");
      if (result.isNew) {
        toast.success("Welcome to AlphaSync!");
      } else {
        toast.success("Welcome back!");
      }
      navigate("/select-mode");
    } catch (err) {
      if (err.code !== "auth/popup-closed-by-user") {
        toast.error(err.message || "Google sign-up failed");
      }
    } finally {
      setGoogleLoading(false);
    }
  };

  const fieldCls =
    "w-full py-2.5 rounded-xl text-sm placeholder-slate-400 border transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-[#00D4FF]/15 focus:border-[#00D4FF]";
  const fieldBg = "bg-slate-50 border-slate-300 text-slate-900";

  return (
    <div
      className="h-screen w-screen overflow-hidden flex"
      style={{ background: "#FFFFFF" }}
    >
      {/* LEFT — animated portfolio panel */}
      <AuthPanelLeft>
        <RegisterAnimation />
      </AuthPanelLeft>

      {/* RIGHT — premium form */}
      <div
        className="flex-1 h-full flex items-center justify-center px-7 xl:px-10 relative overflow-hidden"
        style={{
          background: "#FFFFFF",
        }}
      >
        {/* Glows */}
        <div
          className="absolute -top-10 -right-10 w-96 h-96 rounded-full pointer-events-none"
          style={{
            background:
              "radial-gradient(circle, rgba(14,165,233,0.06) 0%, transparent 70%)",
          }}
        />
        <div
          className="absolute -bottom-10 -left-10 w-72 h-72 rounded-full pointer-events-none"
          style={{
            background:
              "radial-gradient(circle, rgba(30,111,168,0.04) 0%, transparent 70%)",
          }}
        />

        {/* Corner accents */}
        <div className="absolute top-0 right-0 w-32 h-32 border-r border-t rounded-bl-3xl pointer-events-none" style={{ borderColor: 'rgba(14,165,233,0.1)' }} />
        <div className="absolute bottom-0 left-0 w-24 h-24 border-l border-b border-slate-200 rounded-tr-3xl pointer-events-none" />

        {/* Mobile logo */}
        <div className="lg:hidden absolute top-7 left-1/2 -translate-x-1/2">
          <a href="https://www.alphasync.app/">
            <img
              src="/logo.svg"
              alt="AlphaSync"
              className="h-12 object-contain"
              style={{ filter: 'none' }}
            />
          </a>
        </div>

        <div className="w-full max-w-[400px] relative z-10">
          {/* Live pill */}
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full mb-5" style={{ background: 'rgba(0,212,255,0.1)', border: '1px solid rgba(0,212,255,0.3)' }}>
            <span className="relative flex h-1.5 w-1.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#00AA88] opacity-75" />
              <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-[#00AA88]" />
            </span>
            <span className="text-[11px] font-semibold tracking-wide" style={{ color: '#007A99' }}>
              Free · No KYC · No Bank Details
            </span>
          </div>

          {/* Dashboard shortcut — only visible when session is still active */}
          {hasActiveSession && (
            <button
              onClick={() => navigate('/dashboard')}
              className="flex items-center gap-2 px-4 py-2 rounded-full text-[12px] font-bold mb-4 transition-all duration-200 hover:scale-[1.02] active:scale-[0.98]"
              style={{
                background: 'linear-gradient(135deg, #0F172A 0%, #1E3A5F 100%)',
                color: '#00D4FF',
                border: '1px solid rgba(0,212,255,0.25)',
                boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
              }}
            >
              <LayoutDashboard size={14} />
              Go to Dashboard
              <ArrowRight size={12} />
            </button>
          )}

          {/* Headline */}
          <div className="mb-5">
            <h1 className="text-[26px] font-black tracking-tight leading-tight mb-1.5" style={{ color: '#0F172A', fontFamily: 'var(--font-display)' }}>
              Create your account
            </h1>
            <p className="text-[13px]" style={{ color: '#475569' }}>
              Start with{" "}
              <span className="font-bold" style={{ color: '#0099CC' }}>₹10,00,000</span>{" "}
              virtual capital — free forever.
            </p>
          </div>

          {/* Glass card */}
          <div className="relative">
            <div
              className="absolute -inset-[1px] rounded-2xl pointer-events-none"
              style={{
                background:
                  "linear-gradient(135deg, rgba(14,165,233,0.12) 0%, rgba(226,232,240,0.4) 50%, rgba(30,111,168,0.06) 100%)",
              }}
            />
            <div
              className="relative rounded-2xl p-5"
              style={{
                background: "#FFFFFF",
                border: '1px solid #E2E8F0',
                boxShadow: '0 4px 24px rgba(0,0,0,0.06)',
              }}
            >
              {/* Google Sign Up */}
              <button
                type="button"
                onClick={handleGoogleSignUp}
                disabled={googleLoading}
                className="w-full flex items-center justify-center gap-3 py-3 rounded-xl text-[13px] font-bold border border-slate-200 hover:border-slate-300 bg-white hover:bg-slate-50 transition-all duration-200 active:scale-[0.98] disabled:opacity-50 mb-4"
                style={{ color: '#1E293B', borderColor: '#E2E8F0', boxShadow: '0 1px 3px rgba(0,0,0,0.08)' }}
              >
                {googleLoading ? (
                  <div className="w-4 h-4 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
                ) : (
                  <svg className="w-4 h-4" viewBox="0 0 24 24">
                    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
                    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                  </svg>
                )}
                {googleLoading ? "Signing up..." : "Continue with Google"}
              </button>

              {/* Divider */}
              <div className="flex items-center gap-3 mb-4">
                <div className="flex-1 h-px bg-slate-200" />
                <span className="text-[11px] text-slate-400 font-semibold uppercase tracking-widest">or</span>
                <div className="flex-1 h-px bg-slate-200" />
              </div>

              <form onSubmit={handleSubmit} className="space-y-3.5">
                {/* Name + Username row */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[10px] font-bold text-slate-800 mb-1.5 uppercase tracking-widest">
                      Full Name
                    </label>
                    <div className="relative group">
                      <User className="absolute left-3 top-1/2 -translate-y-1/2 w-[14px] h-[14px] text-slate-400 group-focus-within:text-[#00bcd4] transition-colors" />
                      <input
                        type="text"
                        value={formData.full_name}
                        onChange={set("full_name")}
                        placeholder="Full name"
                        required
                        className={`${fieldCls} ${fieldBg} pl-9 pr-3`}
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-[10px] font-bold text-slate-800 mb-1.5 uppercase tracking-widest">
                      Username
                    </label>
                    <div className="relative group">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[12px] text-slate-400 font-mono group-focus-within:text-[#00bcd4] transition-colors select-none">
                        @
                      </span>
                      <input
                        type="text"
                        value={formData.username}
                        onChange={set("username")}
                        placeholder="username"
                        required
                        className={`${fieldCls} ${fieldBg} pl-7 pr-3`}
                      />
                    </div>
                  </div>
                </div>

                {/* Email */}
                <div>
                  <label className="block text-[10px] font-bold text-slate-800 mb-1.5 uppercase tracking-widest">
                    Email Address
                  </label>
                  <div className="relative group">
                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-[14px] h-[14px] text-slate-400 group-focus-within:text-[#00bcd4] transition-colors" />
                    <input
                      type="email"
                      value={formData.email}
                      onChange={set("email")}
                      placeholder="you@example.com"
                      required
                      className={`${fieldCls} ${fieldBg} pl-9 pr-4`}
                    />
                  </div>
                </div>

                {/* Password */}
                <div>
                  <label className="block text-[10px] font-bold text-slate-800 mb-1.5 uppercase tracking-widest">
                    Password
                  </label>
                  <div className="relative group">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-[14px] h-[14px] text-slate-400 group-focus-within:text-[#00bcd4] transition-colors" />
                    <input
                      type={showPassword ? "text" : "password"}
                      value={formData.password}
                      onChange={set("password")}
                      placeholder="Min 6 characters"
                      required
                      minLength={6}
                      className={`${fieldCls} ${fieldBg} pl-9 pr-10`}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-500 transition-colors"
                    >
                      {showPassword ? (
                        <EyeOff className="w-4 h-4" />
                      ) : (
                        <Eye className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                  <StrengthBar password={formData.password} />
                </div>

                {/* CTA */}
                <div className="pt-1">
                  <button
                    type="submit"
                    disabled={loading}
                    className="relative w-full flex items-center justify-center gap-2.5 py-3.5 text-[13px] font-black overflow-hidden transition-all duration-200 active:scale-[0.97] disabled:opacity-50 group"
                    style={{
                      background: 'var(--gold)',
                      color: 'var(--navy)',
                      borderRadius: '999px',
                      boxShadow: "0 4px 20px rgba(14,165,233,0.30)",
                    }}
                  >
                    <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/12 to-transparent -translate-x-full group-hover:translate-x-full transition-transform duration-700 pointer-events-none" />
                    {loading ? (
                      <>
                        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        Creating account...
                      </>
                    ) : (
                      <>
                        Create Free Account{" "}
                        <ArrowRight size={16} className="group-hover:translate-x-0.5 transition-transform duration-150" />
                      </>
                    )}
                  </button>
                </div>
              </form>
            </div>
          </div>

          {/* Links */}
          <div className="mt-4 text-center space-y-2">
            <p className="text-[13px]" style={{ color: '#475569' }}>
              Already have an account?{" "}
              <Link
                to="/login"
                className="font-bold transition-colors"
                style={{ color: '#0099CC' }}
              >
                Sign In
              </Link>
            </p>
            <div className="flex items-center justify-center gap-1.5">
              <ShieldCheck size={14} className="text-emerald-500/60" />
              <span className="text-[11px]" style={{ color: '#64748B' }}>
                Free forever. No credit card required.
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
