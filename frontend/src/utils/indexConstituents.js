/**
 * NSE / BSE Index & ETF constituent stock mappings.
 *
 * Keys are canonical base symbols (no .NS / .BO suffix, no ^ prefix).
 * Values are arrays of constituent base symbols — .NS is added at fetch time.
 *
 * Add or update entries here whenever an index rebalances.
 */

const NIFTY50_STOCKS = [
    'ADANIENT', 'ADANIPORTS', 'APOLLOHOSP', 'ASIANPAINT', 'AXISBANK',
    'BAJAJ-AUTO', 'BAJAJFINSV', 'BAJFINANCE', 'BHARTIARTL', 'BPCL',
    'BRITANNIA', 'CIPLA', 'COALINDIA', 'DIVISLAB', 'DRREDDY',
    'EICHERMOT', 'GRASIM', 'HCLTECH', 'HDFCBANK', 'HDFCLIFE',
    'HEROMOTOCO', 'HINDALCO', 'HINDUNILVR', 'ICICIBANK', 'INDUSINDBK',
    'INFY', 'ITC', 'JIOFIN', 'JSWSTEEL', 'KOTAKBANK',
    'LT', 'M&M', 'MARUTI', 'NESTLEIND', 'NTPC',
    'ONGC', 'POWERGRID', 'RELIANCE', 'SBIN', 'SBILIFE',
    'SUNPHARMA', 'TATAMOTORS', 'TATACONSUM', 'TATASTEEL', 'TCS',
    'TECHM', 'TITAN', 'TRENT', 'ULTRACEMCO', 'WIPRO',
];

const NIFTY_BANK_STOCKS = [
    'HDFCBANK', 'ICICIBANK', 'KOTAKBANK', 'AXISBANK', 'SBIN',
    'INDUSINDBK', 'BANDHANBNK', 'FEDERALBNK', 'IDFCFIRSTB', 'AUBANK',
    'PNB', 'BANKBARODA',
];

const NIFTY_IT_STOCKS = [
    'TCS', 'INFY', 'HCLTECH', 'WIPRO', 'TECHM',
    'MPHASIS', 'LTIM', 'COFORGE', 'PERSISTENT', 'KPITTECH', 'OFSS',
];

// Representative top-20 of NIFTY Midcap 100 (full 100 is too large for sidebar)
const NIFTY_MIDCAP100_STOCKS = [
    'APLAPOLLO', 'ASTRAL', 'AUBANK', 'BANDHANBNK', 'BSE',
    'CAMS', 'CDSL', 'COFORGE', 'GLENMARK', 'HAL',
    'HINDPETRO', 'KPITTECH', 'LTTS', 'MPHASIS', 'NAUKRI',
    'PERSISTENT', 'POLYCAB', 'SBICARD', 'TIINDIA', 'TATACOMM',
];

const NIFTY_NEXT50_STOCKS = [
    'ABB', 'ACC', 'ADANIGREEN', 'AMBUJACEM', 'BERGEPAINT',
    'BIOCON', 'BOSCHLTD', 'COLPAL', 'CONCOR', 'DLF',
    'GAIL', 'GODREJCP', 'GODREJPROP', 'HAVELLS', 'ICICIGI',
    'ICICIPRULI', 'INDUSTOWER', 'MARICO', 'MCDOWELL-N', 'MOTHERSON',
    'NAUKRI', 'OBEROIRLTY', 'PAGEIND', 'PIDILITIND', 'PIIND',
    'SRF', 'TORNTPHARM', 'TRENT', 'TVSMOTOR', 'VEDL',
];

const SENSEX_STOCKS = [
    'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK',
    'LT', 'SBIN', 'ITC', 'BHARTIARTL', 'AXISBANK',
    'BAJFINANCE', 'KOTAKBANK', 'HCLTECH', 'WIPRO', 'MARUTI',
    'SUNPHARMA', 'TITAN', 'BAJAJFINSV', 'POWERGRID', 'NTPC',
    'TATASTEEL', 'ASIANPAINT', 'NESTLEIND', 'M&M', 'ULTRACEMCO',
    'TATAMOTORS', 'TRENT', 'ADANIPORTS', 'JSWSTEEL', 'HDFCLIFE',
];

