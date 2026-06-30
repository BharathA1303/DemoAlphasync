import { useState, useEffect } from "react";

import toast from "react-hot-toast";
import { ArrowRight, Eye, EyeOff, KeyRound, ShieldCheck, User, X } from "lucide-react";
import { useBrokerStore } from "../../stores/useBrokerStore";
import BrokerLogo from "./BrokerLogo";
import { getBrokerMeta } from "./brokerMeta";

/**
 * Unified "Add Broker Account" modal — replaces the old separate
 * credentials-modal + OAuth-redirect-modal two-step flow.
 *
 * One screen collects everything: App Key/Secret, the user's broker
 * Client ID, and (optionally) a trading password + DOB/PAN (Zebu) or
 * TOTP secret (Alice Blue). Submitting saves the credentials, then
 * immediately tries to connect — if a password was given, the backend
 * authenticates headlessly with zero browser interaction; otherwise the
 * browser is sent to the broker's own login page one time.
 */
const FIELD_CONFIG = {
  zebu: [
    { key: "api_key", label: "App Key", sublabel: "(from MYNT portal → Client Code → API Key)", placeholder: "Paste MYNT App Key", required: true },
    { key: "api_secret", label: "Secret Key", sublabel: "(OAuth secret — optional for API-only accounts)", placeholder: "Paste OAuth Secret if you have one", required: false, secret: true },
    { key: "client_id", label: "Zebu User ID", sublabel: "(required)", placeholder: "Your Zebu User ID", required: true },
    { key: "factor2", label: "Date of Birth / PAN", sublabel: "(required for API login)", placeholder: "e.g. 01-01-1990 or ABCDE1234", required: true },
    { key: "trading_password", label: "Trading Password", sublabel: "(required for API login)", placeholder: "Your Zebu login password", required: true, secret: true },
    { key: "vendor_code", label: "Vendor Code", sublabel: "(optional — defaults to User ID)", placeholder: "Your Zebu Vendor Code", required: false },
  ],
  aliceblue: [
    { key: "api_key", label: "App Key", sublabel: "(API Key)", placeholder: "Paste AliceBlue App Key", required: true },
    { key: "api_secret", label: "App Secret Key", sublabel: "(apiSecret — required)", placeholder: "Paste apiSecret from a3.aliceblueonline.com (Apps)", required: true, secret: true },
    { key: "client_id", label: "AliceBlue User ID", sublabel: "(required)", placeholder: "e.g. AB1234 — your AliceBlue User ID", required: true },
    { key: "trading_password", label: "Trading Password", sublabel: "(optional — for auto-refresh)", placeholder: "Your AliceBlue login password", required: false, secret: true },
    { key: "totp_secret", label: "TOTP Secret", sublabel: "(optional — for auto-refresh)", placeholder: "Base32 TOTP seed from AliceBlue 2FA setup", required: false, secret: true },
    { key: "algo_id", label: "Algo ID", sublabel: "(optional — not used by AliceBlue ANT API)", placeholder: "Leave blank — algoid not sent", required: false },
  ],
};

