import { useEffect, useMemo, useRef, useState } from 'react';
import Modal from '../ui/Modal';
import { RefreshCw, Search } from 'lucide-react';
import { cn } from '../../utils/cn';
import api, { isRateLimited } from '../../services/api';
import { formatPrice, formatQuantity } from '../../utils/formatters';

const POPULAR_UNDERLYINGS = [
    { symbol: 'NIFTY', type: 'Index', desc: 'Nifty 50 Futures' },
    { symbol: 'BANKNIFTY', type: 'Index', desc: 'Bank Nifty Futures' },
    { symbol: 'FINNIFTY', type: 'Index', desc: 'Nifty Financial Services Futures' },
    { symbol: 'MIDCPNIFTY', type: 'Index', desc: 'Nifty Mid Select Futures' },
    { symbol: 'NIFTYNXT50', type: 'Index', desc: 'Nifty Next 50 Futures' },
    { symbol: 'RELIANCE', type: 'Stock', desc: 'Reliance Industries' },
    { symbol: 'TCS', type: 'Stock', desc: 'Tata Consultancy Services' },
    { symbol: 'HDFCBANK', type: 'Stock', desc: 'HDFC Bank' },
    { symbol: 'INFY', type: 'Stock', desc: 'Infosys' },
    { symbol: 'ICICIBANK', type: 'Stock', desc: 'ICICI Bank' },
    { symbol: 'SBIN', type: 'Stock', desc: 'State Bank of India' },
    { symbol: 'LT', type: 'Stock', desc: 'Larsen & Toubro' },
    { symbol: 'ITC', type: 'Stock', desc: 'ITC' },
    { symbol: 'AXISBANK', type: 'Stock', desc: 'Axis Bank' },
    { symbol: 'BHARTIARTL', type: 'Stock', desc: 'Bharti Airtel' },
    { symbol: 'TATAMOTORS', type: 'Stock', desc: 'Tata Motors' },
    { symbol: 'SUNPHARMA', type: 'Stock', desc: 'Sun Pharma' },
    { symbol: 'MARUTI', type: 'Stock', desc: 'Maruti Suzuki' },
];

const sanitize = (value = '') => String(value || '').replace(/\.(NS|BO)$/i, '').trim().toUpperCase();

const formatExpiry = (date) => {
    if (!date) return 'NFO';
    const parsed = new Date(date);
    if (Number.isNaN(parsed.getTime())) return date;
    return parsed.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' }).toUpperCase();
};

