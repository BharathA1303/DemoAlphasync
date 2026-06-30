import { Fragment, useState, useEffect, useMemo, useCallback, useRef } from 'react';
import {
    BarChart3,
    Search,
    RefreshCw,
    Funnel,
    Download,
    CalendarDays,
    ChevronsUpDown,
    ChevronUp,
    ChevronDown,
    AlertCircle,
    Clock3,
    CheckCircle2,
} from 'lucide-react';
import api from '../services/api';
import { formatCurrency, cleanSymbol, formatQuantity, formatPercent, formatDate } from '../utils/formatters';
import { Skeleton } from '../components/ui';
import { cn } from '../utils/cn';
import { usePortfolioStore } from '../store/usePortfolioStore';

const ORDER_TABS = [
    { key: 'pending', label: 'Pending' },
    { key: 'all', label: 'All Orders' },
    { key: 'filled', label: 'Filled' },
];

const SOURCE_FILTERS = [
    { key: 'all', label: 'All' },
    { key: 'manual', label: 'Manual' },
    { key: 'zeroloss', label: 'Alpha AutoTrade' },
    { key: 'algo', label: 'Algo' },
];

const DATE_FILTERS = [
    { key: 'today', label: 'Today' },
    { key: 'week', label: 'This Week' },
    { key: 'month', label: 'This Month' },
    { key: 'custom', label: 'Custom' },
];

const PENDING_STATUSES = new Set(['OPEN', 'PENDING', 'TRIGGER_PENDING', 'AMO_RECEIVED', 'MODIFY_PENDING', 'PARTIALLY_FILLED']);
const FILLED_STATUSES = new Set(['FILLED', 'COMPLETE', 'EXECUTED']);
const REJECTED_STATUSES = new Set(['REJECTED', 'CANCELLED', 'EXPIRED']);

const normalizeStatus = (status) => String(status || '').toUpperCase();
const normalizeSymbol = (symbol) => String(symbol || '').trim();
const normalizeSide = (side) => String(side || '').toUpperCase();
const normalizeProduct = (product) => String(product || '').toUpperCase();

function parseOrderTimestamp(order) {
    const raw = order.executed_at || order.updated_at || order.created_at || order.time || null;
    if (!raw) return null;
    const normalizedRaw =
        typeof raw === 'string' && !/[zZ]|[+\-]\d{2}:?\d{2}$/.test(raw)
            ? `${raw}Z`
            : raw;
    const date = new Date(normalizedRaw);
    return Number.isNaN(date.getTime()) ? null : date;
}

function formatOrderTime(ts) {
    if (!ts) return '—';
    return ts
        .toLocaleString('en-IN', {
            day: '2-digit',
            month: 'short',
            hour: 'numeric',
            minute: '2-digit',
            hour12: true,
        })
        .replace(',', '');
}

function toOrderTypeLabel(type) {
    const normalized = String(type || '').toUpperCase();
    if (normalized === 'STOP_LOSS') return 'SL';
    if (normalized === 'STOP_LOSS_LIMIT') return 'SL-M';
    if (normalized === 'TAKE_PROFIT') return 'TP';
    if (normalized === 'BRACKET') return 'BRACKET';
    return normalized || '—';
}

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function resolveOrderId(order) {
    const candidates = [order?.id, order?.order_id, order?.uid];
    for (const candidate of candidates) {
        const value = String(candidate ?? '').trim();
        if (UUID_REGEX.test(value)) return value;
    }
    return null;
}

function getStatusKind(status) {
    const normalized = normalizeStatus(status);
    if (FILLED_STATUSES.has(normalized)) return 'filled';
    if (PENDING_STATUSES.has(normalized)) return 'pending';
    if (REJECTED_STATUSES.has(normalized)) return 'rejected';
    return 'other';
}

function isWithinDateRange(ts, range, fromDate, toDate) {
    if (!ts) return false;

    const now = new Date();
    const timeValue = ts.getTime();

    if (range === 'today') {
        const start = new Date(now);
        start.setHours(0, 0, 0, 0);
        const end = new Date(now);
        end.setHours(23, 59, 59, 999);
        return timeValue >= start.getTime() && timeValue <= end.getTime();
    }

    if (range === 'week') {
        const start = new Date(now);
        const day = (start.getDay() + 6) % 7;
        start.setDate(start.getDate() - day);
        start.setHours(0, 0, 0, 0);
        return timeValue >= start.getTime() && timeValue <= now.getTime();
    }

    if (range === 'month') {
        const start = new Date(now.getFullYear(), now.getMonth(), 1);
        start.setHours(0, 0, 0, 0);
        return timeValue >= start.getTime() && timeValue <= now.getTime();
    }

    if (range === 'custom') {
        const hasFrom = Boolean(fromDate);
        const hasTo = Boolean(toDate);
        if (!hasFrom && !hasTo) return true;

        const start = hasFrom ? new Date(`${fromDate}T00:00:00`) : null;
        const end = hasTo ? new Date(`${toDate}T23:59:59.999`) : null;

        if (start && Number.isNaN(start.getTime())) return false;
        if (end && Number.isNaN(end.getTime())) return false;

        if (start && timeValue < start.getTime()) return false;
        if (end && timeValue > end.getTime()) return false;
        return true;
    }

    return true;
}

function getSortValue(order, key) {
    if (key === 'symbol') return cleanSymbol(order.symbol || '').toUpperCase();
    if (key === 'side') return order.side_norm;
    if (key === 'qty') return Number(order.display_qty || 0);
    if (key === 'avgPrice') return Number(order.avg_price ?? 0);
    if (key === 'orderType') return order.order_type_display;
    if (key === 'product') return order.product_norm;
    if (key === 'time') return Number(order.tsMs || 0);
    if (key === 'pnl') return Number(order.pnl_value ?? Number.NEGATIVE_INFINITY);
    if (key === 'status') return order.status_norm;
    return Number(order.tsMs || 0);
}

