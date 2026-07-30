const toNumber = (value, fallback = 0) => {
    const num = Number(value);
    return Number.isFinite(num) ? num : fallback;
};

const pickNumber = (...values) => {
    for (const value of values) {
        if (value == null || value === '') continue;
        const num = Number(value);
        if (Number.isFinite(num)) return num;
    }
    return 0;
};

const getQuoteForSymbol = (quotes, symbol) => {
    if (!symbol || !quotes) return null;
    return quotes[symbol] || quotes[symbol.replace('.NS', '')] || quotes[`${symbol}.NS`] || null;
};

export function buildLiveHoldings(holdings = [], liveQuotes = {}) {
    const liveHoldings = (holdings || []).map((holding) => {
        const symbol = holding?.symbol;
        if (!symbol) return holding;

        const quote = getQuoteForSymbol(liveQuotes, symbol);
        const livePrice = toNumber(quote?.price ?? quote?.lp ?? quote?.ltp ?? quote?.last_price, NaN);
        if (!Number.isFinite(livePrice) || livePrice <= 0) return holding;

        const quantity = toNumber(holding.quantity ?? 0, 0);
        const avgPrice = toNumber(holding.avg_price ?? 0, 0);
        const investedValue = avgPrice * quantity;
        const currentValue = livePrice * quantity;
        const pnl = currentValue - investedValue;
        const pnlPercent = Math.abs(investedValue) > 0 ? (pnl / Math.abs(investedValue)) * 100 : 0;

        return {
            ...holding,
            current_price: livePrice,
            current_value: currentValue,
            invested_value: investedValue,
            pnl,
            pnl_percent: pnlPercent,
            __hasLivePrice: true,
        };
    });

    const liveTotals = {
        invested: liveHoldings.reduce((sum, holding) => {
            const qty = toNumber(holding.quantity ?? 0, 0);
            const avg = toNumber(holding.avg_price ?? 0, 0);
            return sum + Math.abs(avg * qty);
        }, 0),
        current: liveHoldings.reduce((sum, holding) => sum + Math.abs(toNumber(holding.current_value ?? 0, 0)), 0),
        unrealized: liveHoldings.reduce((sum, holding) => sum + toNumber(holding.pnl ?? 0, 0), 0),
    };

    const hasLivePricing = liveHoldings.some((holding) => holding?.__hasLivePrice === true);

    return { liveHoldings, liveTotals, hasLivePricing };
}

export function buildPortfolioMetrics({ summary = null, pnl = null, holdings = [], liveQuotes = {}, portfolio = null } = {}) {
    const base = summary || portfolio || {};
    const { liveHoldings, liveTotals, hasLivePricing } = buildLiveHoldings(holdings, liveQuotes);

    const availableCash = pickNumber(base.available_capital, summary?.available_capital, portfolio?.available_capital, pnl?.available, 0);
    const totalInvested = hasLivePricing
        ? pickNumber(liveTotals.invested, base.total_invested, summary?.total_invested, portfolio?.total_invested, 0)
        : pickNumber(base.total_invested, summary?.total_invested, portfolio?.total_invested, 0);
    const currentValue = hasLivePricing
        ? pickNumber(liveTotals.current, base.current_value, summary?.current_value, portfolio?.current_value, 0)
        : pickNumber(base.current_value, summary?.current_value, portfolio?.current_value, 0);
    const realized = pickNumber(base.realized_pnl, summary?.realized_pnl, pnl?.realized, 0);
    const unrealized = hasLivePricing
        ? pickNumber(liveTotals.unrealized, base.unrealized_pnl, summary?.unrealized_pnl, pnl?.unrealized, 0)
        : pickNumber(base.unrealized_pnl, summary?.unrealized_pnl, pnl?.unrealized, 0);
    const totalPnl = pickNumber(base.total_pnl, summary?.total_pnl, pnl?.total, realized + unrealized);
    const totalCapital = pickNumber(base.net_equity, summary?.net_equity, portfolio?.net_equity, availableCash + currentValue);
    const totalPnlPct = pickNumber(base.total_pnl_percent, summary?.total_pnl_percent, totalInvested > 0 ? (totalPnl / Math.abs(totalInvested)) * 100 : 0);
    const m2mPct = totalInvested > 0 ? (unrealized / Math.abs(totalInvested)) * 100 : 0;
    const investedPct = totalCapital > 0 ? (Math.abs(totalInvested) / totalCapital) * 100 : 0;
    const cashPct = totalCapital > 0 ? (Math.max(availableCash, 0) / totalCapital) * 100 : 0;

    return {
        liveHoldings,
        liveTotals,
        hasLivePricing,
        availableCash,
        totalInvested,
        currentValue,
        realized,
        unrealized,
        totalPnl,
        totalCapital,
        totalPnlPct,
        m2mPct,
        investedPct,
        cashPct,
    };
}

export function canonicalPortfolioValues(input) {
    const metrics = buildPortfolioMetrics(input);
    return {
        totalCapital: metrics.totalCapital,
        availableCash: metrics.availableCash,
        totalInvested: metrics.totalInvested,
        currentValue: metrics.currentValue,
        realizedPnl: metrics.realized,
        unrealizedPnl: metrics.unrealized,
        totalPnl: metrics.totalPnl,
        totalPnlPct: metrics.totalPnlPct,
        liveM2M: metrics.unrealized,
        investedPct: metrics.investedPct,
        cashPct: metrics.cashPct,
    };
}