export default function AddFuturesContractModal({
    isOpen,
    onClose,
    onAddContract,
    watchlistItems = [],
}) {
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedUnderlying, setSelectedUnderlying] = useState('NIFTY');
    const [contracts, setContracts] = useState([]);
    const [quotes, setQuotes] = useState({});
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const searchRef = useRef(null);

    const underlyings = useMemo(() => {
        const query = sanitize(searchQuery);
        if (!query) return POPULAR_UNDERLYINGS;
        return POPULAR_UNDERLYINGS.filter((item) =>
            item.symbol.includes(query) || item.desc.toUpperCase().includes(query)
        );
    }, [searchQuery]);

    useEffect(() => {
        if (!isOpen) {
            setSearchQuery('');
            setContracts([]);
            setQuotes({});
            setError(null);
            return;
        }
        setTimeout(() => searchRef.current?.focus(), 100);
        setSelectedUnderlying('NIFTY');
    }, [isOpen]);

    useEffect(() => {
        if (!isOpen || !selectedUnderlying || isRateLimited()) return;
        let cancelled = false;
        const loadContracts = async () => {
            setLoading(true);
            setError(null);
            try {
                const res = await api.get(`/futures/contracts/${encodeURIComponent(selectedUnderlying)}`);
                if (cancelled) return;
                const list = (res.data?.contracts || []).filter((c) => c?.contract_symbol && c?.token);
                setContracts(list);
                if (list.length === 0) {
                    setError(`No futures contracts returned for ${selectedUnderlying}`);
                    setQuotes({});
                    return;
                }

                const quoteResults = await Promise.allSettled(
                    list.map((contract) =>
                        api.get(`/futures/quote/${encodeURIComponent(contract.contract_symbol)}`, {
                            params: { token: contract.token, exchange: contract.exchange || 'NFO' },
                        })
                    )
                );
                if (cancelled) return;
                const nextQuotes = {};
                quoteResults.forEach((result, index) => {
                    if (result.status === 'fulfilled') {
                        nextQuotes[list[index].contract_symbol] = result.value.data;
                    }
                });
                setQuotes(nextQuotes);
            } catch (err) {
                if (!cancelled) {
                    setContracts([]);
                    setQuotes({});
                    setError(err?.response?.data?.detail || `Could not fetch contracts for ${selectedUnderlying}`);
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        };
        loadContracts();
        return () => { cancelled = true; };
    }, [isOpen, selectedUnderlying]);

    const handleSelectContract = (contractSymbol) => {
        const normalized = String(contractSymbol || '').toUpperCase();
        const alreadyAdded = watchlistItems.some(
            (item) => item.contract_symbol?.toUpperCase() === normalized
        );
        if (alreadyAdded) {
            setError(`${normalized} is already in your watchlist`);
            return;
        }
        onAddContract(normalized, selectedUnderlying);
    };

    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Add Futures Contract" size="md">
            <div className="p-5 space-y-4">
                <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                    <input
                        ref={searchRef}
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search underlying (NIFTY, RELIANCE, TCS)..."
                        className="w-full bg-surface-800/60 border border-edge/5 rounded-lg pl-10 pr-3 py-2 text-sm text-heading placeholder-gray-500 focus:outline-none focus:border-primary-500/30"
                    />
                </div>

                <div className="flex gap-2 overflow-x-auto no-scrollbar pb-1">
                    {underlyings.map((item) => (
                        <button
                            key={item.symbol}
                            onClick={() => setSelectedUnderlying(item.symbol)}
                            className={cn(
                                'flex-shrink-0 px-3 py-2 rounded-lg border text-left transition-colors min-w-[140px]',
                                selectedUnderlying === item.symbol
                                    ? 'bg-primary-500/15 border-primary-500/30 text-primary-600'
                                    : 'bg-surface-800/40 border-edge/10 text-gray-500 hover:text-heading'
                            )}
                        >
                            <p className="text-xs font-bold">{item.symbol}</p>
                            <p className="text-[10px] truncate opacity-70">{item.desc}</p>
                        </button>
                    ))}
                </div>

                {error && (
                    <div className="rounded-lg bg-red-500/10 border border-red-500/20 p-2.5 text-xs text-red-400">
                        {error}
                    </div>
                )}

                <div className="space-y-1 max-h-80 overflow-y-auto">
                    {loading ? (
                        <div className="flex items-center justify-center py-10 text-gray-500 text-sm">
                            <RefreshCw className="w-4 h-4 animate-spin mr-2" /> Fetching contracts...
                        </div>
                    ) : contracts.length === 0 ? (
                        <div className="text-center py-10 text-gray-500 text-sm">Select an underlying with active futures contracts.</div>
                    ) : contracts.map((contract) => {
                        const quote = quotes[contract.contract_symbol] || {};
                        const ltp = quote.ltp ?? quote.price ?? null;
                        const alreadyAdded = watchlistItems.some(
                            (item) => item.contract_symbol?.toUpperCase() === contract.contract_symbol.toUpperCase()
                        );
                        return (
                            <button
                                key={contract.contract_symbol}
                                onClick={() => !alreadyAdded && handleSelectContract(contract.contract_symbol)}
                                disabled={alreadyAdded}
                                className={cn(
                                    'w-full text-left px-3 py-2.5 rounded-lg transition-colors',
                                    alreadyAdded
                                        ? 'opacity-50 cursor-not-allowed bg-surface-800/30'
                                        : 'hover:bg-surface-800/60 active:bg-primary-500/20'
                                )}
                            >
                                <div className="flex items-start justify-between gap-3">
                                    <div className="min-w-0">
                                        <p className="text-sm font-semibold text-heading truncate">{contract.contract_symbol}</p>
                                        <p className="text-xs text-gray-500 mt-0.5">
                                            {formatExpiry(contract.expiry_date)} | Lot {formatQuantity(contract.lot_size)}
                                        </p>
                                    </div>
                                    <div className="text-right shrink-0">
                                        <p className="text-xs text-gray-500">{contract.exchange || 'NFO'}</p>
                                        <p className="text-sm font-price text-heading tabular-nums">{ltp != null ? formatPrice(ltp) : '--'}</p>
                                    </div>
                                </div>
                                {alreadyAdded && <p className="text-xs text-gray-500 mt-1">Already in watchlist</p>}
                            </button>
                        );
                    })}
                </div>
            </div>
        </Modal>
    );
}