function csvEscape(value) {
    const text = value == null ? '' : String(value);
    if (/[",\n]/.test(text)) {
        return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
}

function formatCustomDateLabel(value) {
    if (!value) return 'DD MMM YYYY';
    const date = new Date(`${value}T00:00:00`);
    return Number.isNaN(date.getTime()) ? 'DD MMM YYYY' : formatDate(date);
}

function isValidPnlNumber(value) {
    const num = Number(value);
    return Number.isFinite(num) ? num : 0;
}

export default function OrdersPage() {
    const orders = usePortfolioStore((s) => s.orders) || [];
    const holdings = usePortfolioStore((s) => s.holdings) || [];
    const refreshPortfolio = usePortfolioStore((s) => s.refreshPortfolio);
    const portfolioSummary = usePortfolioStore((s) => s.summary);

    const [activeTab, setActiveTab] = useState('all');
    const [sourceFilter, setSourceFilter] = useState('all');
    const [dateRange, setDateRange] = useState('today');
    const [customFromDate, setCustomFromDate] = useState('');
    const [customToDate, setCustomToDate] = useState('');
    const [sideFilter, setSideFilter] = useState('all');
    const [productFilter, setProductFilter] = useState('all');
    const [searchQuery, setSearchQuery] = useState('');
    const [sortConfig, setSortConfig] = useState({ key: 'time', direction: 'desc' });
    const [isRefreshing, setIsRefreshing] = useState(true);
    const [lastUpdatedAt, setLastUpdatedAt] = useState(null);
    const [expandedRowId, setExpandedRowId] = useState(null);
    const [cancelLoadingId, setCancelLoadingId] = useState(null);
    const [editingRowId, setEditingRowId] = useState(null);
    const [editDraft, setEditDraft] = useState({ price: '', quantity: '', triggerPrice: '' });
    const [rowErrors, setRowErrors] = useState({});
    const [flashRows, setFlashRows] = useState({});

    const initializedRef = useRef(false);
    const previousOrderIdsRef = useRef(new Set());
    const customFromInputRef = useRef(null);
    const customToInputRef = useRef(null);

    const loadOrders = useCallback(async () => {
        setIsRefreshing(true);
        try {
            await refreshPortfolio();
            setLastUpdatedAt(new Date());
        } finally {
            setIsRefreshing(false);
        }
    }, [refreshPortfolio]);

    useEffect(() => {
        loadOrders();
    }, [loadOrders]);

    const normalizedOrders = useMemo(() => {
        return (orders || []).map((order, index) => {
            const ts = parseOrderTimestamp(order);
            const avgPriceRaw = order.filled_price ?? order.average_price ?? order.price;
            const quantityRaw = order.quantity ?? order.filled_quantity ?? order.executed_quantity ?? 0;
            const pnlRaw = order.pnl ?? order.realized_pnl ?? order.pnl_amount ?? null;
            const orderTypeRaw = order.order_type || order.type || null;
            const sideNorm = normalizeSide(order.side);
            const statusNorm = normalizeStatus(order.status);
            const strategyTag = String(order.tag || order.strategy || '').toUpperCase();
            const exchangeNorm = String(order.exchange || '').toUpperCase() || (String(order.symbol || '').endsWith('.BO') ? 'BSE' : 'NSE');

            return {
                ...order,
                uid: String(order.id ?? order.order_id ?? order.exchange_order_id ?? `${order.symbol || 'ORD'}-${index}`),
                symbol_norm: normalizeSymbol(order.symbol),
                side_norm: sideNorm,
                status_norm: statusNorm,
                strategy_tag: strategyTag,
                product_norm: normalizeProduct(order.product_type),
                exchange_norm: exchangeNorm,
                order_type_display: toOrderTypeLabel(orderTypeRaw),
                ts,
                tsMs: ts ? ts.getTime() : 0,
                display_qty: Number(quantityRaw || 0),
                avg_price: avgPriceRaw == null ? null : Number(avgPriceRaw),
                pnl_raw_value: pnlRaw == null || Number.isNaN(Number(pnlRaw)) ? null : Number(pnlRaw),
            };
        });
    }, [orders]);

    const derivedOrderPnlById = useMemo(() => {
        const books = new Map();
        const pnlById = new Map();

        const ordered = [...normalizedOrders].sort((a, b) => {
            if (a.tsMs !== b.tsMs) return a.tsMs - b.tsMs;
            return a.uid.localeCompare(b.uid);
        });

        ordered.forEach((order) => {
            const kind = getStatusKind(order.status_norm);
            const qty = Number(order.display_qty ?? 0);
            const price = Number(order.avg_price ?? NaN);
            const side = order.side_norm;
            const symbol = cleanSymbol(order.symbol_norm || order.symbol || '').toUpperCase();

            if (kind !== 'filled' || !symbol || !Number.isFinite(qty) || qty <= 0 || !Number.isFinite(price) || price <= 0) {
                return;
            }

            if (!books.has(symbol)) {
                books.set(symbol, { longs: [], shorts: [] });
            }

            const book = books.get(symbol);
            let remaining = qty;
            let realized = 0;
            let matchedQty = 0;

            if (side === 'BUY') {
                while (remaining > 0 && book.shorts.length > 0) {
                    const lot = book.shorts[0];
                    const closeQty = Math.min(remaining, lot.qty);
                    realized += (lot.price - price) * closeQty;
                    matchedQty += closeQty;
                    lot.qty -= closeQty;
                    remaining -= closeQty;
                    if (lot.qty <= 0) book.shorts.shift();
                }

                if (remaining > 0) {
                    book.longs.push({ qty: remaining, price });
                }
            } else if (side === 'SELL') {
                while (remaining > 0 && book.longs.length > 0) {
                    const lot = book.longs[0];
                    const closeQty = Math.min(remaining, lot.qty);
                    realized += (price - lot.price) * closeQty;
                    matchedQty += closeQty;
                    lot.qty -= closeQty;
                    remaining -= closeQty;
                    if (lot.qty <= 0) book.longs.shift();
                }

                if (remaining > 0) {
                    book.shorts.push({ qty: remaining, price });
                }
            }

            if (matchedQty > 0) {
                pnlById.set(order.uid, realized);
            }
        });

        return pnlById;
    }, [normalizedOrders]);

    const derivedRealizedPnl = useMemo(() => {
        return [...derivedOrderPnlById.values()].reduce(
            (sum, value) => sum + (Number.isFinite(Number(value)) ? Number(value) : 0),
            0
        );
    }, [derivedOrderPnlById]);

    const livePriceBySymbol = useMemo(() => {
        const symbolPriceMap = new Map();
        (holdings || []).forEach((holding) => {
            const symbolKey = cleanSymbol(holding?.symbol || '').toUpperCase();
            const currentPrice = Number(
                holding?.current_price ?? holding?.ltp ?? holding?.last_price ?? NaN
            );
            if (!symbolKey || !Number.isFinite(currentPrice) || currentPrice <= 0) return;
            symbolPriceMap.set(symbolKey, currentPrice);
        });
        return symbolPriceMap;
    }, [holdings]);

    const holdingMetricsBySymbol = useMemo(() => {
        const metricsMap = new Map();
        (holdings || []).forEach((holding) => {
            const symbolKey = cleanSymbol(holding?.symbol || '').toUpperCase();
            const holdingQty = Number(holding?.quantity ?? 0);
            const holdingPnl = Number(holding?.pnl ?? NaN);
            if (!symbolKey || !Number.isFinite(holdingQty) || holdingQty === 0 || !Number.isFinite(holdingPnl)) return;
            metricsMap.set(symbolKey, {
                qty: Math.abs(holdingQty),
                pnl: holdingPnl,
            });
        });
        return metricsMap;
    }, [holdings]);

    const resolvedOrders = useMemo(() => {
        return normalizedOrders.map((order) => {
            const backendPnl = Number(order.pnl ?? order.realized_pnl ?? NaN);
            if (Number.isFinite(backendPnl)) {
                return { ...order, pnl_value: backendPnl };
            }

            const derivedPnl = Number(derivedOrderPnlById.get(order.uid));
            if (Number.isFinite(derivedPnl)) {
                return { ...order, pnl_value: derivedPnl };
            }

            if (order.pnl_raw_value != null && Number.isFinite(Number(order.pnl_raw_value))) {
                return { ...order, pnl_value: Number(order.pnl_raw_value) };
            }

            const symbolKey = cleanSymbol(order.symbol_norm || order.symbol || '').toUpperCase();
            const holdingMetrics = holdingMetricsBySymbol.get(symbolKey);
            const livePrice = Number(livePriceBySymbol.get(symbolKey));
            const qty = Number(order.display_qty ?? 0);
            const avgPrice = Number(order.avg_price ?? NaN);
            const statusKind = getStatusKind(order.status_norm);

            if (
                statusKind === 'filled' &&
                holdingMetrics &&
                Number.isFinite(holdingMetrics.qty) &&
                holdingMetrics.qty > 0 &&
                Number.isFinite(holdingMetrics.pnl) &&
                Number.isFinite(qty) &&
                qty > 0
            ) {
                const proportionalPnl = holdingMetrics.pnl * (qty / holdingMetrics.qty);
                return { ...order, pnl_value: isValidPnlNumber(proportionalPnl) };
            }

            if (
                statusKind === 'filled' &&
                Number.isFinite(livePrice) &&
                Number.isFinite(qty) &&
                qty > 0 &&
                Number.isFinite(avgPrice) &&
                avgPrice > 0
            ) {
                const livePnl = order.side_norm === 'SELL'
                    ? (avgPrice - livePrice) * qty
                    : (livePrice - avgPrice) * qty;
                return { ...order, pnl_value: isValidPnlNumber(livePnl) };
            }

            return { ...order, pnl_value: isValidPnlNumber(order.pnl_raw_value) };
        });
    }, [normalizedOrders, derivedOrderPnlById, holdingMetricsBySymbol, livePriceBySymbol]);

    const backendRealizedPnl = Number(portfolioSummary?.realized_pnl);
    const realizedPnl = Number.isFinite(backendRealizedPnl) && backendRealizedPnl !== 0 ? backendRealizedPnl : derivedRealizedPnl;

    useEffect(() => {
        const ids = normalizedOrders.map((o) => o.uid);
        if (!initializedRef.current) {
            previousOrderIdsRef.current = new Set(ids);
            initializedRef.current = true;
            return;
        }

        const previous = previousOrderIdsRef.current;
        const incoming = normalizedOrders.filter((order) => !previous.has(order.uid));
        if (incoming.length > 0) {
            setFlashRows((prev) => {
                const next = { ...prev };
                incoming.forEach((order) => {
                    next[order.uid] = getStatusKind(order.status_norm) === 'rejected' ? 'rejected' : 'new';
                });
                return next;
            });

            window.setTimeout(() => {
                setFlashRows((prev) => {
                    const next = { ...prev };
                    incoming.forEach((order) => delete next[order.uid]);
                    return next;
                });
            }, 1800);
        }

        previousOrderIdsRef.current = new Set(ids);
    }, [normalizedOrders]);

    const filteredBaseOrders = useMemo(() => {
        const query = searchQuery.trim().toUpperCase();

        return resolvedOrders.filter((order) => {
            if (sourceFilter === 'manual') {
                const isTagged = order.strategy_tag === 'ALGO' || order.strategy_tag === 'ZEROLOSS';
                if (isTagged) return false;
            } else if (sourceFilter !== 'all' && order.strategy_tag !== sourceFilter.toUpperCase()) {
                return false;
            }

            if (!isWithinDateRange(order.ts, dateRange, customFromDate, customToDate)) {
                return false;
            }

            if (sideFilter !== 'all' && order.side_norm !== sideFilter) {
                return false;
            }

            if (productFilter !== 'all' && order.product_norm !== productFilter) {
                return false;
            }

            if (!query) return true;

            const haystack = [
                cleanSymbol(order.symbol_norm || ''),
                order.side_norm,
                order.status_norm,
                order.order_type_display,
                order.product_norm,
            ]
                .filter(Boolean)
                .join(' ')
                .toUpperCase();

            return haystack.includes(query);
        });
    }, [resolvedOrders, sourceFilter, dateRange, customFromDate, customToDate, sideFilter, productFilter, searchQuery]);

    const tabCounts = useMemo(() => {
        return filteredBaseOrders.reduce(
            (acc, order) => {
                const kind = getStatusKind(order.status_norm);
                if (kind === 'pending') acc.pending += 1;
                if (kind === 'filled') acc.filled += 1;
                acc.all += 1;
                return acc;
            },
            { pending: 0, all: 0, filled: 0 }
        );
    }, [filteredBaseOrders]);

    const visibleByTab = useMemo(() => {
        if (activeTab === 'pending') {
            return filteredBaseOrders.filter((order) => getStatusKind(order.status_norm) === 'pending');
        }
        if (activeTab === 'filled') {
            return filteredBaseOrders.filter((order) => getStatusKind(order.status_norm) === 'filled');
        }
        return filteredBaseOrders;
    }, [filteredBaseOrders, activeTab]);

    const sortedVisibleOrders = useMemo(() => {
        const next = [...visibleByTab];
        next.sort((a, b) => {
            const aValue = getSortValue(a, sortConfig.key);
            const bValue = getSortValue(b, sortConfig.key);

            if (aValue == null && bValue == null) return 0;
            if (aValue == null) return 1;
            if (bValue == null) return -1;

            if (typeof aValue === 'number' && typeof bValue === 'number') {
                return sortConfig.direction === 'asc' ? aValue - bValue : bValue - aValue;
            }

            const compare = String(aValue).localeCompare(String(bValue), 'en-IN', { sensitivity: 'base' });
            return sortConfig.direction === 'asc' ? compare : -compare;
        });
        return next;
    }, [visibleByTab, sortConfig]);

    const pairedSymbols = useMemo(() => {
        const bySymbol = new Map();
        sortedVisibleOrders.forEach((order) => {
            const key = cleanSymbol(order.symbol_norm || order.symbol || '');
            if (!bySymbol.has(key)) {
                bySymbol.set(key, { buy: false, sell: false });
            }
            const current = bySymbol.get(key);
            if (order.side_norm === 'BUY') current.buy = true;
            if (order.side_norm === 'SELL') current.sell = true;
        });

        return new Set(
            [...bySymbol.entries()]
                .filter(([, sideState]) => sideState.buy && sideState.sell)
                .map(([symbol]) => symbol)
        );
    }, [sortedVisibleOrders]);

    const summary = useMemo(() => {
        const totalOrders = filteredBaseOrders.length;
        const filled = filteredBaseOrders.filter((o) => getStatusKind(o.status_norm) === 'filled').length;
        const pending = filteredBaseOrders.filter((o) => getStatusKind(o.status_norm) === 'pending').length;
        const rejected = filteredBaseOrders.filter((o) => getStatusKind(o.status_norm) === 'rejected').length;
        const grossTurnover = filteredBaseOrders
            .filter((o) => getStatusKind(o.status_norm) === 'filled')
            .reduce((sum, order) => {
                const qty = Number(order.display_qty || 0);
                const price = Number(order.avg_price || 0);
                if (!Number.isFinite(qty) || !Number.isFinite(price)) return sum;
                return sum + qty * price;
            }, 0);

        return {
            totalOrders,
            filled,
            pending,
            rejected,
            realizedPnl,
            grossTurnover,
            fillRate: totalOrders > 0 ? (filled / totalOrders) * 100 : 0,
        };
    }, [filteredBaseOrders, realizedPnl]);

    const visibleGrossTurnover = useMemo(() => {
        return sortedVisibleOrders
            .filter((o) => getStatusKind(o.status_norm) === 'filled')
            .reduce((sum, order) => {
                const qty = Number(order.display_qty || 0);
                const price = Number(order.avg_price || 0);
                if (!Number.isFinite(qty) || !Number.isFinite(price)) return sum;
                return sum + qty * price;
            }, 0);
    }, [sortedVisibleOrders]);

    const onSort = useCallback((key) => {
        setSortConfig((prev) => {
            if (prev.key === key) {
                return { key, direction: prev.direction === 'asc' ? 'desc' : 'asc' };
            }
            return { key, direction: key === 'time' ? 'desc' : 'asc' };
        });
    }, []);

    const exportCsv = useCallback(() => {
        const headers = ['Symbol', 'Side', 'Qty', 'Price', 'Type', 'Product', 'Time', 'P&L', 'Status'];
        const rows = sortedVisibleOrders.map((order) => [
            cleanSymbol(order.symbol_norm || order.symbol || ''),
            order.side_norm || '—',
            order.display_qty ?? '—',
            order.avg_price == null ? '—' : Number(order.avg_price).toFixed(2),
            order.order_type_display || '—',
            order.product_norm || '—',
            formatOrderTime(order.ts),
            order.pnl_value == null ? '—' : Number(order.pnl_value).toFixed(2),
            order.status_norm || '—',
        ]);

        const csv = [headers, ...rows].map((cols) => cols.map(csvEscape).join(',')).join('\n');
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);

        const anchor = document.createElement('a');
        const dateStamp = new Date().toISOString().slice(0, 10);
        anchor.href = url;
        anchor.download = `orders_${dateStamp}.csv`;
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        URL.revokeObjectURL(url);
    }, [sortedVisibleOrders]);

    const clearRowError = useCallback((uid) => {
        setRowErrors((prev) => {
            if (!prev[uid]) return prev;
            const next = { ...prev };
            delete next[uid];
            return next;
        });
    }, []);

    const openModifyEditor = useCallback((order) => {
        setExpandedRowId(order.uid);
        setEditingRowId(order.uid);
        clearRowError(order.uid);
        setEditDraft({
            price: order.avg_price == null ? '' : String(order.avg_price),
            quantity: String(order.display_qty ?? ''),
            triggerPrice: order.trigger_price == null ? '' : String(order.trigger_price),
        });
    }, [clearRowError]);

    const handleModifySubmit = useCallback(async (order) => {
        const targetId = resolveOrderId(order);
        if (!targetId) {
            setRowErrors((prev) => ({ ...prev, [order.uid]: 'Order ID is missing or invalid for modify request.' }));
            return;
        }

        const canonicalOrderType = String(order.order_type || '').toUpperCase();

        const quantity = Number(editDraft.quantity);
        const price = Number(editDraft.price);
        const triggerPrice = Number(editDraft.triggerPrice);

        if (!Number.isFinite(quantity) || quantity <= 0) {
            setRowErrors((prev) => ({ ...prev, [order.uid]: 'Please enter a valid quantity.' }));
            return;
        }

        const payload = { quantity };
        if (canonicalOrderType !== 'MARKET') {
            if (Number.isFinite(price) && price > 0) payload.price = price;
        }

        if (['STOP_LOSS', 'STOP_LOSS_LIMIT', 'BRACKET'].includes(canonicalOrderType)) {
            if (!Number.isFinite(triggerPrice) || triggerPrice <= 0) {
                setRowErrors((prev) => ({ ...prev, [order.uid]: 'Please enter a valid trigger price.' }));
                return;
            }
            payload.trigger_price = triggerPrice;
        }

        clearRowError(order.uid);

        try {
            const response = await api.patch(`/orders/${encodeURIComponent(String(targetId))}`, payload);
            const updated = response?.data?.order;
            usePortfolioStore.setState((state) => ({
                orders: (state.orders || []).map((row) => {
                    const rowId = row.id ?? row.order_id ?? row.exchange_order_id;
                    if (String(rowId) !== String(targetId)) return row;
                    return {
                        ...row,
                        quantity: updated?.quantity ?? quantity,
                        price: updated?.price ?? (Number.isFinite(price) && price > 0 ? price : row.price),
                        trigger_price: updated?.trigger_price ?? row.trigger_price,
                        updated_at: updated?.updated_at ?? new Date().toISOString(),
                    };
                }),
            }));
            setEditingRowId(null);
        } catch (err) {
            const message = err?.response?.data?.detail || err?.response?.data?.error || err?.message || 'Modify order failed.';
            setRowErrors((prev) => ({ ...prev, [order.uid]: message }));
        }
    }, [clearRowError, editDraft]);

    const handleCancelOrder = useCallback(async (order) => {
        const targetId = resolveOrderId(order);
        if (!targetId) {
            setRowErrors((prev) => ({ ...prev, [order.uid]: 'Order ID is missing or invalid for cancel request.' }));
            return;
        }

        clearRowError(order.uid);
        setCancelLoadingId(order.uid);

        const previousOrders = usePortfolioStore.getState().orders;

        usePortfolioStore.setState((state) => ({
            orders: (state.orders || []).map((row) => {
                const rowId = row.id ?? row.order_id ?? row.exchange_order_id;
                if (String(rowId) !== String(targetId)) return row;
                return {
                    ...row,
                    status: 'CANCELLED',
                    updated_at: new Date().toISOString(),
                };
            }),
        }));

        try {
            await api.delete(`/orders/${encodeURIComponent(String(targetId))}`);
        } catch (err) {
            usePortfolioStore.setState({ orders: previousOrders });
            const message = err?.response?.data?.detail || err?.response?.data?.error || err?.message || 'Cancel order failed.';
            setRowErrors((prev) => ({ ...prev, [order.uid]: message }));
        } finally {
            setCancelLoadingId(null);
        }
    }, [clearRowError]);

    const sortLabel = useMemo(() => {
        if (sortConfig.key === 'time' && sortConfig.direction === 'desc') return 'Latest first';
        return `${sortConfig.key} ${sortConfig.direction}`;
    }, [sortConfig]);

    const emptyStateMessage = useMemo(() => {
        if (searchQuery.trim()) {
            return {
                title: 'No matching orders for your current filters',
                subtitle: 'Try another symbol or broaden your filters.',
                icon: BarChart3,
            };
        }

        if (activeTab === 'pending') {
            return {
                title: 'No pending orders — all clear!',
                subtitle: 'All your open requests are already resolved.',
                icon: Clock3,
            };
        }

        if (activeTab === 'filled') {
            return {
                title: 'No filled orders yet today',
                subtitle: 'Executed trades will appear here once filled.',
                icon: CheckCircle2,
            };
        }

        return {
            title: 'No orders today. Place your first trade from the terminal',
            subtitle: 'Your orderbook will update here in real time.',
            icon: BarChart3,
        };
    }, [activeTab, searchQuery]);

    const openDatePicker = useCallback((inputRef) => {
        const input = inputRef.current;
        if (!input) return;

        if (typeof input.showPicker === 'function') {
            input.showPicker();
            return;
        }

        input.click();
    }, []);

    if (isRefreshing && normalizedOrders.length === 0) {
        return (
            <div className="p-4 lg:p-6 space-y-6">
                <Skeleton variant="text" className="h-8 w-48" />
                <Skeleton variant="table-row" count={8} />
            </div>
        );
    }

    const EmptyIcon = emptyStateMessage.icon;

    return (
        <div className="p-4 lg:p-6 space-y-5 animate-fade-in">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <h1 className="text-2xl font-display font-semibold text-heading">Orders</h1>
                <div className="flex items-center gap-2">
                    <button
                        type="button"
                        onClick={exportCsv}
                        className="inline-flex items-center gap-2 rounded-lg border border-edge/10 bg-surface-900/40 px-3 py-2 text-xs font-semibold text-heading transition-colors hover:border-edge/20"
                    >
                        <Download className="h-3.5 w-3.5" />
                        Export
                    </button>
                    <button
                        type="button"
                        onClick={loadOrders}
                        disabled={isRefreshing}
                        className="inline-flex items-center gap-2 rounded-lg border border-edge/10 bg-surface-900/40 px-3 py-2 text-xs font-semibold text-heading transition-colors hover:border-edge/20 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                        <RefreshCw className={cn('h-3.5 w-3.5', isRefreshing && 'animate-spin')} />
                        Refresh
                    </button>
                    <span className="text-[11px] text-gray-500">
                        {lastUpdatedAt
                            ? `Updated ${lastUpdatedAt.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}`
                            : '—'}
                    </span>
                </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3">
                <div className="glass-card p-4">
                    <p className="text-[11px] uppercase tracking-wide text-gray-500">Total Orders</p>
                    <p className="mt-1 text-xl font-semibold text-heading tabular-nums">{formatQuantity(summary.totalOrders)}</p>
                    <p className="mt-1 text-[11px] text-gray-500">Today</p>
                </div>
                <div className="glass-card p-4">
                    <p className="text-[11px] uppercase tracking-wide text-gray-500">Filled</p>
                    <p className="mt-1 text-xl font-semibold text-heading tabular-nums">{formatQuantity(summary.filled)}</p>
                    <p className="mt-1 text-[11px] text-gray-500">{formatPercent(summary.fillRate, 0, false)} fill rate</p>
                </div>
                <div className="glass-card p-4">
                    <p className="text-[11px] uppercase tracking-wide text-gray-500">Pending</p>
                    <p className="mt-1 text-xl font-semibold text-heading tabular-nums">{formatQuantity(summary.pending)}</p>
                    <p className="mt-1 text-[11px] text-gray-500">{summary.pending > 0 ? `${summary.pending} open orders` : 'No open orders'}</p>
                </div>
                <div className="glass-card p-4">
                    <p className="text-[11px] uppercase tracking-wide text-gray-500">Rejected</p>
                    <p className={cn('mt-1 text-xl font-semibold tabular-nums', summary.rejected > 0 ? 'text-loss' : 'text-heading')}>
                        {formatQuantity(summary.rejected)}
                    </p>
                    <p className="mt-1 text-[11px] text-gray-500">{summary.rejected > 0 ? 'Needs review' : 'No rejections'}</p>
                </div>
                <div className="glass-card p-4">
                    <p className="text-[11px] uppercase tracking-wide text-gray-500">Realised P&amp;L</p>
                    <p className={cn('mt-1 text-xl font-semibold tabular-nums', summary.realizedPnl >= 0 ? 'text-profit' : 'text-loss')}>
                        {summary.realizedPnl > 0 ? '+' : ''}{formatCurrency(summary.realizedPnl)}
                    </p>
                    <p className="mt-1 text-[11px] text-gray-500">Gross turnover {formatCurrency(summary.grossTurnover)}</p>
                </div>
            </div>

            <div className="glass-card p-3 lg:p-4 space-y-3">
                <div className="flex flex-wrap items-center gap-2 lg:gap-3">
                    <div className="flex flex-wrap items-center gap-2">
                        {ORDER_TABS.map((tab) => (
                            <button
                                key={tab.key}
                                type="button"
                                onClick={() => setActiveTab(tab.key)}
                                className={cn(
                                    'rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors',
                                    activeTab === tab.key
                                        ? 'border-primary-500/30 bg-primary-500/15 text-primary-600 shadow-sm'
                                        : 'border-edge/10 bg-surface-900/40 text-gray-500 hover:border-edge/20 hover:text-heading'
                                )}
                            >
                                {tab.label}
                                <span className="ml-1.5 text-[10px] font-mono opacity-80">
                                    {tab.key === 'pending' ? tabCounts.pending : tab.key === 'filled' ? tabCounts.filled : tabCounts.all}
                                </span>
                            </button>
                        ))}
                    </div>

                    <div className="ml-auto flex flex-wrap items-center gap-2">
                        <span className="inline-flex items-center gap-1 text-[11px] text-gray-500">
                            <Funnel className="h-3 w-3" />
                            Filter
                        </span>
                        {SOURCE_FILTERS.map((filter) => (
                            <button
                                key={filter.key}
                                type="button"
                                onClick={() => setSourceFilter(filter.key)}
                                aria-pressed={sourceFilter === filter.key}
                                className={cn(
                                    'rounded border px-2.5 py-1 text-[11px] font-medium transition-colors',
                                    sourceFilter === filter.key
                                        ? 'border-primary-500/30 bg-primary-500/15 text-primary-600 shadow-sm'
                                        : 'border-edge/10 bg-surface-900/40 text-gray-500 hover:border-edge/20 hover:text-heading'
                                )}
                            >
                                {filter.label}
                            </button>
                        ))}
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                    <div className="inline-flex items-center rounded-lg border border-edge/10 bg-surface-900/30 p-1">
                        <span className="px-2 text-[11px] text-gray-500 inline-flex items-center gap-1">
                            <CalendarDays className="h-3 w-3" /> Date
                        </span>
                        {DATE_FILTERS.map((filter) => (
                            <button
                                key={filter.key}
                                type="button"
                                onClick={() => setDateRange(filter.key)}
                                className={cn(
                                    'rounded px-2 py-1 text-[11px] font-medium transition-colors',
                                    dateRange === filter.key ? 'bg-primary-500/15 text-primary-600 shadow-sm' : 'text-gray-500 hover:text-heading'
                                )}
                            >
                                {filter.label}
                            </button>
                        ))}
                    </div>

                    {dateRange === 'custom' && (
                        <div className="flex items-center gap-2">
                            <button
                                type="button"
                                onClick={() => openDatePicker(customFromInputRef)}
                                className="inline-flex h-8 min-w-[132px] items-center justify-between gap-2 rounded-lg border border-edge/10 bg-surface-900/40 px-3 text-xs font-medium text-heading transition-colors hover:border-edge/20"
                            >
                                <span className={cn(customFromDate ? 'text-heading' : 'text-gray-500')}>
                                    {formatCustomDateLabel(customFromDate)}
                                </span>
                                <CalendarDays className="h-3.5 w-3.5 text-gray-500" />
                            </button>
                            <span className="text-[11px] text-gray-500">to</span>
                            <button
                                type="button"
                                onClick={() => openDatePicker(customToInputRef)}
                                className="inline-flex h-8 min-w-[132px] items-center justify-between gap-2 rounded-lg border border-edge/10 bg-surface-900/40 px-3 text-xs font-medium text-heading transition-colors hover:border-edge/20"
                            >
                                <span className={cn(customToDate ? 'text-heading' : 'text-gray-500')}>
                                    {formatCustomDateLabel(customToDate)}
                                </span>
                                <CalendarDays className="h-3.5 w-3.5 text-gray-500" />
                            </button>
                            <input
                                ref={customFromInputRef}
                                type="date"
                                value={customFromDate}
                                onChange={(e) => setCustomFromDate(e.target.value)}
                                className="sr-only"
                                tabIndex={-1}
                                aria-hidden="true"
                            />
                            <input
                                ref={customToInputRef}
                                type="date"
                                value={customToDate}
                                onChange={(e) => setCustomToDate(e.target.value)}
                                className="sr-only"
                                tabIndex={-1}
                                aria-hidden="true"
                            />
                        </div>
                    )}

                    <div className="inline-flex items-center rounded-lg border border-edge/10 bg-surface-900/30 p-1">
                        {['All', 'BUY', 'SELL'].map((value) => (
                            <button
                                key={value}
                                type="button"
                                onClick={() => setSideFilter(value === 'All' ? 'all' : value)}
                                aria-pressed={sideFilter === (value === 'All' ? 'all' : value)}
                                className={cn(
                                    'rounded px-2 py-1 text-[11px] font-medium transition-colors',
                                    sideFilter === (value === 'All' ? 'all' : value)
                                        ? 'bg-primary-500/15 text-primary-600 shadow-sm'
                                        : 'text-gray-500 hover:text-heading'
                                )}
                            >
                                {value}
                            </button>
                        ))}
                    </div>

                    <div className="inline-flex items-center rounded-lg border border-edge/10 bg-surface-900/30 p-1">
                        {['All', 'MIS', 'CNC', 'NRML'].map((value) => (
                            <button
                                key={value}
                                type="button"
                                onClick={() => setProductFilter(value === 'All' ? 'all' : value)}
                                aria-pressed={productFilter === (value === 'All' ? 'all' : value)}
                                className={cn(
                                    'rounded px-2 py-1 text-[11px] font-medium transition-colors',
                                    productFilter === (value === 'All' ? 'all' : value)
                                        ? 'bg-primary-500/15 text-primary-600 shadow-sm'
                                        : 'text-gray-500 hover:text-heading'
                                )}
                            >
                                {value}
                            </button>
                        ))}
                    </div>

                    <div className="relative ml-auto w-full lg:w-[340px]">
                        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                        <input
                            type="text"
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            placeholder="Search by symbol, side, or status..."
                            className="w-full rounded-lg border border-edge/10 bg-surface-800/60 py-2 pl-10 pr-3 text-sm text-heading placeholder-gray-500 focus:border-primary-500/30 focus:outline-none"
                        />
                    </div>
                </div>
            </div>

            {sortedVisibleOrders.length > 0 ? (
                <div className="glass-card overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="min-w-[1220px] w-full text-sm">
                            <thead className="border-b border-edge/5 bg-surface-900/30">
                                <tr className="text-[11px] uppercase tracking-wider text-gray-500">
                                    {[
                                        ['symbol', 'Symbol', 'text-left'],
                                        ['side', 'Side', 'text-left'],
                                        ['qty', 'Qty', 'text-right'],
                                        ['avgPrice', 'Avg Price', 'text-right'],
                                        ['orderType', 'Order Type', 'text-left'],
                                        ['product', 'Product', 'text-left'],
                                        ['time', 'Time', 'text-left'],
                                        ['pnl', 'P&L', 'text-right'],
                                        ['status', 'Status', 'text-left'],
                                    ].map(([key, label, align]) => (
                                        <th key={key} className={cn('px-4 py-3 font-semibold', align)}>
                                            <button
                                                type="button"
                                                onClick={() => onSort(key)}
                                                className="inline-flex items-center gap-1 text-inherit"
                                            >
                                                {label}
                                                {sortConfig.key === key ? (
                                                    sortConfig.direction === 'asc' ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
                                                ) : (
                                                    <ChevronsUpDown className="h-3 w-3 opacity-60" />
                                                )}
                                            </button>
                                        </th>
                                    ))}
                                    <th className="px-4 py-3 text-left font-semibold">Actions</th>
                                </tr>
                            </thead>

                            <tbody className="divide-y divide-edge/[0.04]">
                                {sortedVisibleOrders.map((order) => {
                                    const isPending = getStatusKind(order.status_norm) === 'pending';
                                    const isExpanded = expandedRowId === order.uid;
                                    const isEditing = editingRowId === order.uid;
                                    const pnlValue = order.pnl_value;
                                    const hasPair = pairedSymbols.has(cleanSymbol(order.symbol_norm || order.symbol || ''));

                                    return (
                                        <Fragment key={order.uid}>
                                            <tr
                                                onClick={() => setExpandedRowId((prev) => (prev === order.uid ? null : order.uid))}
                                                className={cn(
                                                    'cursor-pointer transition-colors hover:bg-overlay/[0.04]',
                                                    hasPair && 'border-l-2 border-primary-500/20',
                                                    flashRows[order.uid] === 'new' && 'bg-profit/10',
                                                    flashRows[order.uid] === 'rejected' && 'bg-loss/10'
                                                )}
                                            >
                                                <td className="px-4 py-3">
                                                    <div className="font-semibold text-heading">{cleanSymbol(order.symbol_norm || order.symbol || '—')}</div>
                                                    <div className="mt-0.5 text-[10px] uppercase text-gray-500">{order.exchange_norm || '—'}</div>
                                                </td>
                                                <td className="px-4 py-3">
                                                    <span className={cn(
                                                        'inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold',
                                                        order.side_norm === 'BUY' ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear'
                                                    )}>
                                                        {order.side_norm || '—'}
                                                    </span>
                                                </td>
                                                <td className="px-4 py-3 text-right font-mono text-heading">{formatQuantity(order.display_qty)}</td>
                                                <td className="px-4 py-3 text-right font-mono text-heading">{formatCurrency(order.avg_price)}</td>
                                                <td className="px-4 py-3">
                                                    <span className="inline-flex rounded-md border border-edge/10 bg-surface-900/40 px-2 py-0.5 text-[11px] text-gray-300">
                                                        {order.order_type_display || '—'}
                                                    </span>
                                                </td>
                                                <td className="px-4 py-3">
                                                    <span className="inline-flex rounded-md border border-edge/10 bg-surface-900/40 px-2 py-0.5 text-[11px] text-gray-300">
                                                        {order.product_norm || '—'}
                                                    </span>
                                                </td>
                                                <td className="px-4 py-3 text-xs text-gray-500">{formatOrderTime(order.ts)}</td>
                                                <td className="px-4 py-3 text-right font-mono">
                                                    <span className={cn('font-semibold', pnlValue > 0 ? 'text-profit' : pnlValue < 0 ? 'text-loss' : 'text-gray-500')}>
                                                        {pnlValue > 0 ? '+' : ''}{formatCurrency(pnlValue)}
                                                    </span>
                                                </td>
                                                <td className="px-4 py-3">
                                                    <span className={cn(
                                                        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium',
                                                        getStatusKind(order.status_norm) === 'filled' && 'border-profit/20 bg-profit/10 text-profit',
                                                        getStatusKind(order.status_norm) === 'pending' && 'border-primary-500/20 bg-primary-500/10 text-primary-600',
                                                        getStatusKind(order.status_norm) === 'rejected' && 'border-loss/20 bg-loss/10 text-loss',
                                                        getStatusKind(order.status_norm) === 'other' && 'border-edge/10 bg-surface-900/40 text-gray-400'
                                                    )}>
                                                        <span className={cn(
                                                            'h-1.5 w-1.5 rounded-full',
                                                            getStatusKind(order.status_norm) === 'filled' && 'bg-profit',
                                                            getStatusKind(order.status_norm) === 'pending' && 'bg-primary-500',
                                                            getStatusKind(order.status_norm) === 'rejected' && 'bg-loss',
                                                            getStatusKind(order.status_norm) === 'other' && 'bg-gray-500'
                                                        )} />
                                                        {order.status_norm || '—'}
                                                    </span>
                                                </td>
                                                <td className="px-4 py-3" onClick={(event) => event.stopPropagation()}>
                                                    {isPending ? (
                                                        <div className="flex flex-wrap items-center gap-2">
                                                            <button
                                                                type="button"
                                                                onClick={() => openModifyEditor(order)}
                                                                className="rounded border border-edge/10 bg-surface-900/50 px-2 py-1 text-[11px] font-medium text-heading hover:border-edge/20"
                                                            >
                                                                Modify
                                                            </button>
                                                            <button
                                                                type="button"
                                                                disabled={cancelLoadingId === order.uid}
                                                                onClick={() => handleCancelOrder(order)}
                                                                className="rounded border border-loss/20 bg-loss/10 px-2 py-1 text-[11px] font-medium text-loss hover:border-loss/30 disabled:opacity-60"
                                                            >
                                                                {cancelLoadingId === order.uid ? 'Cancelling...' : 'Cancel'}
                                                            </button>
                                                        </div>
                                                    ) : (
                                                        <span className="text-[11px] text-gray-500">—</span>
                                                    )}
                                                </td>
                                            </tr>

                                            {isExpanded && (
                                                <tr className="bg-surface-900/20">
                                                    <td colSpan={10} className="px-4 py-3">
                                                        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
                                                            <div className="rounded-lg border border-edge/10 bg-surface-900/40 p-3 text-xs text-gray-400 space-y-1">
                                                                <div>Order ID: <span className="text-heading">{order.id || order.order_id || 'N/A'}</span></div>
                                                                {order.exchange_order_id && <div>Exchange Order ID: <span className="text-heading">{order.exchange_order_id}</span></div>}
                                                                {order.validity && <div>Validity: <span className="text-heading">{order.validity}</span></div>}
                                                            </div>
                                                            <div className="rounded-lg border border-edge/10 bg-surface-900/40 p-3 text-xs text-gray-400 space-y-1">
                                                                {(order.trigger_price != null) && <div>Trigger Price: <span className="text-heading">{formatCurrency(order.trigger_price)}</span></div>}
                                                                <div>Created: <span className="text-heading">{formatOrderTime(parseOrderTimestamp({ created_at: order.created_at }))}</span></div>
                                                                <div>Updated: <span className="text-heading">{formatOrderTime(parseOrderTimestamp({ updated_at: order.updated_at }))}</span></div>
                                                            </div>
                                                            <div className="rounded-lg border border-edge/10 bg-surface-900/40 p-3 text-xs text-gray-400 space-y-1">
                                                                <div>Filled Qty: <span className="text-heading">{formatQuantity(order.filled_quantity ?? 0)}</span></div>
                                                                <div>Tag: <span className="text-heading">{order.strategy_tag || 'MANUAL'}</span></div>
                                                                {order.rejection_reason && <div>Rejection Reason: <span className="text-heading">{order.rejection_reason}</span></div>}
                                                            </div>
                                                        </div>

                                                        {isEditing && (
                                                            <div className="mt-3 rounded-lg border border-edge/10 bg-surface-900/40 p-3">
                                                                <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                                                                    <label className="text-xs text-gray-400">
                                                                        Price
                                                                        <input
                                                                            type="number"
                                                                            step="0.05"
                                                                            value={editDraft.price}
                                                                            onChange={(e) => setEditDraft((prev) => ({ ...prev, price: e.target.value }))}
                                                                            className="mt-1 h-8 w-full rounded border border-edge/10 bg-surface-900/40 px-2 text-xs text-heading"
                                                                        />
                                                                    </label>
                                                                    <label className="text-xs text-gray-400">
                                                                        Qty
                                                                        <input
                                                                            type="number"
                                                                            value={editDraft.quantity}
                                                                            onChange={(e) => setEditDraft((prev) => ({ ...prev, quantity: e.target.value }))}
                                                                            className="mt-1 h-8 w-full rounded border border-edge/10 bg-surface-900/40 px-2 text-xs text-heading"
                                                                        />
                                                                    </label>
                                                                    {['SL', 'SL-M'].includes(order.order_type_display) && (
                                                                        <label className="text-xs text-gray-400">
                                                                            Trigger Price
                                                                            <input
                                                                                type="number"
                                                                                step="0.05"
                                                                                value={editDraft.triggerPrice}
                                                                                onChange={(e) => setEditDraft((prev) => ({ ...prev, triggerPrice: e.target.value }))}
                                                                                className="mt-1 h-8 w-full rounded border border-edge/10 bg-surface-900/40 px-2 text-xs text-heading"
                                                                            />
                                                                        </label>
                                                                    )}
                                                                </div>

                                                                <div className="mt-3 flex items-center gap-2">
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => handleModifySubmit(order)}
                                                                        className="rounded border border-primary-500/20 bg-primary-500/10 px-3 py-1.5 text-xs font-semibold text-primary-600"
                                                                    >
                                                                        Save
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        onClick={() => setEditingRowId(null)}
                                                                        className="rounded border border-edge/10 bg-surface-900/60 px-3 py-1.5 text-xs font-semibold text-gray-400"
                                                                    >
                                                                        Cancel
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        )}

                                                        {rowErrors[order.uid] && (
                                                            <div className="mt-3 inline-flex items-center gap-1.5 rounded border border-loss/20 bg-loss/10 px-2 py-1 text-xs text-loss">
                                                                <AlertCircle className="h-3.5 w-3.5" />
                                                                {rowErrors[order.uid]}
                                                            </div>
                                                        )}
                                                    </td>
                                                </tr>
                                            )}
                                        </Fragment>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>
            ) : (
                <div className="glass-card p-12 text-center">
                    <EmptyIcon className="mx-auto mb-3 h-12 w-12 text-gray-600 opacity-30" />
                    <p className="text-sm font-medium text-gray-500">{emptyStateMessage.title}</p>
                    <p className="mt-1 text-xs text-gray-600">{emptyStateMessage.subtitle}</p>
                </div>
            )}

            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-gray-600">
                <span>Rows: {formatQuantity(sortedVisibleOrders.length)}</span>
                <span>Gross Turnover: {formatCurrency(visibleGrossTurnover)}</span>
                <span>Sort: {sortLabel}</span>
            </div>
        </div>
    );
}
