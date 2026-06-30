const toDateMs = (value) => {
    const ts = value ? Date.parse(value) : Number.NaN;
    return Number.isFinite(ts) ? ts : 0;
};

const normalizeSide = (value) => String(value || '').trim().toUpperCase();

const normalizeSymbol = (value) => String(value || '').trim().toUpperCase();

export function computeOpenLots(transactions = [], holdings = []) {
    const holdingsByKey = new Map();
    for (const h of holdings || []) {
        const symbol = normalizeSymbol(h?.symbol);
        const productType = String(h?.product_type || 'CNC').toUpperCase();
        const qty = Number(h?.quantity ?? 0);
        if (!symbol || !Number.isFinite(qty) || qty === 0) continue;
        const key = `${symbol}:${productType}`;
        holdingsByKey.set(key, {
            symbol,
            product_type: productType,
            quantity: qty,
            avg_price: Number(h?.avg_price ?? 0),
            updated_at: h?.updated_at || h?.created_at || null,
        });
    }

    // Source of truth: no live holdings means no open lots.
    if (holdingsByKey.size === 0) {
        return [];
    }

    const txByKey = new Map();
    for (const tx of transactions || []) {
        if (!tx || !tx.symbol) continue;
        const symbol = normalizeSymbol(tx.symbol);
        const productType = String(tx.product_type || 'CNC').toUpperCase();
        const key = `${symbol}:${productType}`;
        if (!holdingsByKey.has(key)) continue;

        const side = normalizeSide(tx.transaction_type);
        const qty = Number(tx.quantity ?? 0);
        const price = Number(tx.price ?? tx.filled_price ?? 0);
        if ((side !== 'BUY' && side !== 'SELL') || !Number.isFinite(qty) || qty <= 0) {
            continue;
        }

        const list = txByKey.get(key) || [];
        list.push({
            id: tx.id,
            order_id: tx.order_id,
            symbol,
            product_type: productType,
            side,
            qty,
            price,
            created_at: tx.created_at,
        });
        txByKey.set(key, list);
    }

    const lots = [];

    for (const [key, holding] of holdingsByKey.entries()) {
        const { symbol, product_type: productType } = holding;
        const targetQty = Number(holding.quantity || 0);
        if (!Number.isFinite(targetQty) || targetQty === 0) continue;

        const keyTxDesc = [...(txByKey.get(key) || [])].sort((a, b) => {
            const ta = toDateMs(a.created_at);
            const tb = toDateMs(b.created_at);
            if (ta !== tb) return tb - ta;
            return String(b.id || '').localeCompare(String(a.id || ''));
        });

        // Keep only the most recent transaction suffix that explains current net position.
        const suffix = [];
        let suffixNet = 0;
        for (const tx of keyTxDesc) {
            suffix.push(tx);
            suffixNet += tx.side === 'BUY' ? tx.qty : -tx.qty;
            if (suffixNet === targetQty) {
                break;
            }
        }

        const cycleTx = suffix.reverse();
        const rebuilt = [];

        for (const tx of cycleTx) {
            let remaining = tx.qty;
            const entryPrice = Number.isFinite(tx.price) && tx.price > 0
                ? tx.price
                : Number(holding.avg_price || 0);

            if (tx.side === 'BUY') {
                // BUY closes existing short lots first, then opens long lots.
                for (const lot of rebuilt) {
                    if (remaining <= 0) break;
                    if (Number(lot.remaining_qty) >= 0) continue;
                    const cover = Math.min(remaining, Math.abs(Number(lot.remaining_qty)));
                    lot.remaining_qty = Number(lot.remaining_qty) + cover;
                    remaining -= cover;
                }
                if (remaining > 0) {
                    rebuilt.push({
                        id: tx.id,
                        order_id: tx.order_id,
                        symbol,
                        product_type: productType,
                        side: 'LONG',
                        entry_price: entryPrice,
                        remaining_qty: remaining,
                        created_at: tx.created_at,
                    });
                }
            } else {
                // SELL closes existing long lots first, then opens short lots.
                for (const lot of rebuilt) {
                    if (remaining <= 0) break;
                    if (Number(lot.remaining_qty) <= 0) continue;
                    const close = Math.min(remaining, Number(lot.remaining_qty));
                    lot.remaining_qty = Number(lot.remaining_qty) - close;
                    remaining -= close;
                }
                if (remaining > 0) {
                    rebuilt.push({
                        id: tx.id,
                        order_id: tx.order_id,
                        symbol,
                        product_type: productType,
                        side: 'SHORT',
                        entry_price: entryPrice,
                        remaining_qty: -remaining,
                        created_at: tx.created_at,
                    });
                }
            }
        }

        const filtered = rebuilt.filter((lot) => Number(lot.remaining_qty) !== 0);
        let rebuiltNet = 0;
        for (const lot of filtered) {
            rebuiltNet += Number(lot.remaining_qty || 0);
            lots.push(lot);
        }

        if (rebuiltNet !== targetQty) {
            const delta = targetQty - rebuiltNet;
            lots.push({
                id: `synthetic-${delta > 0 ? 'long' : 'short'}-${symbol}-${productType}`,
                order_id: null,
                symbol,
                product_type: productType,
                side: delta > 0 ? 'LONG' : 'SHORT',
                entry_price: Number(holding.avg_price || 0),
                remaining_qty: delta,
                created_at: holding.updated_at,
                synthetic: true,
            });
        }
    }

    return lots.sort((a, b) => toDateMs(b.created_at) - toDateMs(a.created_at));
}