function ZebuHelpPanel({ redirectUrl }) {
  const copyRedirect = async () => {
    try {
      await navigator.clipboard.writeText(redirectUrl);
      toast.success("Redirect URL copied");
    } catch {
      toast.error("Could not copy — select and copy the URL manually");
    }
  };

  return (
    <div className="rounded-xl border border-emerald-200/80 bg-gradient-to-b from-emerald-50/80 to-slate-50 overflow-hidden">
      <div className="px-4 py-3 border-b border-emerald-100 bg-emerald-50/60">
        <p className="text-sm font-bold text-slate-900">How to connect Zebull (Mynt)</p>
        <p className="text-[11px] text-slate-500 mt-0.5">One-time setup — takes about 2 minutes</p>
      </div>

      <ol className="px-4 py-3 space-y-3 text-xs text-slate-700 leading-relaxed list-none">
        <li className="flex gap-2.5">
          <span className="flex-shrink-0 w-5 h-5 rounded-full bg-emerald-600 text-white text-[10px] font-bold flex items-center justify-center">1</span>
          <span>
            Log in to the <strong>MYNT developer portal</strong> at{" "}
            <a href="https://go.mynt.in" target="_blank" rel="noopener noreferrer" className="text-emerald-700 font-semibold underline">go.mynt.in</a>
          </span>
        </li>
        <li className="flex gap-2.5">
          <span className="flex-shrink-0 w-5 h-5 rounded-full bg-emerald-600 text-white text-[10px] font-bold flex items-center justify-center">2</span>
          <span>
            Go to <strong>Client Code → API Key</strong> and copy your <strong>App Key</strong> into the field above.
            Most API-only accounts do <strong>not</strong> need an OAuth Secret Key.
          </span>
        </li>
        <li className="flex gap-2.5">
          <span className="flex-shrink-0 w-5 h-5 rounded-full bg-emerald-600 text-white text-[10px] font-bold flex items-center justify-center">3</span>
          <span>
            Enter your <strong>Zebu User ID</strong>, <strong>Trading Password</strong>, and{" "}
            <strong>Date of Birth</strong> (DD-MM-YYYY) or <strong>PAN</strong> — this is <em>not</em> a TOTP/OTP code.
          </span>
        </li>
        <li className="flex gap-2.5">
          <span className="flex-shrink-0 w-5 h-5 rounded-full bg-emerald-600 text-white text-[10px] font-bold flex items-center justify-center">4</span>
          <div className="min-w-0 flex-1">
            <span className="block mb-1.5">
              <strong>Only if you have OAuth access:</strong> in the MYNT portal, set your Redirect URL to:
            </span>
            <div className="flex items-stretch gap-1.5">
              <code className="flex-1 text-[10px] font-mono bg-white border border-slate-200 rounded-lg px-2 py-1.5 break-all text-slate-800">
                {redirectUrl}
              </code>
              <button
                type="button"
                onClick={copyRedirect}
                className="flex-shrink-0 px-2 py-1 rounded-lg text-[10px] font-semibold border border-emerald-300 text-emerald-700 hover:bg-emerald-50"
              >
                Copy
              </button>
            </div>
          </div>
        </li>
        <li className="flex gap-2.5">
          <span className="flex-shrink-0 w-5 h-5 rounded-full bg-emerald-600 text-white text-[10px] font-bold flex items-center justify-center">5</span>
          <span>
            Click <strong>Add Broker</strong>. Sessions expire at midnight IST — with password + DOB saved,
            AlphaSync reconnects automatically each day.
          </span>
        </li>
      </ol>

      <div className="px-4 py-2.5 bg-amber-50 border-t border-amber-100 text-[11px] text-amber-900">
        <strong>API-only accounts:</strong> if MYNT shows &quot;Access Restricted for API Only Users&quot; in the browser,
        ignore OAuth — use Trading Password + DOB/PAN above instead.
      </div>
    </div>
  );
}

function HelpBox({ broker, redirectUrl }) {
  if (broker === "zebu") {
    return <ZebuHelpPanel redirectUrl={redirectUrl} />;
  }
  return (
    <div className="text-xs text-slate-600 leading-relaxed p-3.5 rounded-xl bg-slate-50 border border-slate-200">
      <p className="font-semibold text-slate-700 mb-1.5">Alice Blue setup (one-time):</p>
      <ol className="list-decimal list-inside space-y-1">
        <li>Get <strong>App Key</strong> + <strong>API Secret</strong> from a3.aliceblueonline.com → Apps</li>
        <li>In the Apps page set <strong>Redirect URL</strong> to <span className="font-mono text-[11px] break-all">{redirectUrl}</span></li>
        <li>In the same Apps page, find <strong>IP Whitelist</strong> — add this server's outbound IP (shown on the Trade page as "Server IP")</li>
        <li>Enter your AliceBlue User ID (e.g. AB1234) as the Client ID</li>
        <li>Leave <strong>Algo ID</strong> blank — Alice Blue's ANT API doesn't require it for manual orders</li>
      </ol>
      <div className="mt-2.5 p-2 bg-amber-50 border border-amber-200 rounded-lg text-[11px] text-amber-900">
        <strong>⚠️ Crucial Redirect Warning:</strong> If you are currently logged into the Alice Blue web trading platform (ant.aliceblueonline.com) in this browser, Alice Blue will skip the redirect and land you in their dashboard. <strong>You must log out of ant.aliceblueonline.com first</strong> or run this connect flow in an <strong>Incognito / Private Window</strong>.
      </div>
      <p className="mt-2">
        <strong>Optional:</strong> enter Trading Password + TOTP Secret to enable automatic
        daily reconnect — without them, Refresh opens a one-click login page each day.
      </p>
      <p className="mt-2">
        <strong>Most common rejection:</strong> "IP restriction" — fix by whitelisting the
        server IP in step 3.
      </p>
    </div>
  );
}

