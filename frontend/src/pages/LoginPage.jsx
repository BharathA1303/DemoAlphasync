// LoginPage.jsx — Combined Login + Register
import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuthStore } from "../stores/useAuthStore";
import toast from "react-hot-toast";
import usePageMeta from "../hooks/usePageMeta";
import { hasUserSessionCookie } from "../utils/authSessionCookie";

function PwdStrength({ password }) {
  if (!password) return null;
  const score = [
    password.length >= 8,
    /[A-Z]/.test(password),
    /[0-9]/.test(password),
    /[^A-Za-z0-9]/.test(password),
  ].filter(Boolean).length;
  const cls = score <= 1 ? "weak" : score <= 2 ? "medium" : "strong";
  return (
    <div className="pwd-strength">
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className={"pwd-bar" + (i <= score ? " " + cls : "")} />
      ))}
    </div>
  );
}

export default function LoginPage() {
  usePageMeta(
    "α·SIM Demo Trading — Login | AlphaSync",
    "Start paper trading for free. ₹10L virtual capital, live NSE/BSE data, zero risk."
  );

  const [tab, setTab] = useState("login");
  const [loginEmail, setLoginEmail]     = useState("");
  const [loginPass, setLoginPass]       = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [regFname, setRegFname]         = useState("");
  const [regLname, setRegLname]         = useState("");
  const [regEmail, setRegEmail]         = useState("");
  const [regPass, setRegPass]           = useState("");
  const [regAgree, setRegAgree]         = useState(false);
  const [regLoading, setRegLoading]     = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [showLoginPass, setShowLoginPass] = useState(false);
  const [showRegPass,   setShowRegPass]   = useState(false);

  const loginWithEmail     = useAuthStore((s) => s.loginWithEmail);
  const loginWithGoogle    = useAuthStore((s) => s.loginWithGoogle);
  const registerWithEmail  = useAuthStore((s) => s.registerWithEmail);
  const resendVerification = useAuthStore((s) => s.resendVerification);
  const existingUser       = useAuthStore((s) => s.user);
  const navigate           = useNavigate();
  const [searchParams]     = useSearchParams();
  const adminIntent        = (searchParams.get("intent") || "").toLowerCase() === "admin";

  const routeByAccountStatus = (profile) => {
    const status   = (profile?.account_status || "active").toLowerCase();
    const isActive = status === "active" && profile?.is_active !== false;
    if (isActive) {
      if (adminIntent) {
        if ((profile?.role || "").toLowerCase() === "admin") {
          navigate("/admin/panel");
        } else {
          toast.error(`Signed in as ${profile?.email || "this account"}, but it is not an admin account.`);
          navigate("/admin");
        }
        return;
      }
      localStorage.setItem("alphasync_trading_mode", "demo");
      localStorage.setItem("alphasync_onboarded", "1");
      navigate("/dashboard");
    } else {
      navigate("/account-status");
    }
  };

  const hasPhone = (profile) => {
    if ((profile?.role || "").toLowerCase() === "admin") return true;
    return Boolean(profile?.phone);
  };

  const handleAuthSuccess = (profile) => {
    if (!hasPhone(profile)) { navigate("/collect-phone"); return; }
    routeByAccountStatus(profile);
  };

  useEffect(() => {
    if (!existingUser || adminIntent) return;
    if (!hasUserSessionCookie()) return;
    handleAuthSuccess(existingUser);
  }, [existingUser, adminIntent]);

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoginLoading(true);
    try {
      const result = await loginWithEmail(loginEmail, loginPass);
      if ((result?.user?.account_status || "active") !== "active") {
        toast("Login successful. Your account is pending review.");
      } else {
        toast.success("Welcome back!");
      }
      handleAuthSuccess(result?.user);
    } catch (err) {
      const code = err.code;
      if (code === "auth/email-not-verified") {
        try { await resendVerification(loginEmail, loginPass); toast.error("Email not verified. We sent a new verification link."); }
        catch  { toast.error("Email not verified. Check your inbox."); }
        navigate("/verify-email", { state: { email: loginEmail, password: loginPass } });
        return;
      } else if (code === "auth/user-not-found" || code === "auth/wrong-password" || code === "auth/invalid-credential") {
        toast.error("Invalid email or password");
      } else if (code === "auth/too-many-requests") {
        toast.error("Too many attempts. Try again later.");
      } else {
        toast.error(err.message || "Login failed");
      }
    } finally { setLoginLoading(false); }
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    if (regPass.length < 6) return toast.error("Password must be at least 6 characters");
    setRegLoading(true);
    try {
      const fullName = (regFname + " " + regLname).trim();
      const result   = await registerWithEmail(regEmail, regPass, fullName, "");
      if (result.needsVerification) {
        navigate("/verify-email", { state: { email: regEmail, password: regPass } });
      } else {
        localStorage.setItem("alphasync_trading_mode", "demo");
        localStorage.setItem("alphasync_onboarded", "1");
        navigate("/dashboard");
      }
    } catch (err) {
      const code = err.code;
      if (code === "auth/email-already-in-use") toast.error("Email already registered. Try signing in.");
      else if (code === "auth/weak-password")   toast.error("Password is too weak.");
      else toast.error(err.message || "Registration failed");
    } finally { setRegLoading(false); }
  };

  const handleGoogleLogin = async () => {
    setGoogleLoading(true);
    try {
      const result = await loginWithGoogle("login");
      const email  = result?.user?.email || "selected Google account";
      if ((result?.user?.account_status || "active") !== "active") {
        toast(`Signed in as ${email}. Your account is under review.`);
      } else {
        toast.success(`Welcome back, ${email}!`);
      }
      handleAuthSuccess(result?.user);
    } catch (err) {
      if (err.response?.status === 404) { toast.error("Account not found. Please create an account first."); setTab("register"); return; }
      if (err.code !== "auth/popup-closed-by-user") toast.error(err.message || "Google sign-in failed");
    } finally { setGoogleLoading(false); }
  };

  const handleGoogleRegister = async () => {
    setGoogleLoading(true);
    try {
      const result = await loginWithGoogle("register");
      const email  = result?.user?.email || "selected Google account";
      if ((result?.user?.account_status || "active") !== "active") {
        toast.success(`Registered as ${email}. Account pending approval.`);
      } else {
        toast.success(result.isNew ? `Welcome to AlphaSync, ${email}!` : `Welcome back, ${email}!`);
      }
      handleAuthSuccess(result?.user);
    } catch (err) {
      if (err.code !== "auth/popup-closed-by-user") toast.error(err.message || "Google sign-up failed");
    } finally { setGoogleLoading(false); }
  };

  const handleForgotPassword = async () => {
    if (!loginEmail) return toast.error("Enter your email first");
    try {
      const { resetPassword } = useAuthStore.getState();
      await resetPassword(loginEmail);
      toast.success("Password reset email sent!");
    } catch { toast.error("Could not send reset email."); }
  };

  return (
    <div className="lp-shell">
      <style dangerouslySetInnerHTML={{ __html: LP_STYLES }} />

      {/* ═══════════════════════════════════════════════
          LEFT — FULL BLEED dark navy (no margin/radius)
          ═══════════════════════════════════════════════ */}
      <div className="lp-left">

        <div className="lp-glow lp-glow-tr" />
        <div className="lp-glow lp-glow-bl" />

        {/* candlestick chart bg */}
        <div className="lp-chart" aria-hidden>
          <svg viewBox="0 0 640 520" preserveAspectRatio="xMidYMid slice" width="100%" height="100%">
            <defs>
              <linearGradient id="lpGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stopColor="#00B67A" stopOpacity="0.35" />
                <stop offset="100%" stopColor="#00B67A" stopOpacity="0"    />
              </linearGradient>
            </defs>
            <polygon
              points="0,460 60,418 115,394 170,410 220,368 275,342 325,295 378,316 425,268 478,248 525,206 572,182 610,158 640,138 640,520 0,520"
              fill="url(#lpGrad)"
            />
            <polyline
              points="0,460 60,418 115,394 170,410 220,368 275,342 325,295 378,316 425,268 478,248 525,206 572,182 610,158 640,138"
              fill="none" stroke="#00B67A" strokeWidth="1.8"
              strokeLinecap="round" strokeLinejoin="round"
            />
            <line x1="60"  y1="406" x2="60"  y2="430" stroke="#00B67A" strokeWidth="1.5"/><rect x="52"  y="410" width="16" height="16" fill="#00B67A" rx="2"/>
            <line x1="275" y1="330" x2="275" y2="356" stroke="#00B67A" strokeWidth="1.5"/><rect x="267" y="334" width="16" height="17" fill="#00B67A" rx="2"/>
            <line x1="425" y1="256" x2="425" y2="280" stroke="#00B67A" strokeWidth="1.5"/><rect x="417" y="260" width="16" height="17" fill="#00B67A" rx="2"/>
            <line x1="525" y1="194" x2="525" y2="218" stroke="#00B67A" strokeWidth="1.5"/><rect x="517" y="198" width="16" height="18" fill="#00B67A" rx="2"/>
            <line x1="610" y1="146" x2="610" y2="168" stroke="#00B67A" strokeWidth="1.5"/><rect x="602" y="150" width="16" height="16" fill="#00B67A" rx="2"/>
            <line x1="170" y1="398" x2="170" y2="424" stroke="#F87171" strokeWidth="1.5"/><rect x="162" y="403" width="16" height="18" fill="#F87171" rx="2"/>
            <line x1="378" y1="303" x2="378" y2="328" stroke="#F87171" strokeWidth="1.5"/><rect x="370" y="308" width="16" height="16" fill="#F87171" rx="2"/>
            <line x1="478" y1="236" x2="478" y2="260" stroke="#F87171" strokeWidth="1.5"/><rect x="470" y="241" width="16" height="14" fill="#F87171" rx="2"/>
          </svg>
        </div>

        {/* ── Logo: white-logo.png + WHITE "AlphaSync" text ── */}
        <div className="lp-logo">
          <img src="/white-logo.png" alt="AlphaSync" className="lp-logo-icon" />
          <span className="lp-logo-name">AlphaSync</span>
          <span className="lp-logo-badge">{"α·SIM"}</span>
        </div>

        {/* ── Hero ── */}
        <div className="lp-hero">


          <h1>
            Trade the market.<br />
            <span className="lp-accent-txt">Risk absolutely nothing.</span>
          </h1>

          <p className="lp-sub">
            Practice with {"₹"}10 Lakh of virtual capital on live NSE &amp; BSE data.
            No real money, no risk — just pure trading experience.
          </p>

          {/* Features — NO rectangular box overlays */}
          <div className="lp-feats">

            <div className="lp-feat">
              <div className="lp-icon lp-icon-a"><i className="fa fa-chart-line"></i></div>
              <div className="lp-feat-txt">
                <strong>Live Market Data</strong>
                <span>Real-time NSE &amp; BSE prices — same data as professional traders</span>
              </div>
            </div>

            <div className="lp-feat">
              <div className="lp-icon lp-icon-b"><i className="fa fa-shield-halved"></i></div>
              <div className="lp-feat-txt">
                <strong>Zero Broker Setup</strong>
                <span>No API keys, no brokerage account needed to get started</span>
              </div>
            </div>

            <div className="lp-feat">
              <div className="lp-icon lp-icon-c"><i className="fa fa-chart-pie"></i></div>
              <div className="lp-feat-txt">
                <strong>Full Analytics Dashboard</strong>
                <span>P&amp;L tracking, position sizing, risk metrics &amp; strategy reports</span>
              </div>
            </div>

          </div>

          {/* Virtual capital */}
          <div className="lp-capital">
            <div>
              <div className="lp-cap-lbl">Starting Virtual Capital</div>
              <div className="lp-cap-amt">{"₹"}10,00,000</div>
            </div>
            <button className="lp-cap-btn" type="button">
              <i className="fa fa-rotate"></i> Reset anytime
            </button>
          </div>

        </div>

        {/* ── Trust strip ── */}
        <div className="lp-trust">
          <span><i className="fa fa-circle-check"></i>100% Virtual Trading</span>
          <span><i className="fa fa-chart-line"></i>Live Market Data</span>
          <span><i className="fa fa-shield-halved"></i>Secure &amp; Private</span>
          <span><i className="fa fa-circle-info"></i>No Hidden Charges</span>
        </div>

      </div>

      {/* ═══════════════════════════════════════════════
          RIGHT — pure white
          ═══════════════════════════════════════════════ */}
      <div className="lp-right">

        <div className="lp-nav">
          <a href="/login" className="lpn-active">Live Trading</a>
          <a href="/admin" className="lpn-muted">Admin Panel</a>
        </div>

        <div className="lp-form-area">
          <div className="lp-card">

            <div className="lp-card-head">
              <h2>{tab === "login" ? "Welcome back 👋" : "Start trading free 🚀"}</h2>
              <p>
                {tab === "login"
                  ? <>Login to your {"α·SIM"} demo account</>
                  : <>Create your {"α·SIM"} account — takes 30 seconds</>}
              </p>
            </div>

            <div className="lp-tabs" role="tablist">
              <button
                className={"lp-tab" + (tab === "login"    ? " active" : "")}
                onClick={() => setTab("login")} type="button" role="tab"
              >Login</button>
              <button
                className={"lp-tab" + (tab === "register" ? " active" : "")}
                onClick={() => setTab("register")} type="button" role="tab"
              >Create Account</button>
            </div>

            {/* LOGIN */}
            <div className={"lp-panel" + (tab === "login" ? " active" : "")}>
              <form onSubmit={handleLogin}>

                <div className="lp-field">
                  <label>Email Address</label>
                  <div className="lp-inp">
                    <i className="lp-ico fa fa-envelope"></i>
                    <input type="email" placeholder="you@email.com" required
                      autoComplete="email" value={loginEmail}
                      onChange={(e) => setLoginEmail(e.target.value)} />
                  </div>
                </div>

                <div className="lp-field">
                  <label>Password</label>
                  <div className="lp-inp">
                    <i className="lp-ico fa fa-lock"></i>
                    <input
                      type={showLoginPass ? "text" : "password"}
                      placeholder="••••••••" required autoComplete="current-password"
                      value={loginPass} onChange={(e) => setLoginPass(e.target.value)}
                    />
                    <i className={"lp-eye fa " + (showLoginPass ? "fa-eye-slash" : "fa-eye")}
                       onClick={() => setShowLoginPass(!showLoginPass)} />
                  </div>
                </div>

                <div className="lp-row">
                  <label className="lp-check">
                    <input type="checkbox" /> Remember me
                  </label>
                  <a href="#forgot" className="lp-forgot"
                     onClick={(e) => { e.preventDefault(); handleForgotPassword(); }}>
                    Forgot password?
                  </a>
                </div>

                <button type="submit" className="lp-btn-primary" disabled={loginLoading}>
                  {loginLoading
                    ? <><i className="fa fa-spinner fa-spin"></i>&nbsp; Signing in…</>
                    : <><i className="fa fa-lock"></i>&nbsp; Enter {"α·SIM"} Dashboard</>}
                </button>

              </form>

              <div className="lp-or">or continue with</div>

              <button className="lp-btn-google" onClick={handleGoogleLogin}
                      disabled={googleLoading} type="button">
                <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg"
                     alt="Google" width="20" height="20" />
                {googleLoading ? "Signing in…" : "Continue with Google"}
              </button>

              <p className="lp-terms">
                By logging in, you agree to our{" "}
                <a href="/terms">Terms &amp; Privacy Policy</a>
              </p>
            </div>

            {/* REGISTER */}
            <div className={"lp-panel" + (tab === "register" ? " active" : "")}>
              <form onSubmit={handleRegister}>

                <div className="lp-field-row">
                  <div className="lp-field">
                    <label>First Name</label>
                    <div className="lp-inp">
                      <i className="lp-ico fa fa-user"></i>
                      <input type="text" placeholder="First name" required autoComplete="given-name"
                        value={regFname} onChange={(e) => setRegFname(e.target.value)} />
                    </div>
                  </div>
                  <div className="lp-field">
                    <label>Last Name</label>
                    <div className="lp-inp">
                      <i className="lp-ico fa fa-user"></i>
                      <input type="text" placeholder="Last name" required autoComplete="family-name"
                        value={regLname} onChange={(e) => setRegLname(e.target.value)} />
                    </div>
                  </div>
                </div>

                <div className="lp-field">
                  <label>Email Address</label>
                  <div className="lp-inp">
                    <i className="lp-ico fa fa-envelope"></i>
                    <input type="email" placeholder="you@email.com" required autoComplete="email"
                      value={regEmail} onChange={(e) => setRegEmail(e.target.value)} />
                  </div>
                </div>

                <div className="lp-field">
                  <label>Create Password</label>
                  <div className="lp-inp">
                    <i className="lp-ico fa fa-lock"></i>
                    <input
                      type={showRegPass ? "text" : "password"}
                      placeholder="Min 8 characters" required autoComplete="new-password"
                      value={regPass} onChange={(e) => setRegPass(e.target.value)}
                    />
                    <i className={"lp-eye fa " + (showRegPass ? "fa-eye-slash" : "fa-eye")}
                       onClick={() => setShowRegPass(!showRegPass)} />
                  </div>
                  <PwdStrength password={regPass} />
                </div>

                <div className="lp-field" style={{ marginBottom:"1.125rem" }}>
                  <label style={{ display:"flex", alignItems:"flex-start", gap:".5rem",
                                  cursor:"pointer", fontSize:".9375rem", color:"#64748B", fontWeight:400 }}>
                    <input type="checkbox" required checked={regAgree}
                           onChange={(e) => setRegAgree(e.target.checked)}
                           style={{ marginTop:"3px", flexShrink:0, accentColor:"#00B67A" }} />
                    <span>
                      I agree to the{" "}<a href="/terms" className="lp-link">Terms of Service</a>
                      {" "}and{" "}<a href="/privacy" className="lp-link">Privacy Policy</a>
                    </span>
                  </label>
                </div>

                <button type="submit" className="lp-btn-primary" disabled={regLoading}>
                  {regLoading
                    ? <><i className="fa fa-spinner fa-spin"></i>&nbsp; Creating account…</>
                    : <><i className="fa fa-rocket"></i>&nbsp; Create Free Account &amp; Start Trading</>}
                </button>

              </form>

              <div className="lp-or">or sign up with</div>

              <button className="lp-btn-google" onClick={handleGoogleRegister}
                      disabled={googleLoading} type="button">
                <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg"
                     alt="Google" width="20" height="20" />
                {googleLoading ? "Signing up…" : "Sign up with Google"}
              </button>
            </div>

          </div>
        </div>
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════
   LP_STYLES
   ════════════════════════════════════════════════════════════ */
const LP_STYLES = `

  .lp-shell *, .lp-shell *::before, .lp-shell *::after { box-sizing: border-box; }

  .lp-shell {
    --accent:    #00B67A;
    --accent-dk: #009B68;
    --green-lt:  #6EE7B7;
    --green-md:  #34D399;
    --r-sm: 10px; --r-md: 14px; --r-lg: 18px; --r-xl: 22px; --r-pill: 999px;
    --f-sans:    'Inter', -apple-system, system-ui, sans-serif;
    --f-display: 'Manrope', 'Inter', system-ui, sans-serif;
    --f-mono:    'JetBrains Mono', 'SF Mono', 'Menlo', monospace;
    --ease: all 0.2s cubic-bezier(0.4,0,0.2,1);

    display: grid;
    grid-template-columns: 55fr 45fr;
    height: 100vh;
    height: 100dvh;
    overflow: hidden;
    background: #060D1A;
    font-family: var(--f-sans);
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  /* ══════════════════════════════════════════════════════
     LEFT — FULL BLEED (zero margin, zero border-radius)
     ══════════════════════════════════════════════════════ */
  .lp-left {
    background: linear-gradient(155deg, #060D1A 0%, #08152A 52%, #0A1B32 100%);
    display: flex;
    flex-direction: column;
    padding: 2rem 2.75rem;
    position: relative;
    overflow: hidden;
    scrollbar-width: none; /* Firefox */
  }
  .lp-left::-webkit-scrollbar { display: none; } /* Chrome/Safari */

  .lp-glow { position: absolute; border-radius: 50%; pointer-events: none; z-index: 0; }
  .lp-glow-tr {
    width: 640px; height: 640px;
    background: radial-gradient(circle, rgba(20,90,195,0.13) 0%, transparent 62%);
    top: -230px; right: -180px;
  }
  .lp-glow-bl {
    width: 480px; height: 480px;
    background: radial-gradient(circle, rgba(0,155,185,0.09) 0%, transparent 65%);
    bottom: -150px; left: -110px;
    animation: lpGlow 9s ease-in-out infinite;
  }
  @keyframes lpGlow { 0%,100%{transform:scale(1);opacity:.75} 50%{transform:scale(1.08);opacity:1} }

  .lp-chart {
    position: absolute; inset: 0;
    opacity: 0.11; pointer-events: none; overflow: hidden;
  }

  /* ── Logo ─────────────────────────────────────────── */
  .lp-logo {
    display: flex; align-items: center; gap: .9rem;
    flex-shrink: 0; position: relative; z-index: 2;
  }
  .lp-logo-icon {
    height: 48px; width: 48px; object-fit: contain;
  }
  .lp-logo-name {
    color: #FFFFFF;
    font-size: 1.625rem;
    font-weight: 700;
    font-family: var(--f-display);
    letter-spacing: -.02em;
    line-height: 1;
  }
  .lp-logo-badge {
    font-size: .72rem; font-weight: 700;
    background: rgba(0,182,122,0.1);
    color: #00B67A;
    border: 1px solid rgba(0,182,122,0.3);
    padding: .2rem .65rem;
    border-radius: var(--r-pill);
    letter-spacing: .05em;
  }

  /* ── Hero ──────────────────────────────────────────── */
  .lp-hero {
    flex: 1; display: flex; flex-direction: column;
    justify-content: center;
    position: relative; z-index: 2;
    padding: 1.25rem 0 .75rem;
  }

  .lp-pill {
    display: inline-flex; align-items: center; gap: .4rem;
    background: rgba(0,182,122,0.08);
    border: 1px solid rgba(0,182,122,0.2);
    color: #00B67A;
    font-size: .8rem; font-weight: 700; letter-spacing: .08em;
    padding: .4rem 1.1rem; border-radius: var(--r-pill);
    margin-bottom: 2rem; width: fit-content;
  }

  .lp-left h1 {
    font-size: clamp(1.875rem, 3vw, 2.75rem);
    line-height: 1.2; letter-spacing: -.75px;
    font-weight: 800; font-family: var(--f-display);
    color: #FFFFFF; margin: 0 0 1rem;
  }
  .lp-accent-txt { color: #00B67A; }

  .lp-sub {
    font-size: .975rem;
    color: rgba(255,255,255,0.7); line-height: 1.7;
    max-width: 520px; margin-bottom: 1.75rem;
  }

  /* Features — CLEAN rows, zero box overlays */
  .lp-feats { display: flex; flex-direction: column; gap: 1rem; margin-bottom: 1.75rem; }

  .lp-feat {
    display: flex; align-items: center; gap: 1.1rem;
    padding: .15rem 0;
  }

  .lp-icon {
    width: 46px; height: 46px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 1rem; flex-shrink: 0;
    background: rgba(0, 182, 122, 0.08);
    border: 1px solid rgba(0, 182, 122, 0.2);
    color: #00B67A;
  }

  .lp-feat-txt { line-height: 1.4; }
  .lp-feat-txt strong {
    display: block; color: #FFFFFF;
    font-size: .95rem; font-weight: 600; margin-bottom: .2rem;
  }
  .lp-feat-txt span { display: block; color: rgba(255,255,255,0.65); font-size: .84rem; }

  /* Capital card */
  .lp-capital {
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 1.25rem 1.625rem;
    display: flex; align-items: center;
    justify-content: space-between; gap: .75rem;
    width: 100%; max-width: 600px;
  }
  .lp-cap-lbl {
    font-size: .75rem; font-weight: 600;
    color: rgba(255,255,255,0.4);
    text-transform: uppercase; letter-spacing: .08em; margin-bottom: .4rem;
  }
  .lp-cap-amt {
    font-size: clamp(1.625rem, 2.5vw, 2.125rem);
    font-weight: 700; color: #00B67A;
    font-family: var(--f-mono); letter-spacing: -.02em; line-height: 1;
  }
  .lp-cap-btn {
    display: inline-flex; align-items: center; gap: .4rem;
    font-size: .8rem; font-weight: 500;
    background: transparent; color: #94A3B8;
    border: 1px solid rgba(255,255,255,0.15);
    padding: .5rem 1rem; border-radius: var(--r-pill);
    cursor: pointer; font-family: var(--f-sans);
    transition: var(--ease); white-space: nowrap;
  }
  .lp-cap-btn:hover { border-color: rgba(255,255,255,0.25); background: rgba(255,255,255,0.04); }

  /* Trust */
  .lp-trust {
    display: flex; align-items: center;
    justify-content: space-between; gap: .5rem;
    padding-top: 1.25rem;
    flex-shrink: 0; position: relative; z-index: 2;
  }
  .lp-trust span {
    display: inline-flex; align-items: center; justify-content: center; gap: .45rem;
    font-size: .82rem; font-weight: 500;
    color: rgba(255,255,255,0.65); white-space: nowrap;
    flex: 1;
  }
  .lp-trust span i { font-size: .9rem; color: #FFFFFF; }

  /* ══════════════════════════════════════════════════════
     RIGHT — pure white
     ══════════════════════════════════════════════════════ */
  .lp-right {
    background: #F8FAFC;
    display: flex; flex-direction: column; overflow: hidden;
    position: relative;
  }

  /* Nav is a static top row — NOT absolute, so it never overlaps the card */
  .lp-nav {
    display: flex; align-items: center; justify-content: flex-end;
    gap: 1.5rem;
    padding: 1.5rem 2.5rem .75rem;
    flex-shrink: 0;
    z-index: 10;
  }
  .lp-nav a { font-size: .9rem; font-weight: 500; text-decoration: none; transition: color .18s; }
  .lpn-back   { color: #94A3B8; }
  .lpn-back:hover { color: #64748B; }
  .lpn-active { color: #00B67A !important; font-weight: 600; }
  .lpn-active:hover { color: #009B68 !important; }
  .lpn-muted  { color: #94A3B8; }
  .lpn-muted:hover { color: #64748B; }

  .lp-form-area {
    flex: 1; display: flex;
    align-items: center; justify-content: center;
    padding: 1rem 2rem 2rem;
    overflow-y: auto;
    scrollbar-width: none;
  }
  .lp-form-area::-webkit-scrollbar { display: none; }

  /* ── Card ────────────────── */
  .lp-card {
    width: 100%; max-width: 480px;
    background: #FFFFFF;
    border-radius: 20px;
    padding: 2rem 2.5rem 1.75rem;
    border: 1.5px solid #E2E8F0;
    box-shadow:
      0 20px 40px rgba(15,23,42,0.04),
      0 4px 12px rgba(15,23,42,0.02);
  }

  .lp-card-head { text-align: center; margin-bottom: 1rem; }
  .lp-card-head h2 {
    font-size: 2rem; font-weight: 700;
    font-family: var(--f-display); color: #0F172A;
    letter-spacing: -.5px; margin: 0 0 .5rem; line-height: 1.15;
  }
  .lp-card-head p { font-size: 1.05rem; color: #64748B; line-height: 1.5; }

  /* Tabs */
  .lp-tabs {
    display: grid; grid-template-columns: 1fr 1fr;
    border: 1px solid #E2E8F0; border-radius: 14px;
    background: #F1F5F9;
    padding: 5px;
    margin-bottom: 1rem;
    gap: 5px;
  }
  .lp-tab {
    padding: .75rem 1rem; text-align: center;
    font-size: .95rem; font-weight: 600; color: #64748B;
    background: transparent; border: 2px solid transparent; cursor: pointer;
    font-family: var(--f-sans);
    border-radius: 10px;
    transition: all 0.2s ease;
    outline: none;
  }
  .lp-tab.active {
    background: #FFFFFF;
    color: #00B67A;
    border: 2px solid transparent;
    border-bottom: 2.5px solid #00B67A;
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
  }
  .lp-tab:not(.active):hover { color: #0F172A; }

  /* Fields */
  .lp-field { margin-bottom: 0.875rem; }
  .lp-field-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }

  .lp-field > label {
    display: block; font-size: .95rem; font-weight: 600;
    color: #1E293B; margin-bottom: .5rem; letter-spacing: .01em;
  }
  .lp-inp { position: relative; }
  .lp-ico {
    position: absolute; left: 1.25rem; top: 50%;
    transform: translateY(-50%);
    color: #64748B; font-size: 1rem; pointer-events: none;
  }
  .lp-inp input {
    width: 100%; height: 50px;
    background: #FFFFFF; border: 1.5px solid #E2E8F0;
    border-radius: 12px;
    padding: 0 1rem 0 3.25rem;
    color: #0F172A; font-size: .95rem;
    font-family: var(--f-sans); outline: none; transition: var(--ease);
  }
  .lp-inp input::placeholder { color: #94A3B8; }
  .lp-inp input:focus {
    border-color: #00B67A;
    box-shadow: 0 0 0 4px rgba(0,182,122,0.08);
    background: #FFFFFF;
  }
  .lp-eye {
    position: absolute; right: 1.25rem; top: 50%;
    transform: translateY(-50%);
    color: #64748B; cursor: pointer; font-size: 1.05rem; transition: color .18s;
  }
  .lp-eye:hover { color: #00B67A; }

  .lp-row {
    display: flex; align-items: center;
    justify-content: space-between; margin-bottom: 1.25rem;
  }
  .lp-check {
    display: flex; align-items: center; gap: .5rem;
    font-size: .95rem; color: #64748B; cursor: pointer;
    user-select: none;
  }
  .lp-check input[type="checkbox"] {
    accent-color: #00B67A;
    width: 16px; height: 16px;
    cursor: pointer;
  }
  .lp-forgot {
    font-size: .95rem; color: #00B67A;
    text-decoration: none; font-weight: 600; transition: color .18s;
  }
  .lp-forgot:hover { color: #009B68; text-decoration: underline; }

  /* Primary button */
  .lp-btn-primary {
    width: 100%; height: 50px;
    border-radius: 12px;
    background: linear-gradient(90deg, #00B67A 0%, #009E6A 100%);
    color: #FFFFFF; font-size: 1rem; font-weight: 600;
    font-family: var(--f-sans); border: none; cursor: pointer;
    display: flex; align-items: center; justify-content: center; gap: .5rem;
    margin-bottom: 1rem;
    box-shadow: 0 10px 25px rgba(0, 182, 122, 0.15);
    letter-spacing: .01em; transition: var(--ease);
  }
  .lp-btn-primary:hover  { transform: translateY(-1px); box-shadow: 0 12px 30px rgba(0,182,122,0.35); }
  .lp-btn-primary:active { transform: translateY(0);    box-shadow: 0 6px 16px rgba(0,182,122,0.2); }
  .lp-btn-primary:disabled { opacity:.6; cursor:not-allowed; transform:none; box-shadow:none; }

  .lp-or {
    display: flex; align-items: center; gap: 1rem;
    margin: 1rem 0;
    color: #94A3B8; font-size: .9rem; font-weight: 500;
  }
  .lp-or::before,.lp-or::after { content:''; flex:1; height:1px; background:#E2E8F0; }

  .lp-btn-google {
    width: 100%; height: 50px;
    border-radius: 12px; background: #FFFFFF;
    border: 1.5px solid #E2E8F0; color: #0F172A;
    font-size: .95rem; font-weight: 600;
    font-family: var(--f-sans); cursor: pointer;
    display: flex; align-items: center; justify-content: center; gap: .7rem;
    margin-bottom: 1rem; transition: var(--ease);
  }
  .lp-btn-google:hover { background: #F8FAFC; border-color: #CBD5E1; transform: translateY(-1px); }
  .lp-btn-google:disabled { opacity:.6; cursor:not-allowed; }

  .lp-terms {
    font-size: .9rem; color: #64748B;
    text-align: center; line-height: 1.6;
    margin-top: 1rem;
  }
  .lp-terms a { color: #00B67A; font-weight: 600; text-decoration: none; }
  .lp-terms a:hover { color: #009B68; text-decoration: underline; }

  .lp-link { color: #00B67A; font-weight: 600; text-decoration: none; }
  .lp-link:hover { color: #009B68; text-decoration: underline; }

  .lp-switch {
    margin-top: 1rem; padding-top: 0.875rem;
    border-top: 1px solid #E2E8F0;
    text-align: center; font-size: .95rem; color: #64748B;
  }
  .lp-switch a {
    color: #00B67A; font-weight: 600; text-decoration: none;
    display: inline-flex; align-items: center; gap: .3rem;
    transition: gap .18s, color .18s;
  }
  .lp-switch a:hover { color: #009B68; gap: .45rem; }

  .lp-panel { display: none; }
  .lp-panel.active { display: block; }

  .pwd-strength { margin-top:.375rem; display:flex; gap:4px; }
  .pwd-bar { flex:1; height:3px; border-radius:2px; background:#E8EDF5; transition:background .3s; }
  .pwd-bar.weak   { background:#EF4444; }
  .pwd-bar.medium { background:#F59E0B; }
  .pwd-bar.strong { background:#00B67A; }

  /* ══════════════════════════════════════════════════════
     RESPONSIVE
     ══════════════════════════════════════════════════════ */
  @media (min-width: 1440px) {
    .lp-left      { padding: 2.25rem 3.25rem; }
    .lp-nav       { padding: 2rem 3rem 1rem; }
    .lp-form-area { padding: 1rem 2.5rem 2.5rem; }
    .lp-card      { max-width: 480px; padding: 2rem 2.5rem 2rem; }
    .lp-card-head h2 { font-size: 2.125rem; }
    .lp-capital   { max-width: 640px; }
  }

  @media (max-width: 1280px) and (min-width: 901px) {
    .lp-left      { padding: 1.75rem 2.25rem; }
    .lp-nav       { padding: 1.25rem 2rem .5rem; gap: 1.25rem; }
    .lp-form-area { padding: .75rem 1.5rem 1.75rem; }
    .lp-card      { max-width: 460px; padding: 1.75rem 2.25rem 1.5rem; }
    .lp-capital   { max-width: 520px; }
    .lp-left h1   { font-size: clamp(1.625rem, 3.5vw, 2.5rem); }
    .lp-card-head h2 { font-size: 1.75rem; }
  }

  @media (max-width: 900px) {
    .lp-shell     { grid-template-columns: 1fr; }
    .lp-left      { display: none; }
    .lp-right     { height: 100dvh; }
    .lp-nav       { justify-content: center; padding: 1.25rem 1.5rem .5rem; gap: 1.25rem; }
    .lp-form-area { padding: .5rem 1.5rem 2.5rem; align-items: flex-start; overflow-y: auto; }
    .lp-card      { max-width: 520px; margin: 0 auto; box-shadow: 0 10px 30px rgba(15,23,42,0.04); }
  }

  @media (max-width: 680px) {
    .lp-nav a     { font-size: .85rem; }
    .lp-nav       { gap: 1rem; padding: 0 1.25rem; }
    .lp-form-area { padding: 0 1.25rem 2rem; }
    .lp-card      { padding: 2.25rem 2.5rem 2rem; border-radius: 16px; }
    .lp-card-head h2 { font-size: 1.75rem; }
    .lp-inp input { height: 54px; }
    .lp-btn-primary { height: 54px; }
    .lp-btn-google  { height: 54px; }
  }

  @media (max-width: 480px) {
    .lp-nav       { padding: 0 1rem; gap: 1rem; margin: 1.25rem auto .75rem; }
    .lp-nav a     { font-size: .8rem; }
    .lp-form-area { padding: 0 1rem 2rem; overflow-y: auto; }
    .lp-card      { max-width: 100%; padding: 1.75rem 1.25rem; box-shadow: none; border: none; background: transparent; }
    .lp-card-head h2 { font-size: 1.5rem; }
    .lp-card-head p  { font-size: .95rem; }
    .lp-tabs      { margin-bottom: 1.5rem; }
    .lp-tab       { padding: .8rem .5rem; font-size: .9rem; }
    .lp-field-row { grid-template-columns: 1fr; gap: 0; }
    .lp-field     { margin-bottom: 1.125rem; }
    .lp-field > label { font-size: .9rem; }
    .lp-inp input { height: 52px; font-size: .9rem; }
    .lp-btn-primary { height: 52px; font-size: .95rem; }
    .lp-btn-google  { height: 52px; font-size: .95rem; }
    .lp-row       { margin-bottom: 1.25rem; }
    .lp-check, .lp-forgot { font-size: .9rem; }
    .lp-terms     { font-size: .85rem; }
    .lp-switch    { font-size: .9rem; }
  }

  @media (max-height: 600px) and (orientation: landscape) {
    .lp-shell    { height: auto; min-height: 100dvh; grid-template-columns: 1fr; overflow-y: auto; }
    .lp-left     { display: none; }
    .lp-right    { height: auto; min-height: 100dvh; }
    .lp-form-area{ overflow-y: visible; }
  }
`;
