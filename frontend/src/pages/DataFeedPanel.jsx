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

  // Zebu OAuth Form states (matching Image 1 layout)
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

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6 text-slate-100">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2 text-white">
            <Activity className="w-7 h-7 text-indigo-400" />
            Admin-Controlled Zebu Data Feed
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            OAuth broker connection, raw tick storage (Postgres + CSV), and time-delayed replay.
          </p>
        </div>
        <button
          onClick={fetchStatus}
          className="flex items-center gap-2 px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm transition"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh Status
        </button>
      </div>

      {/* Grid: 2 Columns */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        {/* Section 1: Zebu OAuth Login Panel (Matches Image 1 layout) */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-5 shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h2 className="text-lg font-semibold flex items-center gap-2 text-white">
              <Key className="w-5 h-5 text-indigo-400" />
              Zebu OAuth Connection
            </h2>
            <span className={`px-2.5 py-1 text-xs font-semibold rounded-full border ${
              connStatus === 'connected'
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                : connStatus === 'error'
                ? 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
            }`}>
              {connStatus.toUpperCase()}
            </span>
          </div>

          <form onSubmit={handleSaveAndConnect} className="space-y-4">
            {/* Broker Dropdown */}
            <div>
              <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">BROKER</label>
              <select
                value={broker}
                onChange={(e) => setBroker(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
              >
                <option value="zebu">Zebu</option>
              </select>
            </div>

            {/* Info Notice */}
            <div className="flex items-center gap-2 p-3 bg-blue-500/10 border border-blue-500/20 rounded-xl text-xs text-blue-300">
              <Info className="w-4 h-4 shrink-0 text-blue-400" />
              <span>Enter your <strong>Zebu</strong> API credentials to connect.</span>
            </div>

            {/* User ID and Client ID */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1">User ID</label>
                <input
                  type="text"
                  value={userId}
                  onChange={(e) => setUserId(e.target.value)}
                  placeholder="e.g. Z70953"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Client ID</label>
                <input
                  type="text"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  placeholder="e.g. Z70953_U"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>
            </div>

            {/* API Secret / Access Token */}
            <div>
              <label className="block text-xs text-slate-400 mb-1">API SECRET / ACCESS TOKEN</label>
              <div className="relative">
                <input
                  type={showSecret ? 'text' : 'password'}
                  value={secretKey}
                  onChange={(e) => setSecretKey(e.target.value)}
                  placeholder="Enter API secret"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 pr-10"
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
              <label className="block text-xs text-slate-400 mb-1">REDIRECT URL</label>
              <input
                type="text"
                value={redirectUrl}
                onChange={(e) => setRedirectUrl(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-sm text-slate-300 focus:outline-none focus:border-indigo-500"
              />
              <p className="text-[11px] text-slate-500 mt-1">Must end with <code className="bg-slate-800 px-1 py-0.5 rounded text-slate-300">/zebu/callback</code></p>
            </div>

            {/* Action Buttons */}
            <div className="flex items-center justify-end gap-3 pt-2">
              {connStatus === 'connected' && (
                <button
                  type="button"
                  onClick={handleDisconnect}
                  className="py-2.5 px-4 bg-rose-600/20 border border-rose-500/30 hover:bg-rose-600/30 text-rose-300 font-medium text-sm rounded-xl transition"
                >
                  Disconnect
                </button>
              )}
              <button
                type="submit"
                disabled={loading}
                className="py-2.5 px-6 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-white font-semibold text-sm rounded-xl transition shadow-lg flex items-center gap-2"
              >
                <Link className="w-4 h-4 text-emerald-400" />
                Save & Connect
              </button>
            </div>
          </form>
        </div>

        {/* Section 2: Delay & Redis Settings */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-5 shadow-xl">
          <div className="border-b border-slate-800 pb-3">
            <h2 className="text-lg font-semibold flex items-center gap-2 text-white">
              <Clock className="w-5 h-5 text-indigo-400" />
              Feed Time-Delay Gate & Redis Policy
            </h2>
          </div>

          <div className="space-y-4">
            <div>
              <label className="text-xs text-slate-400">Time Delay (Seconds)</label>
              <div className="flex gap-2 mt-1">
                <input
                  type="number"
                  min="0"
                  max="86400"
                  value={delaySeconds}
                  onChange={(e) => setDelaySeconds(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                />
                <button
                  onClick={handleSaveDelay}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-sm rounded-xl transition shrink-0"
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
                    className={`px-2.5 py-1 text-xs rounded-lg border ${
                      Number(delaySeconds) === preset
                        ? 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30'
                        : 'bg-slate-800 text-slate-400 border-slate-700 hover:bg-slate-700'
                    }`}
                  >
                    {preset === 60 ? '1 min (60s)' : preset === 300 ? '5 min (300s)' : '15 min (900s)'}
                  </button>
                ))}
              </div>
            </div>

            <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl">
              <p className="text-xs text-slate-400">
                <strong className="text-indigo-300">Live Preview:</strong> All platform users see market ticks & charts delayed by{' '}
                <span className="text-emerald-400 font-bold">{delaySeconds} seconds</span>.
              </p>
            </div>

            <div className="pt-2 border-t border-slate-800 flex items-center justify-between">
              <div>
                <span className="text-sm font-medium text-slate-200">Redis Market-Hours Policy</span>
                <p className="text-xs text-slate-400">Cache quotes in Redis strictly during active market hours.</p>
              </div>
              <button
                onClick={handleToggleRedisPolicy}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  redisMarketHoursOnly ? 'bg-indigo-600' : 'bg-slate-700'
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
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-5 shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <h2 className="text-lg font-semibold flex items-center gap-2 text-white">
            <Database className="w-5 h-5 text-indigo-400" />
            Live Ingestion Monitor & Symbol Master
          </h2>
          <button
            onClick={handleResyncSymbols}
            className="flex items-center gap-1.5 px-3.5 py-2 bg-indigo-600/20 border border-indigo-500/30 hover:bg-indigo-600/30 text-indigo-300 rounded-xl text-xs font-medium transition"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Re-sync Symbol Master
          </button>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-slate-950 p-4 border border-slate-800 rounded-xl">
            <span className="text-xs text-slate-400">Worker Status</span>
            <div className="flex items-center gap-2 mt-1">
              {status?.worker?.is_running ? (
                <>
                  <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                  <span className="text-sm font-semibold text-emerald-400">INGESTING</span>
                </>
              ) : (
                <>
                  <XCircle className="w-5 h-5 text-slate-500" />
                  <span className="text-sm font-semibold text-slate-400">STOPPED</span>
                </>
              )}
            </div>
          </div>

          <div className="bg-slate-950 p-4 border border-slate-800 rounded-xl">
            <span className="text-xs text-slate-400">Ticks Ingested Today</span>
            <p className="text-xl font-bold text-white mt-1">
              {status?.worker?.ticks_ingested_today?.toLocaleString() || 0}
            </p>
          </div>

          <div className="bg-slate-950 p-4 border border-slate-800 rounded-xl">
            <span className="text-xs text-slate-400">Subscribed Scrips</span>
            <p className="text-xl font-bold text-indigo-400 mt-1">
              {status?.worker?.subscribed_count || 0}
            </p>
          </div>

          <div className="bg-slate-950 p-4 border border-slate-800 rounded-xl">
            <span className="text-xs text-slate-400">Active Symbol Master Rows</span>
            <p className="text-xl font-bold text-emerald-400 mt-1">
              {status?.active_symbols_count?.toLocaleString() || 0}
            </p>
          </div>
        </div>

        {status?.worker?.last_error && (
          <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl flex items-center gap-2 text-xs text-rose-300">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>Worker Last Error: {status.worker.last_error}</span>
          </div>
        )}
      </div>
    </div>
  );
}
