import React, { useState, useEffect } from 'react';
import toast from 'react-hot-toast';
import {
  Activity, Key, Link, Clock, Database, RefreshCw,
  CheckCircle2, XCircle, AlertTriangle, Info, Eye, EyeOff
} from 'lucide-react';
import adminApi from '../services/adminApi';

export default function DataFeedPanel() {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(null);

  // Zebu OAuth Form states
  const [broker, setBroker] = useState('zebu');
  const [userId, setUserId] = useState('');
  const [clientId, setClientId] = useState('');
  const [secretKey, setSecretKey] = useState('');
  const [showSecret, setShowSecret] = useState(false);
  const [redirectUrl, setRedirectUrl] = useState(
    `${window.location.origin}/api/admin/broker/zebu/oauth-callback`
  );

  // Time Delay & Redis states
  const [delaySeconds, setDelaySeconds] = useState(300);
  const [redisMarketHoursOnly, setRedisMarketHoursOnly] = useState(true);

  const fetchStatus = async () => {
    try {
      setLoading(true);
      const res = await adminApi.get('/data-feed/status');
      setStatus(res.data);
      if (res.data.client_id) setClientId(res.data.client_id);
      if (res.data.user_id) setUserId(res.data.user_id);
      if (res.data.feed_delay_seconds !== undefined) setDelaySeconds(res.data.feed_delay_seconds);
      if (res.data.redis_active_market_hours_only !== undefined) {
        setRedisMarketHoursOnly(res.data.redis_active_market_hours_only);
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to fetch data feed status');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleSaveAndConnect = async (e) => {
    e.preventDefault();
    try {
      setLoading(true);
      await adminApi.post('/broker/zebu/oauth/configure', {
        client_id: clientId,
        user_id: userId,
        secret_key: secretKey,
        redirect_url: redirectUrl,
      });
      toast.success('Zebu credentials saved');

      const res = await adminApi.get('/broker/zebu/oauth/authorize-url');
      if (res.data?.authorize_url) {
        window.open(res.data.authorize_url, '_blank');
        toast.info('Opened Zebu OAuth login in a new tab');
      }
      fetchStatus();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to connect Zebu OAuth');
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    try {
      await adminApi.post('/broker/zebu/oauth/disconnect');
      toast.success('Zebu OAuth disconnected');
      fetchStatus();
    } catch (err) {
      toast.error('Failed to disconnect OAuth');
    }
  };

  const handleSaveDelay = async () => {
    try {
      await adminApi.put('/data-feed/delay', { delay_seconds: Number(delaySeconds) });
      toast.success(`Feed delay set to ${delaySeconds} seconds`);
      fetchStatus();
    } catch (err) {
      toast.error('Failed to update feed delay');
    }
  };

  const handleToggleRedisPolicy = async () => {
    const nextVal = !redisMarketHoursOnly;
    try {
      await adminApi.put('/data-feed/redis-policy', { active_market_hours_only: nextVal });
      setRedisMarketHoursOnly(nextVal);
      toast.success(`Redis market-hours caching set to ${nextVal ? 'ON' : 'OFF'}`);
    } catch (err) {
      toast.error('Failed to update Redis policy');
    }
  };

  const handleResyncSymbols = async () => {
    try {
      toast.loading('Syncing Symbol Master...', { id: 'resync' });
      const res = await adminApi.post('/data-feed/symbols/resync');
      toast.success(`Symbol master synced! ${JSON.stringify(res.data.synced_counts)}`, { id: 'resync' });
      fetchStatus();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to resync symbols', { id: 'resync' });
    }
  };

  const connStatus = status?.connection_status || 'disconnected';
  const oauthStatus = status?.oauth_status || connStatus;

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto space-y-6" style={{ color: 'var(--text-primary)' }}>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
            <Activity className="w-7 h-7 text-indigo-500" />
            Admin-Controlled Zebu Data Feed
          </h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-muted)' }}>
            OAuth broker connection, raw tick storage (Postgres + CSV), and time-delayed replay.
          </p>
        </div>
        <button
          onClick={fetchStatus}
          className="btn-secondary flex items-center gap-2 text-sm px-3.5 py-2"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh Status
        </button>
      </div>

      {/* Grid: 2 Columns */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Section 1: Zebu OAuth Login Panel */}
        <div className="rounded-2xl p-6 space-y-5 shadow-sm" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
          <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: 'var(--border)' }}>
            <h2 className="text-lg font-semibold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
              <Key className="w-5 h-5 text-indigo-500" />
              Zebu OAuth Connection
            </h2>
            <span className={`px-2.5 py-1 text-xs font-semibold rounded-full border ${
              connStatus === 'connected'
                ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20'
                : connStatus === 'error'
                ? 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20'
                : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20'
            }`}>
              {connStatus.toUpperCase()}
            </span>
          </div>
          {connStatus === 'stalled' && (
            <p className="text-xs -mt-2" style={{ color: 'var(--text-muted)' }}>
              OAuth token is valid but no ticks have arrived recently
              {status?.worker?.last_error ? `: ${status.worker.last_error}` : '.'}
              {status?.worker?.last_tick_timestamp ? ` Last tick: ${new Date(status.worker.last_tick_timestamp).toLocaleTimeString()}.` : ''}
            </p>
          )}

          <form onSubmit={handleSaveAndConnect} className="space-y-4">
            {/* Broker Dropdown */}
            <div>
              <label className="block text-xs font-medium uppercase tracking-wider mb-1" style={{ color: 'var(--text-muted)' }}>BROKER</label>
              <select
                value={broker}
                onChange={(e) => setBroker(e.target.value)}
                className="input-field w-full text-sm"
              >
                <option value="zebu">Zebu</option>
              </select>
            </div>

            {/* Info Notice */}
            <div className="flex items-center gap-2 p-3 rounded-xl text-xs" style={{ background: 'rgba(59, 130, 246, 0.08)', border: '1px solid rgba(59, 130, 246, 0.2)', color: 'var(--text-secondary)' }}>
              <Info className="w-4 h-4 shrink-0 text-blue-500" />
              <span>Enter your <strong>Zebu</strong> API credentials to connect.</span>
            </div>

            {/* User ID and Client ID */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs mb-1" style={{ color: 'var(--text-muted)' }}>User ID</label>
                <input
                  type="text"
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  placeholder="e.g. Z70953"
                  className="input-field w-full text-sm"
                  required
                />
              </div>
              <div>
                <label className="block text-xs mb-1" style={{ color: 'var(--text-muted)' }}>Client ID</label>
                <input
                  type="text"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  placeholder="e.g. Z70953_U"
                  className="input-field w-full text-sm"
                  required
                />
              </div>
            </div>

            {/* API Secret / Access Token */}
            <div>
              <label className="block text-xs mb-1" style={{ color: 'var(--text-muted)' }}>API SECRET / ACCESS TOKEN</label>
              <div className="relative">
                <input
                  type={showSecret ? 'text' : 'password'}
                  value={secretKey}
                  onChange={(e) => setSecretKey(e.target.value)}
                  placeholder="Enter API secret"
                  className="input-field w-full text-sm pr-10"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowSecret(!showSecret)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                >
                  {showSecret ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Redirect URL */}
            <div>
              <label className="block text-xs mb-1" style={{ color: 'var(--text-muted)' }}>REDIRECT URL</label>
              <input
                type="text"
                value={redirectUrl}
                onChange={(e) => setRedirectUrl(e.target.value)}
                className="input-field w-full text-sm"
              />
              <p className="text-[11px] mt-1" style={{ color: 'var(--text-muted)' }}>
                Must end with <code className="px-1.5 py-0.5 rounded font-mono" style={{ background: 'var(--bg-muted)', color: 'var(--text-primary)' }}>/zebu/callback</code>
              </p>
            </div>

            {/* Action Buttons */}
            <div className="flex items-center justify-end gap-3 pt-2">
              {oauthStatus === 'connected' && (
                <button
                  type="button"
                  onClick={handleDisconnect}
                  className="py-2 px-4 bg-rose-600/20 border border-rose-500/30 hover:bg-rose-600/30 text-rose-500 font-medium text-sm rounded-xl transition"
                >
                  Disconnect
                </button>
              )}
              <button
                type="submit"
                disabled={loading}
                className="btn-primary text-sm px-5 py-2 flex items-center gap-2"
              >
                <Link className="w-4 h-4 text-emerald-400" />
                Save & Connect
              </button>
            </div>
          </form>
        </div>

        {/* Section 2: Delay & Redis Settings */}
        <div className="rounded-2xl p-6 space-y-5 shadow-sm" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
          <div className="border-b pb-3" style={{ borderColor: 'var(--border)' }}>
            <h2 className="text-lg font-semibold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
              <Clock className="w-5 h-5 text-indigo-500" />
              Feed Time-Delay Gate & Redis Policy
            </h2>
          </div>

          <div className="space-y-4">
            <div>
              <label className="text-xs" style={{ color: 'var(--text-muted)' }}>Time Delay (Seconds)</label>
              <div className="flex gap-2 mt-1">
                <input
                  type="number"
                  min="0"
                  max="86400"
                  value={delaySeconds}
                  onChange={(e) => setDelaySeconds(e.target.value)}
                  className="input-field w-full text-sm"
                />
                <button
                  onClick={handleSaveDelay}
                  className="btn-primary text-sm px-4 py-2 shrink-0"
                >
                  Apply Delay
                </button>
              </div>
              <div className="flex gap-2 mt-2">
                {[60, 300, 900].map((preset) => (
                  <button
                    key={preset}
                    onClick={() => {
                      setDelaySeconds(preset);
                    }}
                    className={`px-2.5 py-1 text-xs rounded-lg border transition-colors ${
                      Number(delaySeconds) === preset
                        ? 'bg-indigo-500/20 text-indigo-500 border-indigo-500/40 font-bold'
                        : 'btn-secondary'
                    }`}
                  >
                    {preset === 60 ? '1 min (60s)' : preset === 300 ? '5 min (300s)' : '15 min (900s)'}
                  </button>
                ))}
              </div>
            </div>

            <div className="p-3 rounded-xl border" style={{ background: 'var(--bg-muted)', borderColor: 'var(--border)' }}>
              <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                <strong className="text-indigo-500">Live Preview:</strong> All platform users see market ticks & charts delayed by{' '}
                <span className="text-emerald-500 font-bold">{delaySeconds} seconds</span>.
              </p>
            </div>

            <div className="pt-3 border-t flex items-center justify-between" style={{ borderColor: 'var(--border)' }}>
              <div>
                <span className="text-sm font-medium block" style={{ color: 'var(--text-primary)' }}>Redis Market-Hours Policy</span>
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Cache quotes in Redis strictly during active market hours.</p>
              </div>
              <button
                onClick={handleToggleRedisPolicy}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  redisMarketHoursOnly ? 'bg-indigo-600' : 'bg-slate-500'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    redisMarketHoursOnly ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>
          </div>
        </div>

      </div>

      {/* Section 3: Ingestion Monitor & Symbol Master */}
      <div className="rounded-2xl p-6 space-y-5 shadow-sm" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
        <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: 'var(--border)' }}>
          <h2 className="text-lg font-semibold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
            <Database className="w-5 h-5 text-indigo-500" />
            Live Ingestion Monitor & Symbol Master
          </h2>
          <button
            onClick={handleResyncSymbols}
            className="btn-secondary text-xs px-3.5 py-2 flex items-center gap-1.5 font-medium"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Re-sync Symbol Master
          </button>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="p-4 rounded-xl border" style={{ background: 'var(--bg-muted)', borderColor: 'var(--border)' }}>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Worker Status</span>
            <div className="flex items-center gap-2 mt-1">
              {status?.worker?.is_running ? (
                <>
                  <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                  <span className="text-sm font-semibold text-emerald-500">INGESTING</span>
                </>
              ) : (
                <>
                  <XCircle className="w-5 h-5 text-slate-400" />
                  <span className="text-sm font-semibold" style={{ color: 'var(--text-muted)' }}>STOPPED</span>
                </>
              )}
            </div>
          </div>

          <div className="p-4 rounded-xl border" style={{ background: 'var(--bg-muted)', borderColor: 'var(--border)' }}>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Ticks Ingested Today</span>
            <p className="text-xl font-bold mt-1" style={{ color: 'var(--text-primary)' }}>
              {status?.worker?.ticks_ingested_today?.toLocaleString() || 0}
            </p>
          </div>

          <div className="p-4 rounded-xl border" style={{ background: 'var(--bg-muted)', borderColor: 'var(--border)' }}>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Subscribed Scrips</span>
            <p className="text-xl font-bold text-indigo-500 mt-1">
              {status?.worker?.subscribed_count || 0}
            </p>
          </div>

          <div className="p-4 rounded-xl border" style={{ background: 'var(--bg-muted)', borderColor: 'var(--border)' }}>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Active Symbol Master Rows</span>
            <p className="text-xl font-bold text-emerald-500 mt-1">
              {status?.active_symbols_count?.toLocaleString() || 0}
            </p>
          </div>
        </div>

        {status?.worker?.last_error && (
          <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl flex items-center gap-2 text-xs text-rose-500">
            <AlertTriangle className="w-4 h-4 text-rose-500 shrink-0" />
            <span>Worker Last Error: {status.worker.last_error}</span>
          </div>
        )}
      </div>
    </div>
  );
}
