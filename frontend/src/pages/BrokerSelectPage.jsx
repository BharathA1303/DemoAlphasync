import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import { useBrokerStore } from "../stores/useBrokerStore";
import { useAuthStore } from "../stores/useAuthStore";
import { ArrowRight, ShieldCheck, Check, LogOut, Lock, Zap, RefreshCw } from "lucide-react";
import { BROKERS } from "../components/broker/brokerMeta";
import AddBrokerAccountModal from "../components/broker/AddBrokerAccountModal";
import BrokerLogo from "../components/broker/BrokerLogo";

/* ═══════════════════════════════════════════════════════════════
   STYLES — bp-* namespace, self-contained
   ═══════════════════════════════════════════════════════════════ */
const BP_STYLES = `
  .bp-shell *, .bp-shell *::before, .bp-shell *::after { box-sizing: border-box; }

  .bp-shell {
    --accent:    #00B67A;
    --accent-dk: #009B68;
    --green-lt:  #6EE7B7;
    --f-sans:    'Inter', -apple-system, system-ui, sans-serif;
    --f-display: 'Manrope', 'Inter', system-ui, sans-serif;
    --ease: all 0.2s cubic-bezier(0.4,0,0.2,1);

    display: grid;
    grid-template-columns: 45fr 55fr;
    height: 100vh;
    height: 100dvh;
    overflow: hidden;
    font-family: var(--f-sans);
    -webkit-font-smoothing: antialiased;
  }

  /* ── LEFT PANEL ──────────────────────────────────────────────── */
  .bp-left {
    background: linear-gradient(155deg, #060D1A 0%, #08152A 52%, #0A1B32 100%);
    display: flex;
    flex-direction: column;
    padding: 2.5rem 3rem;
    position: relative;
    overflow: hidden;
  }

  /* ambient glow orbs */
  .bp-left::before {
    content: '';
    position: absolute;
    width: 480px; height: 480px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(0,182,122,0.10) 0%, transparent 65%);
    top: -140px; right: -100px;
    pointer-events: none;
  }
  .bp-left::after {
    content: '';
    position: absolute;
    width: 360px; height: 360px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(0,155,185,0.07) 0%, transparent 65%);
    bottom: -100px; left: -80px;
    pointer-events: none;
    animation: bpGlow 9s ease-in-out infinite;
  }
  @keyframes bpGlow { 0%,100%{transform:scale(1);opacity:.7} 50%{transform:scale(1.08);opacity:1} }

  /* candlestick watermark */
  .bp-chart-bg {
    position: absolute; inset: 0;
    opacity: 0.09; pointer-events: none;
  }

  /* Logo */
  .bp-logo {
    display: flex; align-items: center; gap: 1rem;
    flex-shrink: 0; position: relative; z-index: 2;
    margin-bottom: 2.75rem;
  }
  .bp-logo-icon { height: 52px; width: 52px; object-fit: contain; }
  .bp-logo-name {
    color: #FFFFFF;
    font-size: 1.75rem; font-weight: 700;
    font-family: var(--f-display); letter-spacing: -.02em; line-height: 1;
  }
  .bp-logo-badge {
    font-size: .7rem; font-weight: 700;
    background: rgba(0,182,122,0.1);
    color: #00B67A;
    border: 1px solid rgba(0,182,122,0.3);
    padding: .2rem .65rem;
    border-radius: 999px; letter-spacing: .05em;
  }

  /* Hero */
  .bp-hero {
    position: relative; z-index: 2;
    margin-bottom: 2rem;
  }
  .bp-hero h1 {
    font-size: clamp(1.75rem, 2.8vw, 2.4rem);
    line-height: 1.2; font-weight: 800;
    font-family: var(--f-display);
    color: #FFFFFF; margin: 0 0 .875rem;
    letter-spacing: -.02em;
  }
  .bp-hero h1 span { color: #00B67A; }
  .bp-hero p {
    font-size: .925rem; color: rgba(255,255,255,0.65);
    line-height: 1.7; max-width: 380px; margin: 0;
  }

  /* Feature rows */
  .bp-feats {
    display: flex; flex-direction: column; gap: .625rem;
    position: relative; z-index: 2;
    flex: 1;
  }
  .bp-feat {
    display: flex; align-items: center; gap: .875rem;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 14px;
    padding: .875rem 1rem;
  }
  .bp-feat-icon {
    width: 42px; height: 42px; flex-shrink: 0;
    border-radius: 11px;
    background: rgba(0,182,122,0.14);
    border: 1px solid rgba(0,182,122,0.22);
    display: flex; align-items: center; justify-content: center;
    color: var(--green-lt);
  }
  .bp-feat-txt { line-height: 1.4; }
  .bp-feat-txt strong {
    display: block; color: #FFFFFF;
    font-size: .9rem; font-weight: 600; margin-bottom: .2rem;
  }
  .bp-feat-txt span { font-size: .82rem; color: rgba(255,255,255,0.55); }

  /* Security card at bottom */
  .bp-safe {
    position: relative; z-index: 2;
    margin-top: 1.75rem;
    background: rgba(0,182,122,0.07);
    border: 1px solid rgba(0,182,122,0.2);
    border-radius: 14px;
    padding: .875rem 1.125rem;
    display: flex; align-items: center; gap: .75rem;
    flex-shrink: 0;
  }
  .bp-safe-icon {
    width: 36px; height: 36px; flex-shrink: 0;
    border-radius: 10px;
    background: rgba(0,182,122,0.15);
    display: flex; align-items: center; justify-content: center;
    color: #00B67A;
  }
  .bp-safe-title { font-size: .85rem; font-weight: 600; color: #00B67A; }
  .bp-safe-sub   { font-size: .78rem; color: rgba(255,255,255,0.45); margin-top: .15rem; }

  /* ── RIGHT PANEL ─────────────────────────────────────────────── */
  .bp-right {
    background: #F8FAFC;
    display: flex;
    flex-direction: column;
    position: relative;
    overflow: hidden;
  }

  /* Sign out */
  .bp-signout {
    position: absolute; top: 2rem; right: 2.5rem;
    display: flex; align-items: center; gap: .4rem;
    font-size: .875rem; font-weight: 500; color: #64748B;
    background: none; border: none; cursor: pointer;
    font-family: var(--f-sans); transition: color .18s;
    z-index: 10;
  }
  .bp-signout:hover { color: #0F172A; }

  /* Content area — centered */
  .bp-content {
    flex: 1; display: flex; flex-direction: column;
    justify-content: center;
    padding: 5.5rem 3.5rem 2.5rem;
    max-width: 640px; margin: 0 auto; width: 100%;
  }

  .bp-content h2 {
    font-size: 1.625rem; font-weight: 700;
    font-family: var(--f-display); color: #0F172A;
    letter-spacing: -.02em; margin: 0 0 .375rem;
  }
  .bp-content > p {
    font-size: .925rem; color: #64748B;
    line-height: 1.6; margin: 0 0 1.75rem;
  }

  /* Broker grid */
  .bp-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: .875rem;
    margin-bottom: 1.5rem;
  }

  /* Broker card */
  .bp-card {
    height: 130px;
    border-radius: 16px;
    border: 1.5px solid #E2E8F0;
    background: #FFFFFF;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    cursor: pointer; gap: .6rem;
    transition: var(--ease);
    position: relative;
    padding: .75rem .5rem .875rem;
  }
  .bp-card:hover:not(.bp-card--soon) {
    border-color: rgba(0,182,122,0.35);
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,182,122,0.08);
  }
  .bp-card--selected {
    border-color: #00B67A;
    background: rgba(0,182,122,0.04);
    box-shadow: 0 0 0 3px rgba(0,182,122,0.12);
  }
  .bp-card--soon { opacity: .6; cursor: default; }
  .bp-card-name {
    font-size: .78rem; font-weight: 600;
    color: #334155; text-align: center; line-height: 1.25;
  }
  .bp-card--selected .bp-card-name { color: #009B68; }

  /* check badge */
  .bp-card-check {
    position: absolute; top: 8px; right: 8px;
    width: 20px; height: 20px;
    border-radius: 50%;
    background: #00B67A;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 2px 8px rgba(0,182,122,0.35);
  }

  /* SOON badge */
  .bp-card-soon {
    position: absolute; top: 8px; right: 8px;
    font-size: .6rem; font-weight: 700; letter-spacing: .06em;
    color: #94A3B8;
    background: #F1F5F9;
    border: 1px solid #E2E8F0;
    padding: 2px 6px; border-radius: 5px;
  }

  /* Continue button */
  .bp-btn {
    width: 100%; height: 52px;
    border-radius: 12px;
    font-size: .975rem; font-weight: 600;
    font-family: var(--f-sans);
    display: flex; align-items: center; justify-content: center; gap: .5rem;
    transition: var(--ease); cursor: pointer; letter-spacing: .01em;
  }
  .bp-btn--idle {
    background: #F8FAFC;
    color: #94A3B8;
    border: 1.5px solid #E2E8F0;
    cursor: not-allowed;
  }
  .bp-btn--active {
    background: linear-gradient(90deg, #00B67A 0%, #009E6A 100%);
    color: #FFFFFF; border: none;
    box-shadow: 0 8px 24px rgba(0,182,122,0.22);
  }
  .bp-btn--active:hover { transform: translateY(-1px); box-shadow: 0 12px 30px rgba(0,182,122,0.32); }
  .bp-btn--loading {
    background: linear-gradient(90deg, #00B67A 0%, #009E6A 100%);
    color: #FFFFFF; border: none; cursor: wait;
    box-shadow: 0 8px 24px rgba(0,182,122,0.22);
  }

  /* Security footer */
  .bp-security {
    display: flex; align-items: center; justify-content: center; gap: .4rem;
    margin-top: .875rem;
    font-size: .8rem; color: #94A3B8;
  }

  /* Spinner */
  .bp-spinner {
    width: 16px; height: 16px;
    border: 2px solid rgba(255,255,255,0.35);
    border-top-color: #fff;
    border-radius: 50%;
    animation: bpSpin .7s linear infinite;
  }
  @keyframes bpSpin { to { transform: rotate(360deg); } }

  /* ── RESPONSIVE ──────────────────────────────────────────────── */
  @media (max-width: 900px) {
    .bp-shell   { grid-template-columns: 1fr; }
    .bp-left    { display: none; }
    .bp-right   { height: 100dvh; }
    .bp-signout { top: 1.25rem; right: 1.5rem; }
    .bp-content { padding: 4rem 1.5rem 2rem; max-width: 100%; }
    .bp-grid    { gap: .625rem; }
    .bp-card    { height: 110px; }
  }

  @media (max-width: 480px) {
    .bp-content { padding: 3.5rem 1.25rem 2rem; }
    .bp-grid    { gap: .5rem; }
    .bp-card    { height: 100px; border-radius: 12px; }
    .bp-content h2 { font-size: 1.375rem; }
  }
`;

