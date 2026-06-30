import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import {
    RefreshCw,
    Link2,
    Unlink,
    ShieldCheck,
    CheckCircle2,
    AlertTriangle,
    ArrowLeftRight,
} from 'lucide-react';
import { useBrokerStore } from '../stores/useBrokerStore';
import { BROKERS, getBrokerMeta } from '../components/broker/brokerMeta';
import AddBrokerAccountModal from '../components/broker/AddBrokerAccountModal';
import BrokerLogo from '../components/broker/BrokerLogo';

function formatDate(iso) {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
    } catch {
        return '—';
    }
}

function ConnectedBrokerCard({ meta, info, busy, onRefresh, onSwitch, onDisconnect }) {
    const isExpired = info.status === 'expired';
    return (
        <div className="kpi-card bg-surface-900/70 border-edge/15 space-y-3">
            <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-3">
                    <BrokerLogo broker={meta} size="md" />
                    <div>
                        <div className="text-sm font-semibold text-heading">{meta.name}</div>
                        <div className="text-xs text-gray-500">
                            {info.brokerUserId ? `Client ID: ${info.brokerUserId}` : 'Connected account'}
                        </div>
                    </div>
                </div>
                <span
                    className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1 rounded-full ${
                        isExpired ? 'bg-amber-500/10 text-amber-500' : 'bg-emerald-500/10 text-emerald-500'
                    }`}
                >
                    {isExpired ? <AlertTriangle className="w-3 h-3" /> : <CheckCircle2 className="w-3 h-3" />}
                    {isExpired ? 'Session expired' : 'Active'}
                </span>
            </div>

            <div className="text-xs text-gray-500">
                Token expiry: <span className="text-heading font-medium">{formatDate(info.tokenExpiry)}</span>
            </div>

            <div className="flex items-center gap-2 pt-1 flex-wrap">
                <button
                    disabled={busy}
                    onClick={onRefresh}
                    className="btn-secondary text-xs flex items-center gap-1.5 px-3 py-1.5 disabled:opacity-50"
                >
                    <RefreshCw className="w-3.5 h-3.5" /> Refresh
                </button>
                <button
                    disabled={busy}
                    onClick={onSwitch}
                    className="btn-secondary text-xs flex items-center gap-1.5 px-3 py-1.5 disabled:opacity-50"
                >
                    <ArrowLeftRight className="w-3.5 h-3.5" /> Switch broker
                </button>
                <button
                    disabled={busy}
                    onClick={onDisconnect}
                    className="text-xs flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-red-500 hover:bg-red-500/10 transition-colors disabled:opacity-50"
                >
                    <Unlink className="w-3.5 h-3.5" /> Disconnect
                </button>
            </div>
        </div>
    );
}

function AvailableBrokerCard({ meta, connected, onConnect }) {
    const clickable = meta.active && !connected;
    return (
        <div
            className={`rounded-xl border p-4 flex items-center gap-3 transition-colors ${
                clickable
                    ? 'border-edge/15 hover:border-primary-500/30 cursor-pointer'
                    : connected
                        ? 'border-emerald-500/30'
                        : 'border-edge/10 opacity-60'
            }`}
            onClick={() => clickable && onConnect(meta)}
        >
            <BrokerLogo broker={meta} size="sm" />
            <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-heading">{meta.name}</div>
                <div className="text-[11px] text-gray-500">
                    {connected ? 'Connected' : meta.active ? 'Tap to connect' : 'Coming soon'}
                </div>
            </div>
            {connected && <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />}
        </div>
    );
}

/**
 * In-app broker management page. Shows the user's connected broker and
 * every supported broker. Refresh re-runs the connect flow with already
 * saved credentials (no re-typing secrets); Switch disconnects the current
 * broker and starts the connect flow for a different one.
 */
export default function BrokersPage() {
    const brokers = useBrokerStore((s) => s.brokers);
    const fetchStatus = useBrokerStore((s) => s.fetchStatus);
    const fetchCredentialsStatus = useBrokerStore((s) => s.fetchCredentialsStatus);
    const refreshSession = useBrokerStore((s) => s.refreshSession);
    const storeOAuthContext = useBrokerStore((s) => s.storeOAuthContext);
    const disconnect = useBrokerStore((s) => s.disconnect);

    const [loadingStatus, setLoadingStatus] = useState(true);
    const [addBrokerModal, setAddBrokerModal] = useState(null);
    const [busyBroker, setBusyBroker] = useState(null);

    useEffect(() => {
        (async () => {
            await fetchStatus();
            setLoadingStatus(false);
        })();
    }, [fetchStatus]);

    const connectedEntry = Object.entries(brokers).find(([, info]) => info.status === 'connected')
        || Object.entries(brokers).find(([, info]) => info.status === 'expired');
    const connectedBroker = connectedEntry?.[0] || null;
    const connectedInfo = connectedEntry?.[1] || null;
    const connectedMeta = connectedBroker ? getBrokerMeta(connectedBroker) : null;

    const openAddBrokerModal = (meta) =>
        setAddBrokerModal({ broker: meta.broker, brokerName: meta.name, color: meta.color, logoText: meta.logoText });

    const startConnect = async (meta) => {
        if (meta.requiresCredentials) {
            const status = await fetchCredentialsStatus(meta.broker);
            if (!status?.configured) {
                openAddBrokerModal(meta);
                return;
            }
            if (meta.broker === 'zebu' && !status?.can_quickauth) {
                toast('Add your Trading Password and DOB/PAN to connect via API.', { icon: 'ℹ️' });
                openAddBrokerModal(meta);
                return;
            }
        }
        await quickConnect(meta);
    };

    const quickConnect = async (meta) => {
        try {
            const result = await refreshSession(meta.broker);
            if (result.reauth_required && result.oauth_blocked) {
                toast.error(result.message || 'Update your Zebu credentials to connect.');
                openAddBrokerModal(meta);
                return;
            }
            if (result.reauth_required && result.redirect_url) {
                storeOAuthContext(meta.broker, result.state);
                window.location.href = result.redirect_url;
                return;
            }
            await fetchStatus();
            toast.success(`${meta.name} connected!`);
        } catch (err) {
            toast.error(err.message || 'Failed to connect broker');
        }
    };

    const handleConnectClick = (meta) => {
        if (meta.broker === connectedBroker) return;
        if (connectedBroker) {
            if (!window.confirm(`Switch from ${connectedMeta?.name} to ${meta.name}? You'll need to log in to ${meta.name}.`)) return;
            doSwitch(meta);
            return;
        }
        startConnect(meta);
    };

    const doSwitch = async (targetMeta) => {
        setBusyBroker(connectedBroker);
        try {
            await disconnect(connectedBroker);
            await startConnect(targetMeta);
        } finally {
            setBusyBroker(null);
        }
    };

    const handleRefresh = async () => {
        if (!connectedBroker || !connectedMeta) return;
        setBusyBroker(connectedBroker);
        try {
            const result = await refreshSession(connectedBroker);
            if (result.reauth_required && result.oauth_blocked) {
                toast.error(result.message || 'Update your Zebu credentials to reconnect.');
                openAddBrokerModal(connectedMeta);
                return;
            }
            if (result.reauth_required && result.redirect_url) {
                storeOAuthContext(connectedBroker, result.state);
                window.location.href = result.redirect_url;
                return;
            }
            await fetchStatus();
            toast.success(`${connectedMeta.name} session refreshed`);
        } catch (err) {
            toast.error(err.message || 'Refresh failed');
        } finally {
            setBusyBroker(null);
        }
    };

    const handleDisconnect = async () => {
        if (!connectedBroker || !connectedMeta) return;
        if (!window.confirm(`Disconnect ${connectedMeta.name}? You'll need to connect a broker again to keep using AlphaSync.`)) return;
        setBusyBroker(connectedBroker);
        try {
            await disconnect(connectedBroker);
            toast.success(`${connectedMeta.name} disconnected`);
        } finally {
            setBusyBroker(null);
        }
    };

    return (
        <div className="p-4 lg:p-6 space-y-6 animate-fade-in">
            <div>
                <h1 className="text-2xl font-display font-semibold text-heading">Brokers</h1>
                <p className="text-sm text-gray-500 mt-1">
                    Manage the broker account that powers your live market data.
                </p>
            </div>

            <div>
                <h2 className="text-sm font-semibold text-heading mb-3">Connected</h2>
                {loadingStatus ? (
                    <div className="kpi-card bg-surface-900/70 border-edge/15 h-24 animate-pulse" />
                ) : connectedMeta ? (
                    <ConnectedBrokerCard
                        meta={connectedMeta}
                        info={connectedInfo}
                        busy={busyBroker === connectedBroker}
                        onRefresh={handleRefresh}
                        onSwitch={() => document.getElementById('available-brokers')?.scrollIntoView({ behavior: 'smooth' })}
                        onDisconnect={handleDisconnect}
                    />
                ) : (
                    <div className="kpi-card bg-surface-900/70 border-edge/15 flex items-center gap-3">
                        <Link2 className="w-5 h-5 text-amber-500 flex-shrink-0" />
                        <div className="text-sm text-heading">No broker connected yet. Choose one below to get live market data.</div>
                    </div>
                )}
            </div>

            <div id="available-brokers">
                <h2 className="text-sm font-semibold text-heading mb-3">Supported Brokers</h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {BROKERS.filter((b) => b.broker).map((meta) => (
                        <AvailableBrokerCard
                            key={meta.id}
                            meta={meta}
                            connected={meta.broker === connectedBroker}
                            onConnect={handleConnectClick}
                        />
                    ))}
                </div>
                <div className="flex items-center gap-1.5 mt-4">
                    <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
                    <span className="text-[11px] text-gray-500">Credentials encrypted at rest · Never stored in plaintext</span>
                </div>
            </div>

            {addBrokerModal && (
                <AddBrokerAccountModal
                    open={true}
                    onClose={() => setAddBrokerModal(null)}
                    broker={addBrokerModal.broker}
                    brokerName={addBrokerModal.brokerName}
                    color={addBrokerModal.color}
                    logoText={addBrokerModal.logoText}
                    onConnected={() => {
                        setAddBrokerModal(null);
                        fetchStatus();
                    }}
                />
            )}
        </div>
    );
}