export default function AddBrokerAccountModal({ open, onClose, broker, brokerName, color, logoText, onConnected }) {
  const fields = FIELD_CONFIG[broker] || [];
  const brokerMeta = getBrokerMeta(broker) || { broker, name: brokerName, color, logoText };
  const [values, setValues] = useState({});
  const [displayName, setDisplayName] = useState("");
  const [showSecret, setShowSecret] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const saveCredentials = useBrokerStore((s) => s.saveCredentials);
  const refreshSession = useBrokerStore((s) => s.refreshSession);
  const storeOAuthContext = useBrokerStore((s) => s.storeOAuthContext);
  const clearCredentials = useBrokerStore((s) => s.clearCredentials);
  const fetchCredentialsStatus = useBrokerStore((s) => s.fetchCredentialsStatus);
  const brokerData = useBrokerStore((s) => s.brokers[broker] || {});
  const isConfigured = brokerData.credentialsConfigured;
  const loading = useBrokerStore((s) => s.loading);

  useEffect(() => {
    if (open && broker) {
      fetchCredentialsStatus(broker);
    }
  }, [open, broker, fetchCredentialsStatus]);

  if (!open) return null;

  const handleClearCredentials = async () => {
    if (!window.confirm(`Are you sure you want to delete and clear all saved credentials for ${brokerName}?`)) {
      return;
    }
    try {
      await clearCredentials(broker);
      setValues({});
      setDisplayName("");
      toast.success("Credentials cleared successfully. You can now enter them freshly.");
    } catch (err) {
      toast.error(err.message || "Failed to clear credentials");
    }
  };

  const requiredFilled = fields.filter((f) => f.required).every((f) => (values[f.key] || "").trim());
  const redirectUrl = `${window.location.origin}/broker/callback?broker=${broker}`;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!requiredFilled) {
      toast.error("Please fill in all required fields");
      return;
    }
    setSubmitting(true);
    try {
      await saveCredentials(broker, { ...values, display_name: displayName });
      const result = await refreshSession(broker);
      if (result.reauth_required && result.oauth_blocked) {
        toast.error(result.message || "Add your Trading Password and DOB/PAN to connect.");
        return;
      }
      if (result.reauth_required && result.redirect_url) {
        storeOAuthContext(broker, result.state);
        window.location.href = result.redirect_url;
        return;
      }
      toast.success(`${brokerName} connected!`);
      onConnected?.(result);
    } catch (err) {
      toast.error(err.message || "Failed to connect broker");
    } finally {
      setSubmitting(false);
    }
  };

  const busy = loading || submitting;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div
        className="relative w-full max-w-md rounded-2xl border border-slate-100 shadow-2xl overflow-hidden max-h-[90vh] flex flex-col"
        style={{ background: "#ffffff", boxShadow: "0 32px 80px rgba(2,8,23,0.25)" }}
      >
        <button onClick={onClose} className="absolute top-4 right-4 p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors z-10">
          <X className="w-5 h-5" />
        </button>

        <div className="px-6 pt-6 pb-4 border-b border-slate-100 flex-shrink-0">
          <h2 className="text-lg font-bold text-slate-900 mb-3">Add Broker Account</h2>
          <div className="flex items-center gap-3 p-2.5 rounded-xl bg-slate-50 border border-slate-200">
            <BrokerLogo broker={brokerMeta} size="sm" />
            <div className="text-sm font-semibold text-slate-900">{brokerName}</div>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4 overflow-y-auto flex-1">
          <div>
            <label className="block text-xs font-semibold text-slate-600 mb-1.5">
              Account Display Name <span className="text-slate-400 font-normal">(optional)</span>
            </label>
            <div className="relative">
              <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="e.g. My Primary Account"
                className="broker-cred-input w-full pl-10 pr-4 py-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-900 text-sm placeholder-slate-400 focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/20 outline-none transition-all"
              />
            </div>
          </div>

          {isConfigured && (
            <div className="p-3.5 rounded-xl border border-red-200/60 bg-red-50/20 flex items-center justify-between gap-3 text-xs">
              <div className="text-slate-600 leading-relaxed">
                <span className="font-bold text-slate-800">Saved Configuration:</span> An existing app key/credentials config {brokerData.apiKeyPreview ? `(${brokerData.apiKeyPreview})` : ''} is stored in the database.
              </div>
              <button
                type="button"
                onClick={handleClearCredentials}
                className="flex-shrink-0 px-3 py-1.5 rounded-lg text-[10px] font-bold bg-red-500 text-white hover:bg-red-600 transition-colors shadow-sm outline-none"
              >
                Clear Credentials
              </button>
            </div>
          )}

          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400 pt-1">Credentials</p>

          {fields.map((f) => (
            <div key={f.key}>
              <label className="block text-xs font-semibold text-slate-600 mb-1.5">
                {f.label} {f.sublabel && <span className="text-slate-400 font-normal">{f.sublabel}</span>}
              </label>
              <div className="relative">
                <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  type={f.secret && !showSecret[f.key] ? "password" : "text"}
                  value={values[f.key] || ""}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                  placeholder={f.placeholder}
                  className="broker-cred-input w-full pl-10 pr-10 py-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-900 text-sm placeholder-slate-400 focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/20 outline-none transition-all"
                />
                {f.secret && (
                  <button type="button" onClick={() => setShowSecret((s) => ({ ...s, [f.key]: !s[f.key] }))}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors">
                    {showSecret[f.key] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                )}
              </div>
            </div>
          ))}

          <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400 pt-2">Setup guide</p>
          <HelpBox broker={broker} redirectUrl={redirectUrl} />
        </form>

        <div className="px-6 py-4 border-t border-slate-100 flex-shrink-0 space-y-3">
          <div className="flex items-center gap-1.5 justify-center px-3 py-2 rounded-full bg-slate-50 border border-slate-200">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
            <span className="text-[10px] text-slate-600 text-center">
              Encrypted at rest · used only to fetch live prices for your demo account — no real orders are placed
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2.5 rounded-xl text-sm font-semibold text-slate-600 border border-slate-200 hover:bg-slate-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={busy || !requiredFilled}
              className="flex-1 py-2.5 rounded-xl text-sm font-bold flex items-center justify-center gap-2 text-white transition-all duration-300 disabled:opacity-60"
              style={{ background: "linear-gradient(135deg, #059669, #047857)", boxShadow: busy || !requiredFilled ? "none" : "0 4px 20px rgba(5,150,105,.25)" }}
            >
              {busy ? (
                <><div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />Connecting...</>
              ) : (
                <>Add Broker <ArrowRight className="w-4 h-4" /></>
              )}
            </button>
          </div>
        </div>
      </div>
      <style>{`
        .broker-cred-input { color: #0f172a; caret-color: #0f172a; }
        .broker-cred-input::placeholder { color: #94a3b8; opacity: 1; }
        .broker-cred-input:-webkit-autofill, .broker-cred-input:-webkit-autofill:hover,
        .broker-cred-input:-webkit-autofill:focus, .broker-cred-input:-webkit-autofill:active {
          -webkit-text-fill-color: #0f172a !important;
          box-shadow: 0 0 0px 1000px #f8fafc inset !important;
        }
      `}</style>
    </div>
  );
}