/* ═══════════════════════════════════════════════════════════════
   BrokerCard component
   ═══════════════════════════════════════════════════════════════ */
function BrokerCard({ broker, selected, onSelect }) {
  const isSelected = selected === broker.id;
  return (
    <div
      className={[
        "bp-card",
        isSelected ? "bp-card--selected" : "",
        !broker.active ? "bp-card--soon" : "",
      ].join(" ")}
      onClick={() => broker.active && onSelect(broker.id)}
      role="button"
      tabIndex={broker.active ? 0 : -1}
      onKeyDown={(e) => e.key === "Enter" && broker.active && onSelect(broker.id)}
    >
      {isSelected && (
        <div className="bp-card-check">
          <Check style={{ width: 11, height: 11, color: "#fff", strokeWidth: 3 }} />
        </div>
      )}
      {!broker.active && <span className="bp-card-soon">SOON</span>}

      <BrokerLogo broker={broker} size="lg" />
      <span className="bp-card-name">{broker.name}</span>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Candlestick watermark SVG (reused from login page style)
   ═══════════════════════════════════════════════════════════════ */
function ChartWatermark() {
  return (
    <svg
      viewBox="0 0 640 520"
      preserveAspectRatio="xMidYMid slice"
      width="100%" height="100%"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="bpGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor="#00B67A" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#00B67A" stopOpacity="0"    />
        </linearGradient>
      </defs>
      <polygon
        points="0,460 60,418 115,394 170,410 220,368 275,342 325,295 378,316 425,268 478,248 525,206 572,182 610,158 640,138 640,520 0,520"
        fill="url(#bpGrad)"
      />
      <polyline
        points="0,460 60,418 115,394 170,410 220,368 275,342 325,295 378,316 425,268 478,248 525,206 572,182 610,158 640,138"
        fill="none" stroke="#00B67A" strokeWidth="1.8"
        strokeLinecap="round" strokeLinejoin="round"
      />
      <line x1="60"  y1="406" x2="60"  y2="430" stroke="#00B67A" strokeWidth="1.5"/>
      <rect x="52"  y="410" width="16" height="16" fill="#00B67A" rx="2"/>
      <line x1="275" y1="330" x2="275" y2="356" stroke="#00B67A" strokeWidth="1.5"/>
      <rect x="267" y="334" width="16" height="17" fill="#00B67A" rx="2"/>
      <line x1="425" y1="256" x2="425" y2="280" stroke="#00B67A" strokeWidth="1.5"/>
      <rect x="417" y="260" width="16" height="17" fill="#00B67A" rx="2"/>
      <line x1="170" y1="398" x2="170" y2="424" stroke="#F87171" strokeWidth="1.5"/>
      <rect x="162" y="403" width="16" height="18" fill="#F87171" rx="2"/>
    </svg>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Main page
   ═══════════════════════════════════════════════════════════════ */
export default function BrokerSelectPage() {
  const navigate = useNavigate();
  const logout = useAuthStore((s) => s.logout);
  const [selectedBroker, setSelectedBroker] = useState(null);
  const [addBrokerModal, setAddBrokerModal] = useState(null);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [credentialsConfigured, setCredentialsConfigured] = useState(false);
  const brokerLoading = useBrokerStore((s) => s.loading);
  const fetchCredentialsStatus = useBrokerStore((s) => s.fetchCredentialsStatus);
  const fetchStatus = useBrokerStore((s) => s.fetchStatus);
  const refreshSession = useBrokerStore((s) => s.refreshSession);
  const storeOAuthContext = useBrokerStore((s) => s.storeOAuthContext);
  const clearCredentials = useBrokerStore((s) => s.clearCredentials);

  useEffect(() => {
    (async () => {
      const connected = await fetchStatus();
      if (connected) {
        localStorage.setItem("alphasync_onboarded", "1");
        navigate("/dashboard", { replace: true });
      }
    })();
  }, [fetchStatus, navigate]);

  useEffect(() => {
    if (!selectedBroker) {
      setCredentialsConfigured(false);
      return;
    }
    const brokerDef = BROKERS.find((b) => b.id === selectedBroker);
    if (!brokerDef || !brokerDef.active || !brokerDef.broker) {
      setCredentialsConfigured(false);
      return;
    }
    (async () => {
      const status = await fetchCredentialsStatus(brokerDef.broker);
      setCredentialsConfigured(Boolean(status?.configured));
    })();
  }, [selectedBroker, fetchCredentialsStatus]);

  const openCredentialsModal = (brokerDef) => {
    setAddBrokerModal({
      broker: brokerDef.broker,
      brokerName: brokerDef.name,
      color: brokerDef.color,
      logoText: brokerDef.logoText,
    });
  };

  const quickConnect = async (brokerDef) => {
    try {
      const result = await refreshSession(brokerDef.broker);
      if (result.reauth_required && result.oauth_blocked) {
        toast.error(result.message || `Update your ${brokerDef.name} credentials to connect.`);
        openCredentialsModal(brokerDef);
        return;
      }
      if (result.reauth_required && result.redirect_url) {
        storeOAuthContext(brokerDef.broker, result.state);
        window.location.href = result.redirect_url;
        return;
      }
      handleConnected();
    } catch (err) {
      toast.error(err.message || "Failed to connect broker");
    }
  };

  const handleSignOut = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  const handleContinue = async () => {
    if (!selectedBroker) return;
    const brokerDef = BROKERS.find((b) => b.id === selectedBroker);
    if (!brokerDef || !brokerDef.active) return;

    if (brokerDef.requiresCredentials) {
      const status = await fetchCredentialsStatus(brokerDef.broker);
      setCredentialsConfigured(Boolean(status?.configured));
      if (!status?.configured) {
        openCredentialsModal(brokerDef);
        return;
      }
      if (brokerDef.broker === "zebu" && !status?.can_quickauth) {
        toast(
          "Your saved Zebu keys need a Trading Password and DOB/PAN for API login. Please update them.",
          { icon: "ℹ️" }
        );
        openCredentialsModal(brokerDef);
        return;
      }
    }
    await quickConnect(brokerDef);
  };

  const handleClearCredentials = async () => {
    const brokerDef = BROKERS.find((b) => b.id === selectedBroker);
    if (!brokerDef?.broker) return;
    if (!window.confirm(`Clear saved credentials for ${brokerDef.name}? Your AlphaSync account and trading data will not be affected.`)) {
      return;
    }
    try {
      await clearCredentials(brokerDef.broker);
      setCredentialsConfigured(false);
      toast.success(`Saved credentials for ${brokerDef.name} cleared. Enter fresh credentials to connect.`);
      openCredentialsModal(brokerDef);
    } catch (err) {
      toast.error(err.message || "Failed to clear credentials");
    }
  };

  const handleConnected = () => {
    setAddBrokerModal(null);
    localStorage.setItem("alphasync_onboarded", "1");
    setIsTransitioning(true);
    setTimeout(() => navigate("/dashboard"), 400);
  };

  /* ── derive button class ── */
  const btnClass = brokerLoading
    ? "bp-btn bp-btn--loading"
    : selectedBroker
    ? "bp-btn bp-btn--active"
    : "bp-btn bp-btn--idle";

  return (
    <div
      className="bp-shell"
      style={{ opacity: isTransitioning ? 0 : 1, transition: "opacity .4s ease" }}
    >
      <style dangerouslySetInnerHTML={{ __html: BP_STYLES }} />

      {/* ══════════════════════════════════════════════
          LEFT — dark navy branding panel
          ══════════════════════════════════════════════ */}
      <div className="bp-left">

        {/* candlestick chart watermark */}
        <div className="bp-chart-bg"><ChartWatermark /></div>

        {/* Logo */}
        <div className="bp-logo">
          <img src="/white-logo.png" alt="AlphaSync" className="bp-logo-icon" />
          <span className="bp-logo-name">AlphaSync</span>
          <span className="bp-logo-badge">α·SIM</span>
        </div>

        {/* Hero copy */}
        <div className="bp-hero">
          <h1>
            Connect your broker.<br />
            <span>Trade with live data.</span>
          </h1>
          <p>
            Link your real broker account once for live NSE &amp; BSE prices.
            All trades on AlphaSync stay simulated — your credentials are encrypted and never shared.
          </p>
        </div>

        {/* Feature rows */}
        <div className="bp-feats">
          <div className="bp-feat">
            <div className="bp-feat-icon">
              <ShieldCheck style={{ width: 20, height: 20 }} />
            </div>
            <div className="bp-feat-txt">
              <strong>One-time setup</strong>
              <span>Log in once — session saved for the trading day</span>
            </div>
          </div>

          <div className="bp-feat">
            <div className="bp-feat-icon">
              <Zap style={{ width: 20, height: 20 }} />
            </div>
            <div className="bp-feat-txt">
              <strong>Live market data</strong>
              <span>Real-time prices from your connected broker</span>
            </div>
          </div>

          <div className="bp-feat">
            <div className="bp-feat-icon">
              <RefreshCw style={{ width: 19, height: 19 }} />
            </div>
            <div className="bp-feat-txt">
              <strong>Daily refresh</strong>
              <span>Use Refresh to reconnect without re-entering API keys</span>
            </div>
          </div>
        </div>

        {/* Security card */}
        <div className="bp-safe">
          <div className="bp-safe-icon">
            <ShieldCheck style={{ width: 18, height: 18 }} />
          </div>
          <div>
            <div className="bp-safe-title">Your data is safe with us</div>
            <div className="bp-safe-sub">Credentials encrypted · Never stored in plaintext</div>
          </div>
        </div>

      </div>

      {/* ══════════════════════════════════════════════
          RIGHT — white panel with broker selection
          ══════════════════════════════════════════════ */}
      <div className="bp-right">

        {/* Sign out — absolute top-right */}
        <button className="bp-signout" onClick={handleSignOut}>
          <LogOut style={{ width: 15, height: 15 }} />
          Sign out
        </button>

        {/* Main content */}
        <div className="bp-content">
          <h2>Connect Your Broker</h2>
          <p>Select a broker to get live market data. All trades stay local and simulated.</p>

          {/* Broker grid */}
          <div className="bp-grid">
            {BROKERS.map((broker) => (
              <BrokerCard
                key={broker.id}
                broker={broker}
                selected={selectedBroker}
                onSelect={setSelectedBroker}
              />
            ))}
          </div>

          {/* Continue button */}
          <button
            onClick={handleContinue}
            disabled={!selectedBroker || brokerLoading}
            className={btnClass}
          >
            {brokerLoading ? (
              <>
                <span className="bp-spinner" />
                Connecting…
              </>
            ) : selectedBroker ? (
              <>
                Continue with {BROKERS.find((b) => b.id === selectedBroker)?.name}
                <ArrowRight style={{ width: 16, height: 16 }} />
              </>
            ) : (
              <>
                <Lock style={{ width: 15, height: 15 }} />
                Select a broker to continue
              </>
            )}
          </button>

          {/* Security note */}
          <div className="bp-security">
            <ShieldCheck style={{ width: 14, height: 14, color: "#10b981" }} />
            Credentials encrypted · Never stored in plaintext
          </div>

          {/* Credential management buttons */}
          {credentialsConfigured && selectedBroker && (() => {
            const brokerDef = BROKERS.find((b) => b.id === selectedBroker);
            if (!brokerDef || !brokerDef.active || !brokerDef.broker) return null;
            return (
              <div style={{ marginTop: "1rem", display: "flex", flexDirection: "column", gap: ".375rem", alignItems: "center" }}>
                <button
                  type="button"
                  onClick={() => openCredentialsModal(brokerDef)}
                  style={{ fontSize: ".8rem", color: "#64748B", background: "none", border: "none", cursor: "pointer" }}
                >
                  Update saved {brokerDef.name} credentials
                </button>
                <button
                  type="button"
                  onClick={handleClearCredentials}
                  style={{ fontSize: ".8rem", color: "#F87171", background: "none", border: "none", cursor: "pointer" }}
                >
                  Clear saved credentials and start fresh
                </button>
              </div>
            );
          })()}
        </div>
      </div>

      {/* AddBrokerAccountModal — completely unchanged */}
      {addBrokerModal && (
        <AddBrokerAccountModal
          open={true}
          onClose={() => setAddBrokerModal(null)}
          broker={addBrokerModal.broker}
          brokerName={addBrokerModal.brokerName}
          color={addBrokerModal.color}
          logoText={addBrokerModal.logoText}
          onConnected={handleConnected}
        />
      )}
    </div>
  );
}