const NIFTY_AUTO_STOCKS = [
    'TATAMOTORS', 'MARUTI', 'M&M', 'BAJAJ-AUTO', 'HEROMOTOCO',
    'EICHERMOT', 'TVSMOTOR', 'BOSCHLTD', 'MOTHERSON', 'BALKRISIND',
    'ASHOKLEY', 'BHARATFORG',
];

const NIFTY_PHARMA_STOCKS = [
    'SUNPHARMA', 'DIVISLAB', 'CIPLA', 'DRREDDY', 'APOLLOHOSP',
    'AUROPHARMA', 'TORNTPHARM', 'BIOCON', 'LUPIN', 'ALKEM',
    'GLENMARK', 'PFIZER',
];

const NIFTY_FMCG_STOCKS = [
    'HINDUNILVR', 'ITC', 'NESTLEIND', 'BRITANNIA', 'DABUR',
    'GODREJCP', 'MARICO', 'COLPAL', 'EMAMILTD', 'TATACONSUM',
    'UBL', 'VBL',
];

/**
 * Master lookup: base-symbol → constituent base-symbols[]
 *
 * Multiple aliases map to the same list so watchlist items added
 * under any name variant are handled correctly.
 */
export const INDEX_CONSTITUENTS = {
    // ── NIFTY 50 ─────────────────────────────────────────────────────
    'NSEI': NIFTY50_STOCKS,
    'NIFTY50': NIFTY50_STOCKS,
    'NIFTY 50': NIFTY50_STOCKS,
    'NIFTY': NIFTY50_STOCKS,

    // ── NIFTY BANK ───────────────────────────────────────────────────
    'NSEBANK': NIFTY_BANK_STOCKS,
    'BANKNIFTY': NIFTY_BANK_STOCKS,
    'NIFTY BANK': NIFTY_BANK_STOCKS,
    'NIFTYBANK': NIFTY_BANK_STOCKS,
    'BANKBEES': NIFTY_BANK_STOCKS,  // ETF tracks Bank Nifty

    // ── NIFTY IT ─────────────────────────────────────────────────────
    'NIFTYIT': NIFTY_IT_STOCKS,
    'NIFTY IT': NIFTY_IT_STOCKS,
    'ITBEES': NIFTY_IT_STOCKS,       // ETF tracks Nifty IT

    // ── NIFTY Midcap 100 ─────────────────────────────────────────────
    'NIFTY_MIDCAP_100': NIFTY_MIDCAP100_STOCKS,
    'NIFTYMIDCAP100': NIFTY_MIDCAP100_STOCKS,
    'NIFTY MIDCAP 100': NIFTY_MIDCAP100_STOCKS,
    'MIDCAPBEES': NIFTY_MIDCAP100_STOCKS,

    // ── NIFTY Next 50 ────────────────────────────────────────────────
    'NIFTYNXT50': NIFTY_NEXT50_STOCKS,
    'NIFTY NEXT 50': NIFTY_NEXT50_STOCKS,
    'JUNIORBEES': NIFTY_NEXT50_STOCKS, // ETF tracks Nifty Next 50

    // ── NIFTYBEES (ETF tracking Nifty 50) ───────────────────────────
    'NIFTYBEES': NIFTY50_STOCKS,

    // ── SENSEX / BSE ─────────────────────────────────────────────────
    'BSESN': SENSEX_STOCKS,
    'SENSEX': SENSEX_STOCKS,

    // ── Sector indices ───────────────────────────────────────────────
    'NIFTYAUTO': NIFTY_AUTO_STOCKS,
    'NIFTY AUTO': NIFTY_AUTO_STOCKS,
    'NIFTYPHARMA': NIFTY_PHARMA_STOCKS,
    'NIFTY PHARMA': NIFTY_PHARMA_STOCKS,
    'NIFTYFMCG': NIFTY_FMCG_STOCKS,
    'NIFTY FMCG': NIFTY_FMCG_STOCKS,
};

/**
 * Returns the constituent list for a symbol, or null if it is not an index.
 *
 * @param {string} symbol  - e.g. "NIFTY_MIDCAP_100.NS", "^NSEI", "NIFTYBEES"
 * @returns {string[]|null} - constituent base symbols (no .NS) or null
 */
export function getConstituents(symbol) {
    if (!symbol) return null;
    const base = String(symbol)
        .replace(/\.(NS|BO)$/i, '')
        .replace(/^\^/, '')
        .trim()
        .toUpperCase();

    return INDEX_CONSTITUENTS[base] ?? null;
}
