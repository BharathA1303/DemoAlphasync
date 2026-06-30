"""
Market Data Service — Zebu-first live market data.

Primary market data sources:
    1. User's personal Zebu broker session (if connected)
    2. Master Zebu account (shared live feed if configured in .env)
    3. Redis snapshots populated from prior Zebu live data

Responsibilities:
    * Symbol formatting (_format_symbol)
    * User-scoped quote access (get_quote, get_quote_safe)
    * System-level quote access (get_system_quote, get_system_quote_safe)
    * Stock search (local NSE list + Zebu SearchScrip API)
    * Convenience lists (POPULAR_INDIAN_STOCKS, INDIAN_INDICES)
"""

from typing import Optional, Mapping, Any
import time
import logging
import asyncio
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from engines.market_session import market_session, MarketState
from services.nse_stocks import NSE_STOCK_LIST
from providers.symbol_mapper import (
    canonical_to_zebu,
    is_commodity_symbol,
    is_mcx_symbol,
    MCX_COMMODITY_SYMBOLS,
    NCDEX_COMMODITY_SYMBOLS,
)

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


# ── Request deduplication (prevent duplicate concurrent requests) ──
@dataclass
class _RequestInFlight:
    task: asyncio.Task
    created_at: float


_batch_requests: dict = {}  # key → in-flight task
_symbol_requests: dict = {}  # symbol → in-flight task
_cleanup_interval = 300  # Clean old entries after 5 minutes


# Provider timeout to prevent hanging request
PROVIDER_TIMEOUT_SECONDS = 3.0
_LIVE_PROVIDER_RECOVER_COOLDOWN_SECONDS = 20
_last_live_provider_recover_attempt = 0.0
_live_provider_recover_lock = asyncio.Lock()


# ── Timeout wrapper for provider calls ──
async def _call_provider_with_timeout(
    coro, symbol: str, timeout: float = PROVIDER_TIMEOUT_SECONDS
):
    """
    Call provider method with timeout.
    Returns None on timeout/error.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"Provider timeout for {symbol} (>{timeout}s)")
        return None
    except Exception as e:
        logger.warning(f"Provider error for {symbol}: {e}")
        return None


# ── Search result cache ────────────────────────────────────────────────────────
_search_cache: dict = {}
_search_cache_ts: dict = {}
SEARCH_CACHE_DURATION = 300  # 5 minutes

# Popular Indian stocks (used for ticker bar, default suggestions)
POPULAR_INDIAN_STOCKS = [
    {"symbol": "RELIANCE.NS", "name": "Reliance Industries", "exchange": "NSE"},
    {"symbol": "TCS.NS", "name": "Tata Consultancy Services", "exchange": "NSE"},
    {"symbol": "HDFCBANK.NS", "name": "HDFC Bank", "exchange": "NSE"},
    {"symbol": "INFY.NS", "name": "Infosys", "exchange": "NSE"},
    {"symbol": "ICICIBANK.NS", "name": "ICICI Bank", "exchange": "NSE"},
    {"symbol": "HINDUNILVR.NS", "name": "Hindustan Unilever", "exchange": "NSE"},
    {"symbol": "SBIN.NS", "name": "State Bank of India", "exchange": "NSE"},
    {"symbol": "BHARTIARTL.NS", "name": "Bharti Airtel", "exchange": "NSE"},
    {"symbol": "ITC.NS", "name": "ITC Limited", "exchange": "NSE"},
    {"symbol": "KOTAKBANK.NS", "name": "Kotak Mahindra Bank", "exchange": "NSE"},
    {"symbol": "LT.NS", "name": "Larsen & Toubro", "exchange": "NSE"},
    {"symbol": "AXISBANK.NS", "name": "Axis Bank", "exchange": "NSE"},
    {"symbol": "WIPRO.NS", "name": "Wipro", "exchange": "NSE"},
    {"symbol": "HCLTECH.NS", "name": "HCL Technologies", "exchange": "NSE"},
    {"symbol": "TATAMOTORS.NS", "name": "Tata Motors", "exchange": "NSE"},
    {"symbol": "SUNPHARMA.NS", "name": "Sun Pharma", "exchange": "NSE"},
    {"symbol": "MARUTI.NS", "name": "Maruti Suzuki", "exchange": "NSE"},
    {"symbol": "TITAN.NS", "name": "Titan Company", "exchange": "NSE"},
    {"symbol": "BAJFINANCE.NS", "name": "Bajaj Finance", "exchange": "NSE"},
    {"symbol": "ADANIENT.NS", "name": "Adani Enterprises", "exchange": "NSE"},
    {"symbol": "ASIANPAINT.NS", "name": "Asian Paints", "exchange": "NSE"},
    {"symbol": "BAJAJFINSV.NS", "name": "Bajaj Finserv", "exchange": "NSE"},
    {"symbol": "NESTLEIND.NS", "name": "Nestle India", "exchange": "NSE"},
    {"symbol": "ULTRACEMCO.NS", "name": "UltraTech Cement", "exchange": "NSE"},
    {"symbol": "JSWSTEEL.NS", "name": "JSW Steel", "exchange": "NSE"},
    {"symbol": "NTPC.NS", "name": "NTPC Limited", "exchange": "NSE"},
    {"symbol": "M&M.NS", "name": "Mahindra & Mahindra", "exchange": "NSE"},
    {"symbol": "POWERGRID.NS", "name": "Power Grid Corporation", "exchange": "NSE"},
    {"symbol": "ONGC.NS", "name": "Oil & Natural Gas Corporation", "exchange": "NSE"},
    {"symbol": "TECHM.NS", "name": "Tech Mahindra", "exchange": "NSE"},
    {"symbol": "TATASTEEL.NS", "name": "Tata Steel", "exchange": "NSE"},
    {"symbol": "COALINDIA.NS", "name": "Coal India", "exchange": "NSE"},
    {"symbol": "HINDALCO.NS", "name": "Hindalco Industries", "exchange": "NSE"},
    {"symbol": "INDUSINDBK.NS", "name": "IndusInd Bank", "exchange": "NSE"},
    {"symbol": "DIVISLAB.NS", "name": "Divi's Laboratories", "exchange": "NSE"},
    {"symbol": "GRASIM.NS", "name": "Grasim Industries", "exchange": "NSE"},
    {"symbol": "CIPLA.NS", "name": "Cipla", "exchange": "NSE"},
    {"symbol": "DRREDDY.NS", "name": "Dr Reddy's Laboratories", "exchange": "NSE"},
    {"symbol": "APOLLOHOSP.NS", "name": "Apollo Hospitals", "exchange": "NSE"},
    {"symbol": "EICHERMOT.NS", "name": "Eicher Motors", "exchange": "NSE"},
    {"symbol": "BRITANNIA.NS", "name": "Britannia Industries", "exchange": "NSE"},
    {"symbol": "HEROMOTOCO.NS", "name": "Hero MotoCorp", "exchange": "NSE"},
    {"symbol": "TATACONSUM.NS", "name": "Tata Consumer Products", "exchange": "NSE"},
    {"symbol": "BEL.NS", "name": "Bharat Electronics", "exchange": "NSE"},
    {"symbol": "SBILIFE.NS", "name": "SBI Life Insurance", "exchange": "NSE"},
    {"symbol": "HDFCLIFE.NS", "name": "HDFC Life Insurance", "exchange": "NSE"},
    {"symbol": "ADANIPORTS.NS", "name": "Adani Ports & SEZ", "exchange": "NSE"},
    {"symbol": "BAJAJ-AUTO.NS", "name": "Bajaj Auto", "exchange": "NSE"},
    {"symbol": "SHRIRAMFIN.NS", "name": "Shriram Finance", "exchange": "NSE"},
    {"symbol": "DMART.NS", "name": "Avenue Supermarts (DMart)", "exchange": "NSE"},
    {"symbol": "ABB.NS", "name": "ABB India", "exchange": "NSE"},
    {"symbol": "ACC.NS", "name": "ACC Limited", "exchange": "NSE"},
    {"symbol": "AMBUJACEM.NS", "name": "Ambuja Cements", "exchange": "NSE"},
    {"symbol": "BANKBARODA.NS", "name": "Bank of Baroda", "exchange": "NSE"},
    {"symbol": "BERGEPAINT.NS", "name": "Berger Paints", "exchange": "NSE"},
    {"symbol": "BOSCHLTD.NS", "name": "Bosch", "exchange": "NSE"},
    {"symbol": "CANBK.NS", "name": "Canara Bank", "exchange": "NSE"},
    {"symbol": "CHOLAFIN.NS", "name": "Cholamandalam Finance", "exchange": "NSE"},
    {"symbol": "COLPAL.NS", "name": "Colgate Palmolive", "exchange": "NSE"},
    {"symbol": "CONCOR.NS", "name": "Container Corporation", "exchange": "NSE"},
    {"symbol": "DABUR.NS", "name": "Dabur India", "exchange": "NSE"},
    {"symbol": "DLF.NS", "name": "DLF Limited", "exchange": "NSE"},
    {"symbol": "GAIL.NS", "name": "GAIL India", "exchange": "NSE"},
    {"symbol": "GODREJCP.NS", "name": "Godrej Consumer Products", "exchange": "NSE"},
    {"symbol": "HAVELLS.NS", "name": "Havells India", "exchange": "NSE"},
    {"symbol": "ICICIPRULI.NS", "name": "ICICI Prudential Life", "exchange": "NSE"},
    {"symbol": "IDFCFIRSTB.NS", "name": "IDFC First Bank", "exchange": "NSE"},
    {"symbol": "INDHOTEL.NS", "name": "Indian Hotels", "exchange": "NSE"},
    {"symbol": "INDIGO.NS", "name": "InterGlobe Aviation (IndiGo)", "exchange": "NSE"},
    {"symbol": "IOC.NS", "name": "Indian Oil Corporation", "exchange": "NSE"},
    {"symbol": "IRCTC.NS", "name": "IRCTC", "exchange": "NSE"},
    {"symbol": "JINDALSTEL.NS", "name": "Jindal Steel & Power", "exchange": "NSE"},
    {"symbol": "JIOFIN.NS", "name": "Jio Financial Services", "exchange": "NSE"},
    {"symbol": "LICI.NS", "name": "Life Insurance Corporation", "exchange": "NSE"},
    {"symbol": "LUPIN.NS", "name": "Lupin", "exchange": "NSE"},
    {"symbol": "MAXHEALTH.NS", "name": "Max Healthcare", "exchange": "NSE"},
    {"symbol": "MOTHERSON.NS", "name": "Motherson Sumi Wiring", "exchange": "NSE"},
    {"symbol": "MUTHOOTFIN.NS", "name": "Muthoot Finance", "exchange": "NSE"},
    {"symbol": "NAUKRI.NS", "name": "Info Edge (Naukri)", "exchange": "NSE"},
    {"symbol": "NHPC.NS", "name": "NHPC Limited", "exchange": "NSE"},
    {"symbol": "OBEROIRLTY.NS", "name": "Oberoi Realty", "exchange": "NSE"},
    {"symbol": "OFSS.NS", "name": "Oracle Financial Services", "exchange": "NSE"},
    {"symbol": "PAYTM.NS", "name": "One97 Communications (Paytm)", "exchange": "NSE"},
    {"symbol": "PEL.NS", "name": "Piramal Enterprises", "exchange": "NSE"},
    {"symbol": "PERSISTENT.NS", "name": "Persistent Systems", "exchange": "NSE"},
    {"symbol": "PETRONET.NS", "name": "Petronet LNG", "exchange": "NSE"},
    {"symbol": "PIDILITIND.NS", "name": "Pidilite Industries", "exchange": "NSE"},
    {"symbol": "PNB.NS", "name": "Punjab National Bank", "exchange": "NSE"},
    {"symbol": "POLYCAB.NS", "name": "Polycab India", "exchange": "NSE"},
    {"symbol": "RECLTD.NS", "name": "REC Limited", "exchange": "NSE"},
    {"symbol": "SAIL.NS", "name": "Steel Authority of India", "exchange": "NSE"},
    {"symbol": "SIEMENS.NS", "name": "Siemens", "exchange": "NSE"},
    {"symbol": "SRF.NS", "name": "SRF Limited", "exchange": "NSE"},
    {"symbol": "TATAELXSI.NS", "name": "Tata Elxsi", "exchange": "NSE"},
    {"symbol": "TATAPOWER.NS", "name": "Tata Power", "exchange": "NSE"},
    {"symbol": "TRENT.NS", "name": "Trent Limited", "exchange": "NSE"},
    {"symbol": "VBL.NS", "name": "Varun Beverages", "exchange": "NSE"},
    {"symbol": "VEDL.NS", "name": "Vedanta", "exchange": "NSE"},
    {"symbol": "ZOMATO.NS", "name": "Zomato", "exchange": "NSE"},
    {"symbol": "ZYDUSLIFE.NS", "name": "Zydus Lifesciences", "exchange": "NSE"},
]

# MCX / NCDEX Commodities
POPULAR_COMMODITIES = [
    # ── Metals (MCX) ──
    {
        "symbol": "GOLD",
        "name": "Gold",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per 10g",
        "lot": 1,
    },
    {
        "symbol": "GOLDM",
        "name": "Gold Mini",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per 10g",
        "lot": 1,
    },
    {
        "symbol": "GOLDGUINEA",
        "name": "Gold Guinea",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per 8g",
        "lot": 1,
    },
    {
        "symbol": "GOLDPETAL",
        "name": "Gold Petal",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per 1g",
        "lot": 1,
    },
    {
        "symbol": "SILVER",
        "name": "Silver",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per kg",
        "lot": 1,
    },
    {
        "symbol": "SILVERM",
        "name": "Silver Mini",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per kg",
        "lot": 1,
    },
    {
        "symbol": "SILVERMIC",
        "name": "Silver Micro",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per kg",
        "lot": 1,
    },
    {
        "symbol": "COPPER",
        "name": "Copper",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per kg",
        "lot": 250,
    },
    {
        "symbol": "COPPERM",
        "name": "Copper Mini",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per kg",
        "lot": 100,
    },
    {
        "symbol": "ALUMINIUM",
        "name": "Aluminium",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per kg",
        "lot": 500,
    },
    {
        "symbol": "ALUMINI",
        "name": "Aluminium Mini",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per kg",
        "lot": 100,
    },
    {
        "symbol": "ZINC",
        "name": "Zinc",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per kg",
        "lot": 500,
    },
    {
        "symbol": "ZINCMINI",
        "name": "Zinc Mini",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per kg",
        "lot": 100,
    },
    {
        "symbol": "LEAD",
        "name": "Lead",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per kg",
        "lot": 500,
    },
    {
        "symbol": "LEADMINI",
        "name": "Lead Mini",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per kg",
        "lot": 100,
    },
    {
        "symbol": "NICKEL",
        "name": "Nickel",
        "exchange": "MCX",
        "category": "metals",
        "unit": "per kg",
        "lot": 100,
    },
    # ── Energy (MCX) ──
    {
        "symbol": "CRUDEOIL",
        "name": "Crude Oil",
        "exchange": "MCX",
        "category": "energy",
        "unit": "per bbl",
        "lot": 100,
    },
    {
        "symbol": "CRUDEOILM",
        "name": "Crude Oil Mini",
        "exchange": "MCX",
        "category": "energy",
        "unit": "per bbl",
        "lot": 10,
    },
    {
        "symbol": "NATURALGAS",
        "name": "Natural Gas",
        "exchange": "MCX",
        "category": "energy",
        "unit": "per MMBtu",
        "lot": 1250,
    },
    {
        "symbol": "NATGASMINI",
        "name": "Natural Gas Mini",
        "exchange": "MCX",
        "category": "energy",
        "unit": "per MMBtu",
        "lot": 250,
    },
    # ── Agriculture / other commodity contracts ──
    {
        "symbol": "COTTONCNDY",
        "name": "Cotton Candy",
        "exchange": "MCX",
        "category": "agriculture",
        "unit": "per candy",
        "lot": 48,
    },
    {
        "symbol": "KAPAS",
        "name": "Kapas",
        "exchange": "MCX",
        "category": "agriculture",
        "unit": "per 20kg",
        "lot": 200,
    },
    # ── NCDEX fallback universe ──
    {
        "symbol": "COTTON",
        "name": "Cotton",
        "exchange": "NCDEX",
        "category": "agriculture",
        "unit": "per bale",
        "lot": 25,
    },
    {
        "symbol": "CASTORSEED",
        "name": "Castor Seed",
        "exchange": "NCDEX",
        "category": "agriculture",
        "unit": "per quintal",
        "lot": 100,
    },
    {
        "symbol": "SOYBEAN",
        "name": "Soybean",
        "exchange": "NCDEX",
        "category": "agriculture",
        "unit": "per quintal",
        "lot": 100,
    },
    {
        "symbol": "GUARSEED",
        "name": "Guar Seed",
        "exchange": "NCDEX",
        "category": "agriculture",
        "unit": "per quintal",
        "lot": 100,
    },
    {
        "symbol": "RMSEED",
        "name": "Mustard Seed",
        "exchange": "NCDEX",
        "category": "agriculture",
        "unit": "per quintal",
        "lot": 100,
    },
    {
        "symbol": "CHANA",
        "name": "Chana",
        "exchange": "NCDEX",
        "category": "agriculture",
        "unit": "per quintal",
        "lot": 100,
    },
    {
        "symbol": "MENTHOIL",
        "name": "Mentha Oil",
        "exchange": "MCX",
        "category": "agriculture",
        "unit": "per kg",
        "lot": 360,
    },
]

# Indian market indices
INDIAN_INDICES = [
    {"symbol": "^NSEI", "name": "NIFTY 50"},
    {"symbol": "^BSESN", "name": "SENSEX"},
    {"symbol": "^NSEBANK", "name": "BANK NIFTY"},
    {"symbol": "^CNXFIN", "name": "FINNIFTY"},
    {"symbol": "^CNXIT", "name": "NIFTY IT"},
    {"symbol": "^CNXPHARMA", "name": "NIFTY PHARMA"},
    {"symbol": "^CNXAUTO", "name": "NIFTY AUTO"},
    {"symbol": "^CNXMETAL", "name": "NIFTY METAL"},
    {"symbol": "^CNXFMCG", "name": "NIFTY FMCG"},
    {"symbol": "^CNXPSUBANK", "name": "NIFTY PSU BANK"},
]


def _build_commodity_universe() -> list[dict]:
    """Return the supported commodity universe with any preloaded contract mapping."""
    universe: list[dict] = []
    for item in POPULAR_COMMODITIES:
        symbol = str(item.get("symbol") or "").upper().strip()
        if not symbol:
            continue

        entry = {
            "symbol": symbol,
            "name": item.get("name") or symbol,
            "exchange": str(item.get("exchange") or "MCX").upper().strip() or "MCX",
            "category": item.get("category") or _categorize_commodity(symbol),
            "unit": item.get("unit") or "per unit",
            "lot": item.get("lot") or 1,
        }

        try:
            mapping = canonical_to_zebu(symbol)
        except Exception:
            mapping = None

        if mapping:
            entry["token"] = str(mapping.get("token") or "").strip() or None
            entry["contract_symbol"] = (
                str(mapping.get("trading_symbol") or symbol).upper().strip() or symbol
            )
            entry["exchange"] = (
                str(mapping.get("exchange") or entry["exchange"]).upper().strip()
                or entry["exchange"]
            )

        universe.append(entry)

    return universe


_INTRADAY_HISTORY_INTERVALS = frozenset(
    {"1m", "2m", "3m", "5m", "10m", "15m", "30m", "1h", "2h", "4h"}
)

# Spot index → nearest liquid futures underlying (for volume proxy when index OHLC has v=0).
_INDEX_FUTURES_UNDERLYING: dict[str, str] = {
    "^NSEI": "NIFTY",
    "^NSEBANK": "BANKNIFTY",
    "^BSESN": "SENSEX",
    "^CNXFIN": "FINNIFTY",
    "^CNXMIDCAP": "MIDCPNIFTY",
    "^CNXJUNIOR": "NIFTYNXT50",
}

_INDEX_REDIS_HISTORY_ATTEMPTS: tuple[tuple[str, str], ...] = (
    ("5d", "5m"),
    ("1d", "5m"),
    ("5d", "1m"),
    ("1d", "1m"),
    ("5d", "15m"),
    ("1d", "15m"),
)


def _is_index_symbol(symbol: str) -> bool:
    return str(symbol or "").strip().upper().startswith("^")


def _history_has_volume(candles: list) -> bool:
    return any(int(c.get("volume") or 0) > 0 for c in (candles or []))


def _positive_volume_count(candles: list) -> int:
    return sum(1 for c in (candles or []) if int(c.get("volume") or 0) > 0)


def _interval_seconds(interval: str) -> int:
    mapping = {
        "1m": 60,
        "2m": 120,
        "3m": 180,
        "5m": 300,
        "10m": 600,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "2h": 7200,
        "4h": 14400,
    }
    return mapping.get(str(interval or "").strip().lower(), 300)


def _merge_volume_by_time(primary: list, volume_source: list) -> list:
    """Copy bar volume from a second series keyed by candle time."""
    if not primary or not volume_source:
        return primary or []
    vol_by_time = {
        int(c["time"]): max(0, int(c.get("volume") or 0))
        for c in volume_source
        if c.get("time") is not None
    }
    merged = []
    for candle in primary:
        t = int(candle.get("time"))
        vol = vol_by_time.get(t)
        if vol is not None and vol > 0:
            merged.append({**candle, "volume": vol})
        else:
            merged.append(candle)
    return merged


def _merge_volume_by_nearest_time(
    primary: list,
    volume_source: list,
    tolerance_sec: int = 300,
) -> list:
    """Attach volume from a second series when bucket timestamps differ slightly."""
    if not primary or not volume_source:
        return primary or []

    vol_rows = sorted(
        (
            int(c["time"]),
            max(0, int(c.get("volume") or 0)),
        )
        for c in volume_source
        if c.get("time") is not None and int(c.get("volume") or 0) > 0
    )
    if not vol_rows:
        return primary

    def nearest_volume(target_ts: int) -> int | None:
        best_vol = None
        best_dist = tolerance_sec + 1
        for row_ts, row_vol in vol_rows:
            dist = abs(row_ts - target_ts)
            if dist < best_dist:
                best_dist = dist
                best_vol = row_vol
        return best_vol if best_dist <= tolerance_sec else None

    merged = []
    for candle in primary:
        t = int(candle.get("time"))
        vol = nearest_volume(t)
        if vol is not None and vol > 0:
            merged.append({**candle, "volume": vol})
        else:
            merged.append(candle)
    return merged


async def _get_index_futures_volume_history(
    symbol: str, period: str, interval: str
) -> list:
    """
    Near-month futures OHLCV for index volume proxy.

    Index spot TPSeries often returns intv=0; liquid futures carry real traded volume.
    """
    underlying = _INDEX_FUTURES_UNDERLYING.get(str(symbol or "").strip().upper())
    if not underlying:
        logger.debug("[INDEX_VOLUME_PROXY_FAIL] reason=unsupported_symbol symbol=%s", symbol)
        return []

    try:
        from services.futures_contract_registry import futures_contract_registry

        def _extract_contract_symbol(c: Optional[dict]) -> str:
            return str(
                (c or {}).get("contract_symbol")
                or (c or {}).get("trading_symbol")
                or (c or {}).get("tsym")
                or ""
            ).strip().upper()

        near = futures_contract_registry.get_near_contract(underlying)
        contract_sym = _extract_contract_symbol(near)

        # Registry can be empty on some boots. Warm futures contracts + registry and retry.
        if not contract_sym:
            logger.debug(
                "[INDEX_VOLUME_PROXY_FAIL] reason=registry_none underlying=%s",
                underlying,
            )
            try:
                from services import futures_service

                await futures_service.initialize_futures()
            except Exception as exc:
                logger.debug(
                    "[INDEX_VOLUME_PROXY_FAIL] reason=futures_init_error underlying=%s error=%s",
                    underlying,
                    exc,
                )
            try:
                await futures_contract_registry.refresh_from_service()
            except Exception as exc:
                logger.debug(
                    "[INDEX_VOLUME_PROXY_FAIL] reason=registry_refresh_error underlying=%s error=%s",
                    underlying,
                    exc,
                )

            near = futures_contract_registry.get_near_contract(underlying)
            contract_sym = _extract_contract_symbol(near)

        # Final registry-only fallback: first active contract in the registry list.
        if not contract_sym:
            contracts = futures_contract_registry.get_contracts_for_underlying(underlying)
            if contracts:
                contract_sym = _extract_contract_symbol(contracts[0])

        # Live SearchScrip / CDN path (same contract discovery as Futures page).
        if not contract_sym:
            from services import futures_service

            live_contracts = await futures_service.get_contracts_live(underlying)
            live_sorted = sorted(
                live_contracts or [],
                key=lambda c: str(c.get("expiry_date") or "9999-12-31"),
            )
            if live_sorted:
                contract_sym = _extract_contract_symbol(live_sorted[0])

        if not contract_sym:
            return []

        limit = 800
        if period in {"1d", "5d"}:
            limit = 500
        elif period in {"1mo", "3mo"}:
            limit = 1200

        # Same history pipeline as GET /api/futures/history/{contract} (Futures page chart).
        from services import futures_service

        rows = await futures_service.get_history(
            contract_sym,
            interval=interval,
            limit=limit,
        )
        normalized = normalize_history_candles(rows or [])
        logger.debug(
            "[INDEX_VOLUME_PROXY] underlying=%s resolved_contract=%s proxy_candles=%d positive_volume=%d",
            underlying,
            contract_sym,
            len(normalized),
            _positive_volume_count(normalized),
        )
        return normalized
    except Exception as exc:
        logger.debug(
            "[INDEX_VOLUME_PROXY_FAIL] reason=exception underlying=%s symbol=%s period=%s interval=%s error=%s",
            underlying,
            symbol,
            period,
            interval,
            exc,
        )
        return []


async def _enrich_index_candles_with_futures_volume(
    primary: list,
    symbol: str,
    period: str,
    interval: str,
) -> list:
    """
    Copy near-month futures bar volume onto index OHLC candles (index OHLC unchanged).

    Used by Terminal index charts (^NSEI, ^NSEBANK, ^BSESN) when spot TPSeries has v=0.
    """
    if not primary or not _is_index_symbol(symbol):
        return primary or []
    if interval not in _INTRADAY_HISTORY_INTERVALS:
        return primary
    if _history_has_volume(primary):
        return primary

    fut_hist = await _get_index_futures_volume_history(symbol, period, interval)
    if not fut_hist or not _history_has_volume(fut_hist):
        return primary

    tolerance = max(120, _interval_seconds(interval) * 2)
    merged = _merge_volume_by_nearest_time(
        primary, fut_hist, tolerance_sec=tolerance
    )
    if not _history_has_volume(merged):
        merged = _merge_volume_by_time(merged, fut_hist)
    if merged and _history_has_volume(merged):
        logger.debug(
            "Index futures volume enrich %s (%s %s): bars=%d positive_volume=%d tolerance=%ds",
            symbol,
            period,
            interval,
            len(merged),
            _positive_volume_count(merged),
            tolerance,
        )
        return merged
    return primary


def _format_symbol(symbol: str) -> str:
    """Ensure symbol has .NS suffix for NSE stocks.
    Indices (^), derivative contracts, commodity futures (=F), and MCX symbols are left as-is.
    """
    clean = str(symbol or "").strip().upper()
    if not clean:
        return clean

    # Keep canonical non-equity symbols unchanged.
    if clean.startswith("^") or clean.endswith(("=F", ".NS", ".BO")):
        return clean

    if is_commodity_symbol(clean):
        return clean

    # Keep derivatives unchanged (examples: NIFTY30APR2026FUT, NIFTY24APR2523000CE).
    if re.search(r"\d", clean) and re.search(r"(FUT|CE|PE)$", clean):
        return clean

    return f"{clean}.NS"


def _normalize_quote(quote: Optional[dict]) -> Optional[dict]:
    """
    Normalize quote from ANY source into standardized field names.
    Extracts price from: price, lp, ltp, last_price, lastPrice, last_traded_price
    Extracts change from: change, net_change, netChange, pChange, price_change
    Extracts change% from: change_percent, changePercent, pct_change, pChange, percent_change
    Extracts prev_close from: prev_close, prevClose, previous_close, close
    Returns None if quote is invalid or missing required fields.
    """
    if not quote or not isinstance(quote, dict):
        return None

    def _first_present(*keys: str):
        for key in keys:
            if key in quote and quote.get(key) is not None:
                return quote.get(key)
        return None

    # Extract price (required for valid quote)
    price = _first_present(
        "price",
        "lp",
        "ltp",
        "last_price",
        "lastPrice",
        "last_traded_price",
    )
    try:
        price = float(price) if price else None
        if not price or price <= 0:
            return None
    except (TypeError, ValueError):
        return None

    # Extract previous close
    prev_close = _first_present("prev_close", "prevClose", "previous_close", "close")
    try:
        prev_close = float(prev_close) if prev_close is not None else None
        if prev_close is not None and prev_close <= 0:
            prev_close = None
    except (TypeError, ValueError):
        prev_close = None

    # Extract change (derived if missing)
    change = _first_present("change", "net_change", "netChange", "price_change")
    try:
        change = float(change) if change is not None else None
    except (TypeError, ValueError):
        change = None
    if change is None and prev_close:
        change = round(float(price) - float(prev_close), 2)
    elif change is not None:
        change = round(float(change), 2)

    # Extract change percent (derived if missing)
    change_percent = _first_present(
        "pc",
        "change_percent",
        "changePercent",
        "pct_change",
        "pChange",
        "percent_change",
    )
    try:
        change_percent = float(change_percent) if change_percent is not None else None
    except (TypeError, ValueError):
        change_percent = None
    if prev_close is None and change is not None:
        derived_prev = float(price) - float(change)
        if derived_prev > 0:
            prev_close = derived_prev
    if prev_close is None and change_percent is not None:
        denominator = 1 + (float(change_percent) / 100.0)
        if denominator > 0:
            derived_prev = float(price) / denominator
            if derived_prev > 0:
                prev_close = derived_prev
                if change is None:
                    change = round(float(price) - float(prev_close), 2)
    if change_percent is None and prev_close:
        if change is not None:
            change_percent = round((float(change) / float(prev_close) * 100), 2)
    elif change_percent is not None:
        change_percent = round(float(change_percent), 2)

    # Extract optional fields
    open_price = _first_present("open", "o")
    try:
        open_price = round(float(open_price), 2) if open_price is not None else None
    except (TypeError, ValueError):
        open_price = None

    high = _first_present("high", "h")
    try:
        high = round(float(high), 2) if high is not None else None
    except (TypeError, ValueError):
        high = None

    low = _first_present("low", "l")
    try:
        low = round(float(low), 2) if low is not None else None
    except (TypeError, ValueError):
        low = None

    volume = _first_present("volume", "v", "vo")
    try:
        volume = int(float(volume)) if volume else 0
    except (TypeError, ValueError):
        volume = 0

    # Extract bid/ask/OI/depth — essential for commodity table display.
    # These are provided by Zebu touchline ticks and GetQuotes REST.
    bid_price = _first_present("bid_price", "bp1", "best_bid_price")
    try:
        bid_price = round(float(bid_price), 2) if bid_price else None
    except (TypeError, ValueError):
        bid_price = None

    ask_price = _first_present("ask_price", "sp1", "best_ask_price")
    try:
        ask_price = round(float(ask_price), 2) if ask_price else None
    except (TypeError, ValueError):
        ask_price = None

    bid_qty = _first_present("bid_qty", "bq1", "best_bid_qty")
    try:
        bid_qty = int(float(bid_qty)) if bid_qty else 0
    except (TypeError, ValueError):
        bid_qty = 0

    ask_qty = _first_present("ask_qty", "sq1", "best_ask_qty")
    try:
        ask_qty = int(float(ask_qty)) if ask_qty else 0
    except (TypeError, ValueError):
        ask_qty = 0

    oi = _first_present("oi", "open_interest")
    try:
        oi = int(float(oi)) if oi else 0
    except (TypeError, ValueError):
        oi = 0

    # Build normalized output
    normalized = {
        "symbol": quote.get("symbol", ""),
        "name": quote.get("name", ""),
        "price": round(float(price), 2),
        "change": change,
        "change_percent": change_percent,
        "prev_close": round(float(prev_close), 2) if prev_close is not None else None,
        "open": open_price,
        "high": high,
        "low": low,
        "volume": volume,
        "bid_price": bid_price,
        "ask_price": ask_price,
        "bid_qty": bid_qty,
        "ask_qty": ask_qty,
        "oi": oi,
        "timestamp": quote.get("timestamp", datetime.now(timezone.utc).isoformat()),
    }

    # Preserve additional fields from original quote (for compatibility)
    for key in [
        "source",
        "exchange",
        "kind",
        "category",
        "unit",
        "lot",
        "market_status",
        "market_state",
        "last_trade_time",
        "token",
        "contract_symbol",
        "expiry_date",
        "tick_size",
        "official",
        "official_close",
        "official_close_timestamp",
        "frozen",
        "frozen_at",
        "is_market_open",
        "freshness_state",
        "instrument_token",
    ]:
        if key in quote:
            normalized[key] = quote[key]

    return normalized


def _coerce_unix_seconds(raw_time) -> Optional[int]:
    """Convert mixed timestamp formats (sec/ms/us/ns/ISO) into Unix seconds."""
    if raw_time is None:
        return None

    # Numeric-like timestamp (int/float or numeric string)
    try:
        as_float = float(raw_time)
        if as_float <= 0:
            return None
        # Detect common epoch units and normalize to seconds.
        if as_float > 1e18:  # nanoseconds
            as_float /= 1_000_000_000.0
        elif as_float > 1e15:  # microseconds
            as_float /= 1_000_000.0
        elif as_float > 1e12:  # milliseconds
            as_float /= 1_000.0
        return int(as_float)
    except (TypeError, ValueError):
        pass

    # ISO datetime string
    if isinstance(raw_time, str):
        try:
            iso = raw_time.replace("Z", "+00:00")
            return int(datetime.fromisoformat(iso).timestamp())
        except Exception:
            return None

    return None


def normalize_history_candles(candles: list) -> list:
    """Normalize mixed OHLCV candle payloads into clean, sorted Unix-second candles."""
    normalized = []

    for candle in candles or []:
        if not isinstance(candle, dict):
            continue

        raw_time = (
            candle.get("time")
            or candle.get("t")
            or candle.get("timestamp")
            or candle.get("datetime")
        )
        t = _coerce_unix_seconds(raw_time)
        if t is None:
            continue

        try:
            o = float(candle.get("open"))
            h = float(candle.get("high"))
            l = float(candle.get("low"))
            c = float(candle.get("close"))
        except (TypeError, ValueError):
            continue

        if not all(x > 0 for x in [o, h, l, c]):
            continue

        high = max(h, o, c, l)
        low = min(l, o, c, h)

        try:
            v = int(float(candle.get("volume", 0) or 0))
        except (TypeError, ValueError):
            v = 0

        normalized.append(
            {
                "time": int(t),
                "open": round(o, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(c, 2),
                "volume": max(0, v),
            }
        )

    normalized.sort(key=lambda x: x["time"])

    deduped = {}
    for item in normalized:
        deduped[item["time"]] = item

    return list(deduped.values())


# ── Provider accessor ──────────────────────────────────────────────


def _get_provider_for_user(user_id: str):
    """Return user provider, falling back to master/any active provider."""
    from services.broker_session import broker_session_manager

    provider = broker_session_manager.get_session(user_id)
    if provider is None:
        provider = broker_session_manager.get_any_session()
    if provider is None:
        raise BrokerNotConnected(user_id)
    return provider


def _get_any_provider():
    """Return ANY active provider for system-level tasks. Raises RuntimeError if none."""
    from services.broker_session import broker_session_manager

    provider = broker_session_manager.get_any_session()
    if provider is None:
        raise RuntimeError("No active broker sessions — market data unavailable")
    return provider


async def _get_any_provider_live(allow_recover: bool = True):
    """Return an active provider, optionally trying master-session recovery first."""
    from services.broker_session import broker_session_manager

    provider = broker_session_manager.get_any_session()
    if provider is not None or not allow_recover:
        return provider

    global _last_live_provider_recover_attempt
    now = time.time()
    if (
        now - _last_live_provider_recover_attempt
    ) < _LIVE_PROVIDER_RECOVER_COOLDOWN_SECONDS:
        return broker_session_manager.get_any_session()

    async with _live_provider_recover_lock:
        provider = broker_session_manager.get_any_session()
        if provider is not None:
            return provider

        now = time.time()
        if (
            now - _last_live_provider_recover_attempt
        ) < _LIVE_PROVIDER_RECOVER_COOLDOWN_SECONDS:
            return broker_session_manager.get_any_session()

        _last_live_provider_recover_attempt = now

        try:
            from services.master_session import master_session_service

            ok = await master_session_service.initialize()
            if ok:
                provider = broker_session_manager.get_any_session()
                if provider is not None:
                    logger.info("Recovered master Zebu session for live-only data path")
        except Exception as e:
            logger.debug(f"Live-only provider recovery failed: {e}")

    return broker_session_manager.get_any_session()


async def _get_provider_quote_live(provider, symbol: str) -> Optional[dict]:
    """Fetch a quote from provider only, retrying once after token remap if needed."""
    quote = await _call_provider_with_timeout(
        provider.get_quote(symbol), symbol, PROVIDER_TIMEOUT_SECONDS
    )
    if quote and (
        quote.get("price") is not None
        or quote.get("lp") is not None
        or quote.get("ltp") is not None
    ):
        return quote

    resolver = getattr(provider, "_resolve_symbol", None)
    if callable(resolver):
        try:
            await _call_provider_with_timeout(
                resolver(symbol), symbol, PROVIDER_TIMEOUT_SECONDS
            )
            retried = await _call_provider_with_timeout(
                provider.get_quote(symbol), symbol, PROVIDER_TIMEOUT_SECONDS
            )
            if retried and (
                retried.get("price") is not None
                or retried.get("lp") is not None
                or retried.get("ltp") is not None
            ):
                return retried
        except Exception as e:
            logger.debug(f"Quote remap retry failed for {symbol}: {e}")

    return quote


class BrokerNotConnected(Exception):
    """Raised when a user has no active broker session."""

    def __init__(self, user_id: str = ""):
        self.user_id = user_id
        super().__init__(
            f"Broker not connected"
            + (f" for user {str(user_id)[:8]}..." if user_id else "")
        )


class ProviderDataUnavailable(Exception):
    """Raised when the active provider has no data for a symbol."""

    pass


# ── User-scoped quote functions ────────────────────────────────────

# Market states where prices must remain frozen (no moving fallback values).
_FROZEN_MARKET_STATES = {
    MarketState.PRE_MARKET,
    MarketState.CLOSING,
    MarketState.AFTER_MARKET,
    MarketState.WEEKEND,
    MarketState.HOLIDAY,
    MarketState.CLOSED,
}
_STALE_QUOTE_MAX_AGE_SECONDS = 120
OFFICIAL_EOD_SOURCE = "official_eod_close"


def _is_market_frozen(state: Optional[MarketState] = None) -> bool:
    if state is None:
        state = market_session.get_current_state()
    return state in _FROZEN_MARKET_STATES


def _normalize_display_source(raw_source: Any, market_open: bool) -> str:
    src = str(raw_source or "").strip().lower()

    if src == OFFICIAL_EOD_SOURCE:
        return OFFICIAL_EOD_SOURCE

    frozen_sources = {
        "frozen",
        "cache",
        "history_snapshot",
        "snapshot",
        "last_price",
        "stale_cache",
        "eod",
    }
    live_sources = {
        "live",
        "live_zebu",
        "live_ws",
        "zebu",
        "market_data_worker",
        "provider",
    }

    if src in frozen_sources:
        return "frozen"

    if not market_open:
        if src in live_sources or src.startswith("live"):
            return "stale_live_ws"
        return "frozen"

    if src in live_sources or src.startswith("live"):
        return "live"

    if not src:
        return "live"

    return "frozen"


def _is_official_eod_quote(quote: Any) -> bool:
    if not isinstance(quote, Mapping):
        return False
    src = str(quote.get("source") or "").lower()
    return src == OFFICIAL_EOD_SOURCE or bool(quote.get("official"))


def _adjust_for_market_state(quote: dict) -> dict:
    """Annotate quote with market status when market is not active.

    Do NOT overwrite price with prev_close. Official EOD close is preserved
    as the authoritative display price after the session ends.
    """
    state = market_session.get_current_state()
    market_open = state == MarketState.OPEN
    quote["market_status"] = state.value if not market_open else "open"
    quote["is_market_open"] = market_open
    quote["market_state"] = state.value.upper() if not market_open else "OPEN"

    ts = _parse_quote_timestamp(
        quote.get("timestamp") or quote.get("last_trade_time") or quote.get("ft")
    )
    quote["last_updated_at"] = int(ts or time.time())
    quote["source"] = _normalize_display_source(quote.get("source"), market_open)

    if _is_official_eod_quote(quote):
        quote["official"] = True
        quote["frozen"] = True
        quote["source"] = OFFICIAL_EOD_SOURCE
        if quote.get("official_close") is None:
            quote["official_close"] = quote.get("price")
        if quote.get("official_close_timestamp") is None and ts:
            quote["official_close_timestamp"] = int(ts)
    elif not market_open:
        quote["frozen"] = True

    return quote


def _parse_quote_timestamp(value: Any) -> Optional[float]:
    """Parse quote timestamp formats (ISO, epoch sec/ms) into epoch seconds."""
    if value in (None, ""):
        return None

    # Numeric epoch path
    try:
        numeric = float(value)
        # Milliseconds epoch
        if numeric > 1_000_000_000_000:
            numeric /= 1000.0
        return numeric if numeric > 0 else None
    except (TypeError, ValueError):
        pass

    # ISO datetime path
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _quote_timestamp(quote: Mapping[str, Any]) -> Optional[float]:
    """Best exchange/session timestamp carried by a cached quote."""
    return _parse_quote_timestamp(
        quote.get("official_close_timestamp")
        or quote.get("exchange_timestamp")
        or quote.get("timestamp")
        or quote.get("last_trade_time")
        or quote.get("ft")
        or quote.get("frozen_at")
    )


def _ist_date_from_epoch(epoch_seconds: Any) -> Optional[str]:
    try:
        ts = float(epoch_seconds)
    except (TypeError, ValueError):
        return None
    if ts > 1_000_000_000_000:
        ts /= 1000.0
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, IST).strftime("%Y-%m-%d")


def _is_current_closed_session_timestamp(epoch_seconds: Any) -> bool:
    """Reject old Redis frozen rows after close while keeping the latest session alive."""
    try:
        ts = float(epoch_seconds)
    except (TypeError, ValueError):
        return False
    if ts > 1_000_000_000_000:
        ts /= 1000.0
    if ts <= 0:
        return False

    now = datetime.now(IST)
    quote_date = datetime.fromtimestamp(ts, IST).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    state = market_session.get_current_state()

    if (
        state in (MarketState.CLOSING, MarketState.AFTER_MARKET, MarketState.CLOSED)
        and now.weekday() < 5
        and (now.hour, now.minute) >= (15, 30)
    ):
        return quote_date == today

    return (time.time() - ts) <= 4 * 86400


def _is_current_closed_session_quote(quote: Any) -> bool:
    if not isinstance(quote, Mapping):
        return False
    ts = _quote_timestamp(quote)
    return _is_current_closed_session_timestamp(ts)


def _is_quote_stale(
    quote: Any, max_age_seconds: int = _STALE_QUOTE_MAX_AGE_SECONDS
) -> bool:
    """True when quote is missing/invalid or timestamp is too old."""
    if not isinstance(quote, Mapping):
        return True

    price = quote.get("price")
    try:
        if float(price) <= 0:
            return True
    except (TypeError, ValueError):
        return True

    ts = _parse_quote_timestamp(
        quote.get("timestamp") or quote.get("last_trade_time") or quote.get("ft")
    )
    if ts is None:
        return False

    return (time.time() - ts) > max_age_seconds


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _sync_enrich_frozen_day_change(quote: Optional[dict]) -> Optional[dict]:
    """Apply Redis frozen payload enrichment in-process (no I/O)."""
    if not quote:
        return quote
    try:
        from cache.redis_client import _enrich_frozen_day_change_payload

        return _enrich_frozen_day_change_payload(quote)
    except Exception:
        return quote


async def _enrich_frozen_quote_day_change(
    symbol: str, quote: Optional[dict]
) -> Optional[dict]:
    """Guarantee day change fields on frozen quotes — Redis fields then daily history."""
    if not quote:
        return None

    enriched = _sync_enrich_frozen_day_change({**quote, "symbol": quote.get("symbol") or symbol})
    if enriched is None:
        return None

    if enriched.get("change") is not None and enriched.get("change_percent") is not None:
        return enriched

    price = _safe_float(
        enriched.get("price")
        or enriched.get("ltp")
        or enriched.get("lp")
        or enriched.get("last_price")
    )
    if price is None or price <= 0:
        return enriched

    session_ts = (
        enriched.get("official_close_timestamp")
        or enriched.get("timestamp")
        or enriched.get("last_trade_time")
        or enriched.get("ft")
    )
    prev_close = await _previous_daily_close(symbol, session_ts)

    # Daily history (5d/1d) may not be in Redis on first boot or after a long weekend.
    # Fall back to the persistent last_price key written at tick-time during trading.
    # During market hours, last_price always carries prev_close (from Zebu's "c" field),
    # and this key has no TTL so it survives across market sessions.
    if prev_close is None or prev_close <= 0:
        try:
            from cache.redis_client import get_last_price as _redis_get_last_price

            _lp_quote = await _redis_get_last_price(symbol)
            if _lp_quote:
                _pc = _safe_float(
                    _lp_quote.get("prev_close")
                    or _lp_quote.get("prevClose")
                    or _lp_quote.get("previous_close")
                )
                if _pc and _pc > 0:
                    prev_close = _pc
        except Exception:
            pass

    if prev_close and prev_close > 0:
        change = round(price - prev_close, 2)
        enriched["prev_close"] = prev_close
        enriched["change"] = change
        enriched["change_percent"] = round((change / prev_close) * 100.0, 2)

    return _sync_enrich_frozen_day_change(enriched)


def _align_quote_with_candle(
    quote: Mapping[str, Any], candle: Mapping[str, Any]
) -> dict:
    """Align quote fields to latest intraday candle so quote/ticker/watchlist match chart close."""
    aligned = dict(quote)

    close = _safe_float(candle.get("close"))
    if close is None or close <= 0:
        return aligned

    aligned["price"] = round(close, 2)
    aligned["ltp"] = aligned["price"]
    aligned["lp"] = aligned["price"]
    aligned["last_price"] = aligned["price"]

    o = _safe_float(candle.get("open"))
    h = _safe_float(candle.get("high"))
    l = _safe_float(candle.get("low"))
    if o is not None and o > 0:
        aligned["open"] = round(o, 2)
    if h is not None and h > 0:
        aligned["high"] = round(h, 2)
    if l is not None and l > 0:
        aligned["low"] = round(l, 2)

    prev_close = _safe_float(
        aligned.get("prev_close")
        or aligned.get("prevClose")
        or aligned.get("close")
        or aligned.get("previous_close")
    )
    if prev_close is not None and prev_close > 0:
        change = close - prev_close
        aligned["change"] = round(change, 2)
        aligned["change_percent"] = round((change / prev_close) * 100.0, 2)

    candle_ts = candle.get("time")
    if candle_ts is not None:
        aligned["timestamp"] = int(candle_ts)

    return aligned


async def _persist_closed_session_quote(symbol: str, quote: Optional[dict]) -> None:
    """Persist the chart-aligned closed-session LTP for watchlists/ticker/indices."""
    if not quote:
        return

    normalized = _normalize_quote({**quote, "symbol": quote.get("symbol") or symbol})
    if not normalized:
        return

    # When the intraday-candle quote has no prev_close (daily history not yet cached),
    # recover it from the existing Redis authoritative close so change/change_percent
    # survive the overwrite instead of being erased.
    if normalized.get("change") is None or normalized.get("change_percent") is None:
        try:
            from cache.redis_client import get_last_price as _redis_get_last_price

            _existing = await _redis_get_last_price(symbol)
            if _existing:
                _pc = _existing.get("prev_close")
                if _pc is not None:
                    try:
                        _pf = round(float(_pc), 2)
                        if _pf > 0:
                            _price = float(normalized.get("price") or 0)
                            normalized["prev_close"] = _pf
                            normalized["change"] = round(_price - _pf, 2)
                            normalized["change_percent"] = round(
                                (normalized["change"] / _pf) * 100.0, 2
                            )
                    except (TypeError, ValueError):
                        pass
                # Fallback: carry over raw change values when prev_close unavailable
                if normalized.get("change") is None:
                    _ec = _existing.get("change")
                    _ep = _existing.get("change_percent")
                    if _ec is not None and _ep is not None:
                        try:
                            normalized["change"] = round(float(_ec), 2)
                            normalized["change_percent"] = round(float(_ep), 2)
                        except (TypeError, ValueError):
                            pass
        except Exception:
            pass

    normalized = await _enrich_frozen_quote_day_change(symbol, normalized)
    if not normalized:
        return

    try:
        from cache.redis_client import set_authoritative_close

        await set_authoritative_close(symbol, normalized)
    except Exception as e:
        logger.debug(f"Closed-session quote persist skipped for {symbol}: {e}")


async def _latest_intraday_candle(symbol: str) -> Optional[dict]:
    """Read latest 1m/5m candle from Redis history for source alignment."""
    try:
        from cache.redis_client import get_history as redis_get_history
        from cache.redis_client import get_last_history as redis_get_last_history
    except Exception:
        return None

    for period, interval in (("1d", "1m"), ("1d", "5m"), ("5d", "5m")):
        try:
            candles = await redis_get_history(symbol, period, interval)
        except Exception:
            candles = None

        if not candles:
            try:
                candles = await redis_get_last_history(symbol, period, interval)
            except Exception:
                candles = None

        normalized = normalize_history_candles(candles or [])
        if normalized:
            latest = normalized[-1]
            if not _is_market_frozen() or _is_current_closed_session_timestamp(
                latest.get("time") or latest.get("timestamp")
            ):
                return latest
            logger.debug(
                "Rejected stale closed-session intraday candle for %s ts=%s",
                symbol,
                latest.get("time") or latest.get("timestamp"),
            )

    return None


async def _previous_daily_close(symbol: str, session_ts: Any = None) -> Optional[float]:
    """Previous trading-day close for day change calculation after market close."""
    try:
        from cache.redis_client import get_history as redis_get_history
        from cache.redis_client import get_last_history as redis_get_last_history
    except Exception:
        return None

    session_date = _ist_date_from_epoch(session_ts)
    for period, interval in (("5d", "1d"), ("1mo", "1d")):
        candles = None
        try:
            candles = await redis_get_history(symbol, period, interval)
        except Exception:
            candles = None

        if not candles:
            try:
                candles = await redis_get_last_history(symbol, period, interval)
            except Exception:
                candles = None

        normalized = normalize_history_candles(candles or [])
        if len(normalized) < 2:
            continue

        if session_date:
            prior = []
            for candle in normalized:
                candle_date = _ist_date_from_epoch(candle.get("time") or candle.get("timestamp"))
                if candle_date and candle_date < session_date:
                    prior.append(candle)
            if prior:
                close = _safe_float(prior[-1].get("close"))
                if close and close > 0:
                    return round(close, 2)

        close = _safe_float(normalized[-2].get("close"))
        if close and close > 0:
            return round(close, 2)

    return None


async def _quote_from_latest_intraday_candle(symbol: str) -> Optional[dict]:
    """Build a minimal quote from last persisted intraday candle when market is closed."""
    candle = await _latest_intraday_candle(symbol)
    if not candle:
        return None

    close_price = _safe_float(candle.get("close"))
    if close_price is None or close_price <= 0:
        return None

    open_price = _safe_float(candle.get("open"))
    high_price = _safe_float(candle.get("high"))
    low_price = _safe_float(candle.get("low"))
    volume = _safe_float(candle.get("volume"))
    try:
        session_ts = int(float(candle.get("time") or time.time()))
    except (TypeError, ValueError):
        session_ts = int(time.time())
    prev_close = await _previous_daily_close(symbol, session_ts)
    change = None
    change_percent = None
    if prev_close and prev_close > 0:
        change = round(close_price - prev_close, 2)
        change_percent = round((change / prev_close) * 100.0, 2)

    base_name = symbol.replace(".NS", "").replace(".BO", "")
    quote = {
        "symbol": symbol,
        "name": base_name,
        "price": round(close_price, 2),
        "ltp": round(close_price, 2),
        "lp": round(close_price, 2),
        "last_price": round(close_price, 2),
        "change": change,
        "change_percent": change_percent,
        "prev_close": prev_close,
        "open": round(open_price, 2) if open_price and open_price > 0 else 0.0,
        "high": round(high_price, 2) if high_price and high_price > 0 else 0.0,
        "low": round(low_price, 2) if low_price and low_price > 0 else 0.0,
        "volume": int(volume) if volume and volume > 0 else 0,
        "timestamp": session_ts,
        "source": "history_snapshot",
        "market_session": "closed",
        "official_close": round(close_price, 2),
        "official_close_timestamp": int(candle.get("time") or time.time()),
        "official": True,
        "frozen": True,
    }
    return _adjust_for_market_state(quote)


async def _get_frozen_quote_snapshot(symbol: str) -> Optional[dict]:
    """
    Return the best frozen quote for non-chart displays when market is closed.

    Priority (same source family as charts — Zebu daily EOD, not stale intraday Redis):
      1. official_eod_close already in Redis last_price
      2. Live Zebu EOD / get_historical_data (writes official close to Redis)
      3. Validated Redis daily candle only
      4. Never use stale live_ws or misaligned intraday as primary
    """
    try:
        from cache.redis_client import get_last_price as redis_get_last_price
        from services.market_eod_reconciliation import (
            fetch_official_eod_close,
            is_official_eod_quote,
            is_rejected_live_tick_for_closed_market,
        )

        frozen_quote = await redis_get_last_price(symbol)
        if (
            frozen_quote
            and is_official_eod_quote(frozen_quote)
            and _is_current_closed_session_quote(frozen_quote)
        ):
            normalized = _normalize_quote(frozen_quote)
            if normalized:
                enriched = await _enrich_frozen_quote_day_change(symbol, normalized)
                return _adjust_for_market_state(enriched or normalized)
        elif frozen_quote and is_official_eod_quote(frozen_quote):
            logger.debug(
                "Rejected stale official EOD Redis quote for %s ts=%s",
                symbol,
                _quote_timestamp(frozen_quote),
            )

        # Fetch fresh EOD from Zebu (charts use this path — ticker/watchlist must match).
        eod_quote = await fetch_official_eod_close(symbol)
        if eod_quote:
            from cache.redis_client import set_authoritative_close

            enriched_eod = await _enrich_frozen_quote_day_change(symbol, eod_quote)
            await set_authoritative_close(symbol, enriched_eod or eod_quote)
            normalized = _normalize_quote(enriched_eod or eod_quote)
            if normalized:
                return _adjust_for_market_state(normalized)

        if (
            frozen_quote
            and _is_current_closed_session_quote(frozen_quote)
            and not is_rejected_live_tick_for_closed_market(frozen_quote)
        ):
            normalized_frozen = _normalize_quote(frozen_quote)
            if normalized_frozen:
                normalized_frozen["source"] = normalized_frozen.get("source") or "frozen"
                enriched = await _enrich_frozen_quote_day_change(symbol, normalized_frozen)
                return _adjust_for_market_state(enriched or normalized_frozen)
        elif frozen_quote:
            logger.debug(
                "Rejected stale frozen Redis quote for %s ts=%s source=%s",
                symbol,
                _quote_timestamp(frozen_quote),
                frozen_quote.get("source"),
            )
    except Exception as e:
        logger.debug(f"Frozen snapshot resolution failed for {symbol}: {e}")

    return None


async def _get_closed_session_quote(symbol: str) -> Optional[dict]:
    """
    Closed-session quote aligned with chart last candle when available.

    Charts read Redis intraday history; ticker/watchlist must use the same close
    instead of a stale official snapshot or misaligned hot Redis price.
    """
    history_quote = await _quote_from_latest_intraday_candle(symbol)
    if history_quote:
        enriched = await _enrich_frozen_quote_day_change(symbol, history_quote)
        result = enriched or history_quote

        # Intraday candles don't carry prev_close themselves; enrichment derives it from
        # daily history or last_price Redis key.  If both are unavailable (e.g. cold boot),
        # pull prev_close from the official EOD snapshot — which fetches from Zebu when
        # Redis has no authoritative close — so the returned quote always has change data.
        if result.get("change") is None or result.get("change_percent") is None:
            try:
                snap = await _get_frozen_quote_snapshot(symbol)
                if snap:
                    _prev = _safe_float(snap.get("prev_close"))
                    _price = _safe_float(
                        result.get("price") or result.get("ltp") or result.get("lp")
                    )
                    if _prev and _prev > 0 and _price:
                        _ch = round(_price - _prev, 2)
                        result = {
                            **result,
                            "prev_close": _prev,
                            "change": _ch,
                            "change_percent": round((_ch / _prev) * 100.0, 2),
                        }
            except Exception as _e:
                logger.debug("Snapshot prev_close fallback skipped for %s: %s", symbol, _e)

        await _persist_closed_session_quote(symbol, result)
        return result

    frozen = await _get_frozen_quote_snapshot(symbol)
    if not frozen:
        return None

    try:
        candle = await _latest_intraday_candle(symbol)
        if candle:
            aligned = _align_quote_with_candle(frozen, candle)
            enriched = await _enrich_frozen_quote_day_change(symbol, aligned)
            await _persist_closed_session_quote(symbol, enriched or aligned)
            return enriched or aligned
    except Exception as e:
        logger.debug(f"Closed-session candle align skipped for {symbol}: {e}")

    enriched_frozen = await _enrich_frozen_quote_day_change(symbol, frozen)
    await _persist_closed_session_quote(symbol, enriched_frozen or frozen)
    return enriched_frozen or frozen


async def _align_quote_to_history(symbol: str, quote: Optional[dict]) -> Optional[dict]:
    """Normalize quote and align to latest intraday history close when available."""
    normalized = _normalize_quote(quote)
    if not normalized:
        return None

    try:
        candle = await _latest_intraday_candle(symbol)
        if candle:
            normalized = _align_quote_with_candle(normalized, candle)
    except Exception as e:
        logger.debug(f"History alignment skipped for {symbol}: {e}")

    return normalized


async def get_quote(symbol: str, user_id: str) -> dict:
    """
    Get real-time quote for a symbol via the user's ZebuProvider.

    Raises:
        BrokerNotConnected       – user has no active session.
        ProviderDataUnavailable  – provider returned None for the symbol.
    """
    symbol = _format_symbol(symbol)
    provider = _get_provider_for_user(user_id)
    quote = await provider.get_quote(symbol)
    quote = await _align_quote_to_history(symbol, quote)
    if quote is None:
        raise ProviderDataUnavailable(
            f"{type(provider).__name__} returned no data for {symbol}"
        )
    return _adjust_for_market_state(quote)


async def get_quote_safe(symbol: str, user_id: str) -> Optional[dict]:
    """Like get_quote() but returns None instead of raising on safe errors."""
    fmt = _format_symbol(symbol)
    market_frozen = _is_market_frozen()

    # Prefer Redis-backed broker stream data first (authoritative across API calls).
    # During closed sessions, allow frozen last-tradable price.
    try:
        from cache.redis_client import get_price as redis_get_price

        redis_quote = await redis_get_price(fmt)
        normalized_redis = await _align_quote_to_history(fmt, redis_quote)
        if normalized_redis:
            if market_frozen:
                if _is_official_eod_quote(normalized_redis):
                    enriched = await _enrich_frozen_quote_day_change(fmt, normalized_redis)
                    return _adjust_for_market_state(enriched or normalized_redis)
            elif not _is_quote_stale(normalized_redis):
                return _adjust_for_market_state(normalized_redis)

        if market_frozen:
            return await _get_closed_session_quote(fmt)
    except Exception as e:
        logger.debug(f"Redis quote read failed for {fmt}: {e}")

    if market_frozen:
        return await _get_closed_session_quote(fmt)

    # Deduplication: if identical request is in-flight, wait for it
    dedup_key = f"{fmt}:{user_id}"
    if dedup_key in _symbol_requests:
        try:
            return await _symbol_requests[dedup_key].task
        except Exception:
            pass  # Fall through to new request

    async def _fetch():
        try:
            try:
                provider = _get_provider_for_user(user_id)
                result = await _call_provider_with_timeout(
                    provider.get_quote(fmt), fmt, PROVIDER_TIMEOUT_SECONDS
                )
                normalized = await _align_quote_to_history(fmt, result)
                if normalized:
                    return _adjust_for_market_state(normalized)
                return None
            except (BrokerNotConnected, RuntimeError):
                return None
        except Exception as e:
            logger.debug(f"get_quote_safe({fmt}) error: {e}")
            return None

    request_task = asyncio.create_task(_fetch())
    _symbol_requests[dedup_key] = _RequestInFlight(request_task, time.time())
    try:
        quote = await request_task
        if quote:
            return quote

        # Live provider unavailable during market hours — keep last known price visible.
        if market_frozen:
            return await _get_closed_session_quote(fmt)
        return await _get_frozen_quote_snapshot(fmt)
    finally:
        if dedup_key in _symbol_requests:
            del _symbol_requests[dedup_key]


# ── System-level quote functions (no user context) ─────────────────


async def get_system_quote(symbol: str) -> dict:
    """
    Get a quote using ANY available provider session.
    For system-level tasks (workers, ZeroLoss) that don't have user context.

    Raises RuntimeError if no sessions exist.
    """
    symbol = _format_symbol(symbol)
    provider = _get_any_provider()
    quote = await provider.get_quote(symbol)
    quote = await _align_quote_to_history(symbol, quote)
    if quote is None:
        raise ProviderDataUnavailable(
            f"{type(provider).__name__} returned no data for {symbol}"
        )
    return _adjust_for_market_state(quote)


async def get_system_quote_safe(symbol: str) -> Optional[dict]:
    """System-level quote using master Zebu or any active provider session."""
    fmt = _format_symbol(symbol)
    market_frozen = _is_market_frozen()

    # Closed/holiday: match chart last intraday close when history is available.
    if market_frozen:
        return await _get_closed_session_quote(fmt)

    # Prefer Redis-backed broker stream data first (authoritative across API calls).
    try:
        from cache.redis_client import get_price as redis_get_price

        redis_quote = await redis_get_price(fmt)
        normalized_redis = await _align_quote_to_history(fmt, redis_quote)
        if normalized_redis and not _is_quote_stale(normalized_redis):
            return _adjust_for_market_state(normalized_redis)
    except Exception as e:
        logger.debug(f"Redis system quote read failed for {fmt}: {e}")

    # Deduplication: if identical request is in-flight, wait for it
    dedup_key = f"sys:{fmt}"
    if dedup_key in _symbol_requests:
        try:
            return await _symbol_requests[dedup_key].task
        except Exception:
            pass

    async def _fetch():
        try:
            provider = _get_any_provider()
            result = await _call_provider_with_timeout(
                provider.get_quote(fmt), fmt, PROVIDER_TIMEOUT_SECONDS
            )
            normalized = await _align_quote_to_history(fmt, result)
            if normalized:
                return _adjust_for_market_state(normalized)
            return None
        except (RuntimeError, Exception) as e:
            logger.debug(f"get_system_quote_safe({fmt}) error: {e}")
            return None

    request_task = asyncio.create_task(_fetch())
    _symbol_requests[dedup_key] = _RequestInFlight(request_task, time.time())
    try:
        quote = await request_task
        if quote:
            return quote

        # Live provider unavailable during market hours — keep last known price visible.
        return await _get_frozen_quote_snapshot(fmt)
    finally:
        if dedup_key in _symbol_requests:
            del _symbol_requests[dedup_key]


async def get_system_quote_live_only(
    symbol: str, allow_recover: bool = True
) -> Optional[dict]:
    """System-level quote that allows only live Zebu (plus Redis snapshots), never Yahoo/demo."""
    fmt = _format_symbol(symbol)
    market_frozen = _is_market_frozen()

    try:
        from cache.redis_client import get_price as redis_get_price

        redis_quote = await redis_get_price(fmt)
        normalized_redis = await _align_quote_to_history(fmt, redis_quote)
        if normalized_redis:
            if market_frozen:
                if _is_official_eod_quote(normalized_redis):
                    enriched = await _enrich_frozen_quote_day_change(fmt, normalized_redis)
                    return _adjust_for_market_state(enriched or normalized_redis)
            elif not _is_quote_stale(normalized_redis):
                return _adjust_for_market_state(normalized_redis)

        if market_frozen:
            return await _get_closed_session_quote(fmt)
    except Exception as e:
        logger.debug(f"Redis live-only system quote read failed for {fmt}: {e}")

    if market_frozen:
        return await _get_closed_session_quote(fmt)

    dedup_key = f"sys_live:{fmt}"
    if dedup_key in _symbol_requests:
        try:
            return await _symbol_requests[dedup_key].task
        except Exception:
            pass

    async def _fetch():
        provider = await _get_any_provider_live(allow_recover=allow_recover)
        if provider is None:
            return None

        result = await _get_provider_quote_live(provider, fmt)
        normalized = await _align_quote_to_history(fmt, result)
        if normalized:
            normalized.setdefault("source", "zebu")
            return _adjust_for_market_state(normalized)
        return None

    request_task = asyncio.create_task(_fetch())
    _symbol_requests[dedup_key] = _RequestInFlight(request_task, time.time())
    try:
        quote = await request_task
        if quote:
            return quote

        # Live provider unavailable during market hours — keep last known price visible.
        return await _get_frozen_quote_snapshot(fmt)
    finally:
        if dedup_key in _symbol_requests:
            del _symbol_requests[dedup_key]


async def get_historical_data_live_only(
    symbol: str,
    period: str = "1mo",
    interval: str = "1d",
    user_id: Optional[str] = None,
    allow_recover: bool = True,
) -> list:
    """Historical candles from live Zebu provider only (with Redis snapshot fallback)."""
    symbol = _format_symbol(symbol)
    cache_key = f"hist_live:{symbol}:{period}:{interval}"

    if cache_key in _symbol_requests:
        try:
            return await _symbol_requests[cache_key].task
        except Exception:
            pass

    async def _get_redis_history_fallback() -> list:
        try:
            from cache.redis_client import get_history as redis_get_history
            from cache.redis_client import get_last_history as redis_get_last_history
        except Exception:
            return []

        try:
            cached = await redis_get_history(symbol, period, interval)
        except Exception:
            cached = None

        normalized = normalize_history_candles(cached or [])
        if normalized:
            return normalized

        try:
            last_cached = await redis_get_last_history(symbol, period, interval)
        except Exception:
            last_cached = None

        return normalize_history_candles(last_cached or [])

    async def _fetch_history():
        provider = None
        try:
            if user_id:
                provider = _get_provider_for_user(user_id)
            else:
                provider = await _get_any_provider_live(allow_recover=allow_recover)
        except (BrokerNotConnected, RuntimeError):
            provider = await _get_any_provider_live(allow_recover=allow_recover)
        except Exception as e:
            logger.debug(f"Live-only history provider lookup failed for {symbol}: {e}")

        if provider is not None:
            candles = await _call_provider_with_timeout(
                provider.get_historical_data(symbol, period=period, interval=interval),
                symbol,
                PROVIDER_TIMEOUT_SECONDS,
            )
            normalized = normalize_history_candles(candles) if candles else []
            if normalized:
                return normalized

        fallback = await _get_redis_history_fallback()
        if fallback:
            logger.debug(
                "get_historical_data_live_only(%s) using Redis fallback (%s %s, %d candles)",
                symbol,
                period,
                interval,
                len(fallback),
            )
        return fallback

    request_task = asyncio.create_task(_fetch_history())
    _symbol_requests[cache_key] = _RequestInFlight(request_task, time.time())
    try:
        return await request_task
    finally:
        if cache_key in _symbol_requests:
            del _symbol_requests[cache_key]


async def get_historical_data(
    symbol: str,
    period: str = "1mo",
    interval: str = "1d",
    user_id: Optional[str] = None,
) -> list:
    """
    Get historical OHLCV data for charts via Zebu live data only.
    """
    symbol = _format_symbol(symbol)

    cache_key = f"hist:{symbol}:{period}:{interval}"
    if cache_key in _symbol_requests:
        try:
            return await _symbol_requests[cache_key].task
        except Exception:
            pass

    async def _get_redis_history_fallback() -> list:
        """Use persisted Redis history when live provider history is unavailable."""
        try:
            from cache.redis_client import get_history as redis_get_history
            from cache.redis_client import get_last_history as redis_get_last_history
        except Exception:
            return []

        lookup_pairs: list[tuple[str, str]] = [(period, interval)]
        if _is_index_symbol(symbol):
            seen = {lookup_pairs[0]}
            for pair in _INDEX_REDIS_HISTORY_ATTEMPTS:
                if pair not in seen:
                    seen.add(pair)
                    lookup_pairs.append(pair)

        best_any: list = []

        for hist_period, hist_interval in lookup_pairs:
            cached = None
            try:
                cached = await redis_get_history(symbol, hist_period, hist_interval)
            except Exception:
                cached = None

            normalized = normalize_history_candles(cached or [])
            if normalized:
                if _history_has_volume(normalized):
                    return normalized
                if not best_any:
                    best_any = normalized
                continue

            try:
                last_cached = await redis_get_last_history(
                    symbol, hist_period, hist_interval
                )
            except Exception:
                last_cached = None

            normalized = normalize_history_candles(last_cached or [])
            if not normalized:
                continue
            if _history_has_volume(normalized):
                return normalized
            if not best_any:
                best_any = normalized

        return best_any

    async def _fetch_history():
        is_index = _is_index_symbol(symbol)
        is_intraday = interval in _INTRADAY_HISTORY_INTERVALS

        async def _finalize_index(candles: list) -> list:
            if not candles or not is_index or not is_intraday:
                return candles or []
            return await _enrich_index_candles_with_futures_volume(
                candles, symbol, period, interval
            )

        # Index charts: prefer worker-built Redis history (tick deltas) when available.
        if is_index and is_intraday:
            redis_first = await _get_redis_history_fallback()
            if redis_first and _history_has_volume(redis_first):
                logger.debug(
                    "get_historical_data(%s) using Redis worker history (%s %s, %d candles)",
                    symbol,
                    period,
                    interval,
                    len(redis_first),
                )
                return await _finalize_index(redis_first)

        try:
            if user_id:
                provider = _get_provider_for_user(user_id)
            else:
                provider = _get_any_provider()

            candles = await _call_provider_with_timeout(
                provider.get_historical_data(symbol, period=period, interval=interval),
                symbol,
                PROVIDER_TIMEOUT_SECONDS,
            )
            normalized = normalize_history_candles(candles) if candles else []
            if is_index and is_intraday:
                logger.debug(
                    "Index history raw provider %s (%s %s): candles=%d positive_volume=%d",
                    symbol,
                    period,
                    interval,
                    len(normalized),
                    _positive_volume_count(normalized),
                )

            if normalized and is_index and is_intraday and not _history_has_volume(normalized):
                try:
                    from providers.zebu_provider import ZebuProvider

                    normalized = ZebuProvider._convert_monotonic_volumes_to_deltas(
                        normalized
                    )
                except Exception:
                    pass
                if normalized:
                    logger.debug(
                        "Index history monotonic-convert %s (%s %s): positive_volume=%d",
                        symbol,
                        period,
                        interval,
                        _positive_volume_count(normalized),
                    )

            if normalized and is_index and is_intraday and not _history_has_volume(normalized):
                redis_hist = await _get_redis_history_fallback()
                if redis_hist and _history_has_volume(redis_hist):
                    tolerance = max(60, _interval_seconds(interval))
                    normalized = _merge_volume_by_nearest_time(
                        normalized, redis_hist, tolerance_sec=tolerance
                    )
                    nearest_count = _positive_volume_count(normalized)
                    if not _history_has_volume(normalized):
                        normalized = _merge_volume_by_time(normalized, redis_hist)
                    exact_count = _positive_volume_count(normalized)
                    logger.debug(
                        "Index history Redis merge %s (%s %s): redis_pos=%d nearest_pos=%d exact_pos=%d tolerance=%ds",
                        symbol,
                        period,
                        interval,
                        _positive_volume_count(redis_hist),
                        nearest_count,
                        exact_count,
                        tolerance,
                    )
                elif redis_hist and len(redis_hist) >= max(2, len(normalized) // 2):
                    logger.debug(
                        "get_historical_data(%s) merging Redis volume into index OHLC (%s %s)",
                        symbol,
                        period,
                        interval,
                    )
                    tolerance = max(60, _interval_seconds(interval))
                    merged = _merge_volume_by_nearest_time(
                        normalized, redis_hist, tolerance_sec=tolerance
                    )
                    if not _history_has_volume(merged):
                        merged = _merge_volume_by_time(merged, redis_hist)
                    normalized = merged

            if normalized:
                if is_index and is_intraday:
                    logger.debug(
                        "Index history final %s (%s %s): candles=%d positive_volume=%d",
                        symbol,
                        period,
                        interval,
                        len(normalized),
                        _positive_volume_count(normalized),
                    )
                return await _finalize_index(normalized)

            fallback = await _get_redis_history_fallback()
            if fallback:
                logger.debug(
                    "get_historical_data(%s) using Redis fallback (%s %s, %d candles)",
                    symbol,
                    period,
                    interval,
                    len(fallback),
                )
            return await _finalize_index(fallback)
        except (BrokerNotConnected, RuntimeError):
            fallback = await _get_redis_history_fallback()
            if fallback:
                return await _finalize_index(fallback)
            return []
        except Exception as e:
            logger.debug(f"get_historical_data({symbol}) error: {e}")
            fallback = await _get_redis_history_fallback()
            if fallback:
                return await _finalize_index(fallback)
            return []

    request_task = asyncio.create_task(_fetch_history())
    _symbol_requests[cache_key] = _RequestInFlight(request_task, time.time())
    try:
        return await request_task
    finally:
        if cache_key in _symbol_requests:
            del _symbol_requests[cache_key]


async def search_stocks(query: str) -> list:
    """Search for Indian stocks — local + Zebu SearchScrip only.

    Priority order:
    1. Local NSE list (~400 stocks, instant, prefix-ranked)
    2. Zebu SearchScrip API (real broker data, covers ALL NSE stocks)

    Results are merged, deduplicated, and returned (max 20).
    """
    query_upper = query.upper().strip()
    if not query_upper:
        return []

    # ── Check search cache ─────────────────────────────────────────────────────
    now = time.time()
    if (
        query_upper in _search_cache
        and (now - _search_cache_ts.get(query_upper, 0)) < SEARCH_CACHE_DURATION
    ):
        return _search_cache[query_upper]

    # ── Step 0: Search indices (NIFTY, SENSEX, BANK NIFTY, etc.) ────────────
    index_matches = []
    for idx in INDIAN_INDICES:
        idx_name_upper = idx["name"].upper()
        idx_sym_upper = idx["symbol"].upper().replace("^", "")
        if (
            query_upper in idx_name_upper
            or query_upper in idx_sym_upper
            or idx_name_upper.startswith(query_upper)
        ):
            index_matches.append(
                {
                    "symbol": idx["symbol"],
                    "name": idx["name"],
                    "exchange": "NSE",
                    "kind": "index",
                }
            )

    # ── Step 1: Local search with ranking (instant) ────────────────────────────
    prefix_matches = []
    substring_matches = []
    for stock in NSE_STOCK_LIST:
        sym_upper = stock["symbol"].upper().replace(".NS", "")
        name_upper = stock["name"].upper()
        if sym_upper.startswith(query_upper) or name_upper.startswith(query_upper):
            prefix_matches.append(stock)
        elif query_upper in sym_upper or query_upper in name_upper:
            substring_matches.append(stock)
    local_results = index_matches + prefix_matches + substring_matches

    # ── Step 2: Remote search (Zebu SearchScrip only) ─────────────────────────
    has_broker = False
    try:
        _get_any_provider()
        has_broker = True
    except (RuntimeError, Exception):
        pass

    if has_broker:
        zebu_results = await _search_zebu(query_upper)
        remote_results = zebu_results if isinstance(zebu_results, list) else []
    else:
        remote_results = []

    # ── Step 3: Merge & deduplicate ────────────────────────────────────────────
    seen = set()
    merged = []

    # Local results first (best ranking, reliable names)
    for r in local_results:
        sym = r["symbol"]
        if sym not in seen:
            seen.add(sym)
            merged.append(r)

    # Then remote results (Zebu SearchScrip)
    for r in remote_results:
        sym = r["symbol"]
        if sym not in seen:
            seen.add(sym)
            merged.append(r)

    result = merged[:20]

    # Cache the result
    _search_cache[query_upper] = result
    _search_cache_ts[query_upper] = now

    return result


async def _search_zebu(query: str) -> list:
    """Search for instruments via Zebu SearchScrip API."""
    try:
        from providers.symbol_mapper import load_zebu_contracts

        provider = _get_any_provider()
        data = await provider._rest_post(
            "/SearchScrip",
            {
                "exch": "NSE",
                "stext": query,
            },
        )
        if not data or data.get("stat") != "Ok":
            return []

        results = []
        contracts_to_register = []
        for item in data.get("values", []):
            tsym = item.get("tsym", "")
            token = item.get("token", "")
            # Filter to EQ segment only
            if "-EQ" not in tsym:
                continue
            name = tsym.replace("-EQ", "")
            symbol = f"{name}.NS"
            results.append(
                {
                    "symbol": symbol,
                    "name": item.get("instname", name),
                    "exchange": "NSE",
                    "token": token,
                }
            )
            if token:
                contracts_to_register.append(
                    {"symbol": name, "token": token, "exchange": "NSE"}
                )

        # Register found tokens so subsequent quotes/history work without SearchScrip
        if contracts_to_register:
            load_zebu_contracts(contracts_to_register)

        return results[:15]
    except (RuntimeError, Exception) as e:
        logger.debug(f"Zebu SearchScrip failed: {e}")
        return []


async def get_index_advances_declines(index_symbol: str, price: Optional[float] = None, chg_pct: Optional[float] = None) -> dict:
    """Calculate advances, declines, and unchanged counts for indices."""
    constituents = {
        "^NSEI": [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
            "ITC.NS", "LT.NS", "SBIN.NS", "BHARTIARTL.NS", "HINDUNILVR.NS",
            "KOTAKBANK.NS", "AXISBANK.NS", "M&M.NS", "SUNPHARMA.NS", "MARUTI.NS",
            "HCLTECH.NS", "TATAMOTORS.NS", "TITAN.NS", "BAJFINANCE.NS", "ADANIENT.NS",
            "ULTRACEMCO.NS", "POWERGRID.NS", "NTPC.NS", "TATASTEEL.NS", "ADANIPORTS.NS",
            "GRASIM.NS", "INDUSINDBK.NS", "NESTLEIND.NS", "HINDALCO.NS", "ONGC.NS",
            "COALINDIA.NS", "TECHM.NS", "CIPLA.NS", "WIPRO.NS", "APOLLOHOSP.NS",
            "BRITANNIA.NS", "EICHERMOT.NS", "HEROMOTOCO.NS", "BPCL.NS", "TATACONSUM.NS",
            "BEL.NS", "HAL.NS", "JSWSTEEL.NS", "ASIANPAINT.NS", "BAJAJFINSV.NS",
            "LTIM.NS", "SBILIFE.NS", "HDFCLIFE.NS", "SHRIRAMFIN.NS", "MUTHOOTFIN.NS"
        ],
        "^BSESN": [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
            "ITC.NS", "LT.NS", "SBIN.NS", "BHARTIARTL.NS", "HINDUNILVR.NS",
            "KOTAKBANK.NS", "AXISBANK.NS", "M&M.NS", "SUNPHARMA.NS", "MARUTI.NS",
            "HCLTECH.NS", "TATAMOTORS.NS", "TITAN.NS", "BAJFINANCE.NS", "ULTRACEMCO.NS",
            "POWERGRID.NS", "NTPC.NS", "TATASTEEL.NS", "INDUSINDBK.NS", "NESTLEIND.NS",
            "JSWSTEEL.NS", "ASIANPAINT.NS", "TECHM.NS", "WIPRO.NS", "LTIM.NS"
        ],
        "^NSEBANK": [
            "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS",
            "INDUSINDBK.NS", "FEDERALBNK.NS", "IDFCFIRSTB.NS", "AUBANK.NS", "PNB.NS",
            "BANKBARODA.NS", "BANDHANBNK.NS"
        ],
        "^CNXFIN": [
            "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS",
            "BAJFINANCE.NS", "CHOLAFIN.NS", "SHRIRAMFIN.NS", "MUTHOOTFIN.NS", "HDFCLIFE.NS",
            "SBILIFE.NS", "PFC.NS", "RECLTD.NS", "LICHSGFIN.NS", "M&MFIN.NS", "BAJAJFINSV.NS"
        ]
    }
    
    syms = constituents.get(index_symbol)
    if not syms:
        return {"advances": 0, "declines": 0, "unchanged": 0}
        
    total = len(syms)
    
    try:
        from cache.redis_client import get_batch_prices
        prices = await get_batch_prices(syms)
        
        adv = 0
        dec = 0
        unc = 0
        has_prices = False
        
        for s in syms:
            q = prices.get(s) or prices.get(s.replace(".NS", ""))
            if q and q.get("price") is not None:
                has_prices = True
                chg = q.get("change")
                if chg is not None:
                    try:
                        chg_f = float(chg)
                        if chg_f > 0:
                            adv += 1
                        elif chg_f < 0:
                            dec += 1
                        else:
                            unc += 1
                    except (TypeError, ValueError):
                        unc += 1
                else:
                    unc += 1
            else:
                unc += 1
                
        if has_prices and (adv > 0 or dec > 0):
            return {"advances": adv, "declines": dec, "unchanged": unc}
    except Exception as e:
        logger.debug(f"Redis fetch for constituents failed: {e}")

    # Deterministic fallback based on index price and change percent
    val = chg_pct if chg_pct is not None else 0.0
    price_seed = price if price is not None else 10000.0
    
    import random
    rnd = random.Random(int(price_seed * 100) if price_seed else 42)
    
    clipped = max(-3.0, min(3.0, val))
    adv_ratio = 0.5 + (clipped / 3.0) * 0.35 + rnd.uniform(-0.06, 0.06)
    adv_ratio = max(0.05, min(0.95, adv_ratio))
    
    adv = int(total * adv_ratio)
    dec = int(total * (1.0 - adv_ratio) * 0.9)
    unc = total - adv - dec
    
    return {"advances": adv, "declines": dec, "unchanged": unc}


async def get_indices(user_id: Optional[str] = None) -> list:
    """Get Indian market indices — fetches all in parallel for speed."""
    import asyncio as _asyncio

    async def _fetch_one(idx_info):
        try:
            if user_id:
                quote = await get_quote_safe(idx_info["symbol"], user_id)
            else:
                quote = await get_system_quote_safe(idx_info["symbol"])
            if quote:
                quote["name"] = idx_info["name"]
                
                # Enrich with advances, declines, unchanged stats
                stats = await get_index_advances_declines(
                    idx_info["symbol"],
                    price=quote.get("price"),
                    chg_pct=quote.get("change_percent")
                )
                quote.update(stats)
                
                return quote
        except Exception as e:
            logger.debug(f"get_indices fetch_one failed for {idx_info['symbol']}: {e}")
            pass
        return None

    results = await _asyncio.gather(
        *[_fetch_one(idx) for idx in INDIAN_INDICES],
        return_exceptions=True,
    )
    return [r for r in results if isinstance(r, dict)]


async def get_ticker_data(user_id: Optional[str] = None) -> list:
    """
    Get indices + all popular stocks for the scrolling ticker bar.

    All symbols fetched in parallel via Zebu live data only.
    """
    import asyncio as _asyncio

    def _normalise_quote(raw_quote: Any, *, name: str, kind: str) -> Optional[dict]:
        if not raw_quote:
            return None
        if isinstance(raw_quote, Mapping):
            quote = dict(raw_quote)
        elif isinstance(raw_quote, dict):
            quote = raw_quote.copy()
        else:
            logger.warning(
                f"Ticker quote ignored for {name}: unexpected type {type(raw_quote).__name__}"
            )
            return None
        quote["name"] = name
        quote["kind"] = kind
        return quote

    async def _fetch_one(symbol: str, name: str, kind: str):
        """Fetch single ticker item with timeout protection."""
        try:
            coro = None
            if user_id:
                coro = get_quote_safe(symbol, user_id)
            else:
                coro = get_system_quote_safe(symbol)

            # Tight timeout for ticker items (2s)
            quote = await asyncio.wait_for(coro, timeout=2.0)
            return _normalise_quote(quote, name=name, kind=kind)
        except (asyncio.TimeoutError, Exception) as e:
            logger.debug(f"Ticker fetch timeout/error ({symbol}): {e}")
            return None

    # Build task list: indices first, then popular stocks
    tasks = []
    for idx_info in INDIAN_INDICES:
        tasks.append(_fetch_one(idx_info["symbol"], idx_info["name"], "index"))
    for stock in POPULAR_INDIAN_STOCKS:
        tasks.append(_fetch_one(stock["symbol"], stock["name"], "stock"))

    results = await _asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


async def get_batch_quotes(symbols: list[str], user_id: Optional[str] = None) -> dict:
    """
    Get quotes for multiple symbols via Zebu live data only.

    Deduplicates concurrent identical requests.
    """
    symbol_list = [_format_symbol(s) for s in symbols if s]
    if not symbol_list:
        return {}

    # Deduplication: check if identical batch request is in-flight
    batch_key = f"batch:{','.join(sorted(symbol_list))}"
    if batch_key in _batch_requests:
        try:
            return await _batch_requests[batch_key].task
        except Exception:
            pass

    async def _fetch_batch():
        # Prefer Redis live batch first (broker-streamed Zebu data).
        # Call provider only for symbols still missing.
        results: dict[str, dict] = {}
        market_frozen = _is_market_frozen()

        try:
            from cache.redis_client import get_batch_prices as redis_get_batch_prices
            from cache.redis_client import get_last_price as redis_get_last_price

            if market_frozen:
                # Hot price:* keys can be stale after close — prefer chart-aligned history.
                for sym in symbol_list:
                    closed_quote = await _get_closed_session_quote(sym)
                    if closed_quote:
                        results[sym] = closed_quote
            else:
                cached_batch = await redis_get_batch_prices(symbol_list)
                for sym in symbol_list:
                    cached_quote = cached_batch.get(sym)
                    normalized_cached = await _align_quote_to_history(sym, cached_quote)
                    if not normalized_cached:
                        continue
                    if not _is_quote_stale(normalized_cached):
                        results[sym] = _adjust_for_market_state(normalized_cached)

                for sym in symbol_list:
                    if sym in results:
                        continue
                    frozen_quote = await redis_get_last_price(sym)
                    normalized_frozen = await _align_quote_to_history(sym, frozen_quote)
                    if normalized_frozen:
                        results[sym] = _adjust_for_market_state(normalized_frozen)
        except Exception as e:
            logger.debug(f"Redis batch read failed: {e}")

        missing_symbols = [sym for sym in symbol_list if sym not in results]
        if not missing_symbols:
            return results

        # Frozen market: serve persisted snapshots only (no moving fallbacks).
        if market_frozen:
            return {sym: q for sym, q in results.items() if q}

        # Register exact Zebu tokens from NSE master before live provider fetch.
        try:
            from services.contract_loader import ensure_nse_equity_mappings

            await ensure_nse_equity_mappings(missing_symbols)
        except Exception as e:
            logger.debug(f"NSE master preload for batch quotes skipped: {e}")

        provider_results = {}
        try:
            if user_id:
                provider = _get_provider_for_user(user_id)
            else:
                provider = _get_any_provider()

            provider_quotes = await asyncio.wait_for(
                _call_provider_with_timeout(
                    provider.get_batch_quotes(missing_symbols),
                    ",".join(missing_symbols[:3]),
                    PROVIDER_TIMEOUT_SECONDS,
                ),
                timeout=PROVIDER_TIMEOUT_SECONDS,
            )
            if provider_quotes:
                provider_results.update(provider_quotes)
        except (BrokerNotConnected, RuntimeError):
            pass
        except (asyncio.TimeoutError, Exception) as e:
            logger.debug(f"Provider batch timeout/error: {e}")

        for sym, quote in provider_results.items():
            fmt_sym = _format_symbol(sym)
            normalized = await _align_quote_to_history(fmt_sym, quote)
            if normalized:
                results[fmt_sym] = _adjust_for_market_state(normalized)

        # If provider fetch misses symbols during market-open, keep last known snapshots.
        remaining_symbols = [sym for sym in symbol_list if sym not in results]
        if remaining_symbols:
            for sym in remaining_symbols:
                fallback = (
                    await _get_closed_session_quote(sym)
                    if market_frozen
                    else await _get_frozen_quote_snapshot(sym)
                )
                if fallback:
                    results[sym] = fallback

        return {sym: q for sym, q in results.items() if q}

    request_task = asyncio.create_task(_fetch_batch())
    _batch_requests[batch_key] = _RequestInFlight(request_task, time.time())
    try:
        return await request_task
    finally:
        if batch_key in _batch_requests:
            del _batch_requests[batch_key]


async def get_public_ticker_data() -> list:
    """Get ticker data via Zebu provider sessions."""
    return await get_ticker_data(user_id=None)


def _categorize_commodity(symbol: str) -> str:
    """Categorize commodity by root symbol."""
    symbol_upper = str(symbol or "").upper()
    metals = {"GOLD", "SILVER", "COPPER", "ALUMINIUM", "ZINC", "LEAD", "NICKEL", "TIN"}
    energy = {"CRUDEOIL", "NATURALGAS", "BRENT"}
    agriculture = {
        "COTTON",
        "CASTOR",
        "SOY",
        "GUAR",
        "MUSTARD",
        "CHANA",
        "JEERA",
        "TURMERIC",
        "CARDAMOM",
        "MENTHOIL",
    }

    if any(m in symbol_upper for m in metals):
        return "metals"
    if any(e in symbol_upper for e in energy):
        return "energy"
    if any(a in symbol_upper for a in agriculture):
        return "agriculture"
    return "other"


def _extract_commodity_root(tsym: str) -> str:
    """Extract root from commodity futures tsym (e.g., CRUDEOILM19MAY26FUT -> CRUDEOILM)."""
    raw = str(tsym or "").upper().strip()
    if not raw:
        return ""

    known_bases = sorted(
        MCX_COMMODITY_SYMBOLS | NCDEX_COMMODITY_SYMBOLS,
        key=len,
        reverse=True,
    )
    without_fut = re.sub(r"F(?:UT)?$", "", raw)
    for candidate in (without_fut, raw):
        for base in known_bases:
            if not candidate.startswith(base):
                continue
            remainder = candidate[len(base):]
            if not remainder or remainder[0].isdigit():
                return base

    return re.sub(r"(?:[A-Z]?\d{1,2}[A-Z]{3}\d{2,4})F(?:UT)?$", "", raw).strip()


def _extract_contract_expiry(tsym: str) -> Optional[str]:
    """Parse expiry from tsym into YYYY-MM-DD when available."""
    raw = str(tsym or "").upper().strip()
    match = re.search(r"([A-Z]?)(\d{1,2}[A-Z]{3}\d{2,4})F(?:UT)?$", raw)
    if not match:
        return None
    date_part = match.group(2)
    for fmt in ("%d%b%y", "%d%b%Y"):
        try:
            return datetime.strptime(date_part, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


async def get_all_commodities_live() -> list[dict]:
    """Discover active commodity contracts from master-contract mappings first, then SearchScrip fallback."""
    from services.contract_loader import ensure_commodity_contract_mappings

    await ensure_commodity_contract_mappings(
        [str(item.get("symbol") or "").upper() for item in POPULAR_COMMODITIES]
    )

    provider = await _get_any_provider_live(allow_recover=True)
    discovered_by_symbol: dict[str, dict] = {
        str(item.get("symbol") or "").upper().strip(): item
        for item in _build_commodity_universe()
        if str(item.get("symbol") or "").strip()
    }

    if provider is None:
        logger.warning("No provider available for commodity discovery")
        return list(discovered_by_symbol.values())

    best_by_root: dict[str, dict] = {
        sym: item for sym, item in discovered_by_symbol.items() if item.get("token")
    }

    async def _search_exchange(exchange: str) -> None:
        # Probe only unresolved known symbols for the exchange and bound each probe latency.
        seed_symbols = [
            str(c.get("symbol") or "").upper()
            for c in POPULAR_COMMODITIES
            if str(c.get("exchange") or "").upper() == exchange
            and not discovered_by_symbol.get(
                str(c.get("symbol") or "").upper(), {}
            ).get("token")
        ]
        queries = [q for q in dict.fromkeys(seed_symbols) if q]

        if not queries:
            return

        async def _search_term(term: str):
            try:
                return await asyncio.wait_for(
                    provider._rest_post(
                        "/SearchScrip", {"exch": exchange, "stext": term}
                    ),
                    timeout=2.5,
                )
            except Exception:
                return None

        responses = await asyncio.gather(*[_search_term(term) for term in queries])
        for resp in responses:

            values = resp.get("values") if isinstance(resp, dict) else None
            if not values:
                continue

            for item in values:
                tsym = str(item.get("tsym") or "").upper().strip()
                token = str(item.get("token") or "").strip()
                if not tsym or not token or not re.search(r"F(?:UT)?$", tsym):
                    continue

                root = _extract_commodity_root(tsym)
                if not root:
                    continue

                expiry = _extract_contract_expiry(tsym)
                lot_raw = item.get("ls") or item.get("lotsize") or 1
                tick_raw = item.get("ti") or item.get("tick_size") or 0.05
                try:
                    lot_size = int(float(lot_raw))
                except Exception:
                    lot_size = 1
                try:
                    tick_size = float(tick_raw)
                except Exception:
                    tick_size = 0.05

                candidate = {
                    "symbol": root,
                    "name": root,
                    "exchange": exchange,
                    "category": _categorize_commodity(root),
                    "token": token,
                    "contract_symbol": tsym,
                    "expiry_date": expiry,
                    "lot": lot_size,
                    "tick_size": tick_size,
                    "unit": "per unit",
                }

                existing = best_by_root.get(root)
                if not existing:
                    best_by_root[root] = candidate
                    continue

                old_expiry = existing.get("expiry_date") or "9999-12-31"
                new_expiry = candidate.get("expiry_date") or "9999-12-31"
                from datetime import date as _date

                today_str = _date.today().isoformat()
                old_is_future = old_expiry >= today_str
                new_is_future = new_expiry >= today_str
                if new_is_future and (not old_is_future or new_expiry < old_expiry):
                    best_by_root[root] = candidate

        logger.debug(
            f"Commodity discovery for {exchange}: found {len(best_by_root)} roots so far"
        )   

    await asyncio.gather(_search_exchange("MCX"), _search_exchange("NCDEX"))

    merged_by_symbol: dict[str, dict] = {}
    for sym, base_item in discovered_by_symbol.items():
        live_item = best_by_root.get(sym) or {}
        merged = {
            **base_item,
            **live_item,
            "symbol": sym,
            "name": (live_item.get("name") or base_item.get("name") or sym),
            "exchange": (
                str(live_item.get("exchange") or base_item.get("exchange") or "MCX")
                .upper()
                .strip()
                or "MCX"
            ),
            "category": (
                live_item.get("category")
                or base_item.get("category")
                or _categorize_commodity(sym)
            ),
            "unit": live_item.get("unit") or base_item.get("unit") or "per unit",
            "lot": live_item.get("lot") or base_item.get("lot") or 1,
        }
        merged_by_symbol[sym] = merged

    # Keep any additional discovered roots too (if not in static universe).
    for sym, live_item in best_by_root.items():
        if sym in merged_by_symbol:
            continue
        merged_by_symbol[sym] = {
            **live_item,
            "symbol": sym,
            "name": live_item.get("name") or sym,
            "exchange": (
                str(live_item.get("exchange") or "MCX").upper().strip() or "MCX"
            ),
            "category": live_item.get("category") or _categorize_commodity(sym),
            "unit": live_item.get("unit") or "per unit",
            "lot": live_item.get("lot") or 1,
        }

    discovered = list(merged_by_symbol.values())
    discovered.sort(
        key=lambda item: (item.get("category") or "", item.get("symbol") or "")
    )
    logger.info(f"Commodity discovery complete: {len(discovered)} instruments")
    return discovered


def _build_commodity_row_from_cache(commodity: dict, prior: dict, source: str) -> dict:
    """Build a stable commodity snapshot row from cached payload when live fetch is missing."""
    fallback_price = prior.get("price")
    try:
        fallback_price = float(fallback_price) if fallback_price is not None else 0.0
    except Exception:
        fallback_price = 0.0

    return {
        "symbol": str(commodity.get("symbol") or "").upper(),
        "name": commodity.get("name") or str(commodity.get("symbol") or "").upper(),
        "price": fallback_price,
        "change": float(prior.get("change") or 0),
        "change_percent": float(prior.get("change_percent") or 0),
        "open": float(prior.get("open") or fallback_price),
        "high": float(prior.get("high") or fallback_price),
        "low": float(prior.get("low") or fallback_price),
        "close": float(prior.get("close") or fallback_price),
        "prev_close": float(prior.get("prev_close") or fallback_price),
        "volume": int(prior.get("volume") or 0),
        "bid_price": float(prior.get("bid_price") or 0),
        "ask_price": float(prior.get("ask_price") or 0),
        "bid_qty": int(prior.get("bid_qty") or 0),
        "ask_qty": int(prior.get("ask_qty") or 0),
        "oi": int(prior.get("oi") or 0),
        "market_cap": 0,
        "exchange": str(
            commodity.get("exchange") or prior.get("exchange") or "MCX"
        ).upper(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "last_trade_time": prior.get("last_trade_time"),
        "kind": "commodity",
        "category": commodity.get("category", "other"),
        "unit": commodity.get("unit", "per unit"),
        "lot": commodity.get("lot", 1),
        "token": prior.get("token"),
        "contract_symbol": prior.get("contract_symbol"),
        "expiry_date": prior.get("expiry_date"),
        "source": source,
    }


async def get_commodity_quotes(user_id: Optional[str] = None) -> list:
    """Fetch commodity quotes from live Zebu discovery, with Redis snapshot fallback only."""
    import cache.redis_client as redis_client

    cached_by_symbol: dict[str, dict] = {}
    try:
        cached_items = await redis_client.get_commodities()
        if isinstance(cached_items, list):
            for item in cached_items:
                sym = str(item.get("symbol") or "").upper().strip()
                if sym:
                    cached_by_symbol[sym] = item
    except Exception:
        cached_by_symbol = {}

    # Never surface old demo data if it was cached from a previous fallback path.
    cached_by_symbol = {
        sym: item
        for sym, item in cached_by_symbol.items()
        if str(item.get("source") or "").lower() not in {"demo", "historical"}
    }

    logger.info(
        f"get_commodity_quotes() called | user_id={'yes' if user_id else 'no'} | "
        f"cached_symbols={list(cached_by_symbol.keys())[:5]}"
    )

    provider = None
    try:
        if user_id:
            provider = _get_provider_for_user(str(user_id))
        else:
            provider = await _get_any_provider_live(allow_recover=True)
    except (BrokerNotConnected, RuntimeError):
        provider = await _get_any_provider_live(allow_recover=True)
    except Exception as e:
        logger.debug(f"Commodity provider lookup failed: {e}")
        provider = await _get_any_provider_live(allow_recover=True)

    commodities = await get_all_commodities_live()
    if not commodities:
        commodities = _build_commodity_universe()

    logger.info(
        f"Commodity universe prepared: {len(commodities)} instruments: "
        f"{[c.get('symbol') for c in commodities[:10]]}"
    )

    market_open = False
    try:
        market_open = market_session.get_current_state() == MarketState.OPEN
    except Exception:
        market_open = False

    if provider is None:
        if market_open:
            logger.warning("Commodity live provider unavailable during market hours")
            return []
        if cached_by_symbol:
            logger.warning("Commodity live provider unavailable; returning cached snapshot only")
            return list(cached_by_symbol.values())
        return []

    async def _fetch_one(commodity: dict) -> Optional[dict]:
        sym = str(commodity.get("symbol") or "").upper().strip()
        if not sym:
            return None

        exchange = str(commodity.get("exchange") or "").upper().strip() or "MCX"
        token = str(commodity.get("token") or "").strip()
        contract_symbol = str(
            commodity.get("contract_symbol") or commodity.get("symbol") or sym
        ).upper().strip()

        live_quote = None
        if token:
            try:
                raw_quote = await asyncio.wait_for(
                    provider._rest_post("/GetQuotes", {"exch": exchange, "token": token}),
                    timeout=3.0,
                )
                if isinstance(raw_quote, dict) and raw_quote.get("stat") == "Ok":
                    live_quote = _normalize_quote(raw_quote)
            except Exception as e:
                logger.debug(f"Commodity GetQuotes failed for {contract_symbol}: {e}")

        if not live_quote and contract_symbol:
            try:
                live_quote = await asyncio.wait_for(
                    provider.get_quote(contract_symbol),
                    timeout=2.5,
                )
                live_quote = _normalize_quote(live_quote) if live_quote else None
            except Exception as e:
                logger.debug(f"Commodity live quote failed for {contract_symbol}: {e}")
                live_quote = None

        # Zebu-only snapshot fallback (Redis/last frozen quote path), never demo/NSE.
        if not live_quote:
            try:
                symbol_for_snapshot = contract_symbol or sym
                snap_quote = await get_system_quote_live_only(
                    symbol_for_snapshot,
                    allow_recover=True,
                )
                live_quote = _normalize_quote(snap_quote) if snap_quote else None
            except Exception as e:
                logger.debug(
                    f"Commodity snapshot quote failed for {contract_symbol or sym}: {e}"
                )
                live_quote = None

        if isinstance(live_quote, dict) and live_quote.get("price") is not None:
            live_quote["symbol"] = sym
            live_quote["name"] = commodity.get("name") or sym
            live_quote["exchange"] = exchange
            live_quote["category"] = commodity.get("category", "other")
            live_quote["token"] = token or live_quote.get("token")
            live_quote["contract_symbol"] = contract_symbol
            live_quote["expiry_date"] = commodity.get("expiry_date")
            live_quote["lot"] = commodity.get("lot", 1)
            live_quote["tick_size"] = commodity.get("tick_size", 0.05)
            live_quote["unit"] = commodity.get("unit", "per unit")
            live_quote["kind"] = "commodity"
            live_quote["source"] = str(live_quote.get("source") or "live_zebu")
            if not market_open:
                enriched = await _enrich_frozen_quote_day_change(
                    contract_symbol or sym, live_quote
                )
                return enriched or live_quote
            return live_quote

        prior = cached_by_symbol.get(sym)
        if prior and not market_open:
            enriched_prior = await _enrich_frozen_quote_day_change(
                contract_symbol or sym, prior
            )
            return _build_commodity_row_from_cache(
                commodity,
                enriched_prior or prior,
                str((enriched_prior or prior).get("source") or "cache"),
            )

        return None

    async def _assemble_quotes(commodity_list: list[dict]) -> list[dict]:
        results = await asyncio.gather(
            *[_fetch_one(c) for c in commodity_list],
            return_exceptions=True,
        )
        return [item for item in results if isinstance(item, dict)]

    successful = await _assemble_quotes(commodities)

    if (
        market_open
        and commodities
        and len(successful) < max(1, int(len(commodities) * 0.5))
    ):
        from services.contract_loader import ensure_commodity_contract_mappings

        logger.warning(
            "Commodity quotes sparse (%d/%d) — refreshing MCX/NCDEX master mappings",
            len(successful),
            len(commodities),
        )
        await ensure_commodity_contract_mappings(
            [str(c.get("symbol") or "").upper() for c in commodities],
            force_refresh=True,
        )
        commodities = await get_all_commodities_live()
        if not commodities:
            commodities = _build_commodity_universe()
        successful = await _assemble_quotes(commodities)

    if successful:
        try:
            await redis_client.set_commodities(successful)
        except Exception as e:
            logger.debug(f"Redis set_commodities failed: {e}")

        if market_open and len(successful) < len(commodities):
            logger.warning(
                "Commodity live assembly partial during market hours: %d/%d",
                len(successful),
                len(commodities),
            )
        logger.info(f"Commodity quotes assembled: {len(successful)} instruments")
        return successful

    # FINAL FALLBACK: Return cached Redis data
    if cached_by_symbol:
        logger.warning("Returning cached commodity data (Zebu live unavailable)")
        return list(cached_by_symbol.values())

    return []


async def search_commodities(query: str) -> list:
    """Search commodities by name, symbol, or category without requiring broker auth."""
    query_upper = query.upper().strip()
    if not query_upper:
        return []

    universe: dict[str, dict] = {}
    for item in POPULAR_COMMODITIES:
        sym = str(item.get("symbol") or "").upper().strip()
        if not sym:
            continue
        universe[sym] = {
            "symbol": sym,
            "name": item.get("name") or sym,
            "exchange": item.get("exchange") or "MCX",
            "category": item.get("category") or _categorize_commodity(sym),
            "unit": item.get("unit") or "per unit",
            "lot": item.get("lot") or 1,
        }

    # Optional enrichment from live broker discovery when available.
    try:
        live_commodities = await get_all_commodities_live()
        for commodity in live_commodities:
            sym = str(commodity.get("symbol") or "").upper().strip()
            if not sym:
                continue
            base = universe.get(
                sym,
                {
                    "symbol": sym,
                    "name": sym,
                    "exchange": commodity.get("exchange") or "MCX",
                    "category": commodity.get("category") or _categorize_commodity(sym),
                    "unit": commodity.get("unit") or "per unit",
                    "lot": commodity.get("lot") or 1,
                },
            )
            universe[sym] = {
                **base,
                **commodity,
                "symbol": sym,
                "name": commodity.get("name") or base.get("name") or sym,
                "category": commodity.get("category")
                or base.get("category")
                or "other",
            }
    except Exception as e:
        logger.debug(f"Live commodity discovery skipped in search: {e}")

    matches = []
    for commodity in universe.values():
        symbol_upper = str(commodity.get("symbol") or "").upper()
        name_upper = str(commodity.get("name") or "").upper()
        category_upper = str(commodity.get("category") or "").upper()
        if (
            query_upper in symbol_upper
            or query_upper in name_upper
            or query_upper in category_upper
        ):
            matches.append(commodity)

    return sorted(matches, key=lambda item: str(item.get("symbol") or ""))


async def get_52w_high_low(symbol: str) -> tuple[Optional[float], Optional[float]]:
    """Calculate 52-week high and low from historical 1y daily candles."""
    redis = None
    cache_key = f"alphasync:indices:52w:{symbol}"
    try:
        from cache.redis_client import get_redis
        redis = await get_redis()
        cached = await redis.get(cache_key)
        if cached:
            import json
            data = json.loads(cached)
            return data.get("high"), data.get("low")
    except Exception:
        pass

    try:
        candles = await get_historical_data(symbol, period="1y", interval="1d")
        if candles:
            highs = [float(c["high"]) for c in candles if c.get("high") is not None]
            lows = [float(c["low"]) for c in candles if c.get("low") is not None]
            if highs and lows:
                h_52 = round(max(highs), 2)
                l_52 = round(min(lows), 2)
                if redis:
                    try:
                        import json
                        await redis.setex(cache_key, 86400, json.dumps({"high": h_52, "low": l_52}))
                    except Exception:
                        pass
                return h_52, l_52
    except Exception as e:
        logger.debug(f"Failed to calculate 52w high/low for {symbol}: {e}")

    return None, None


async def get_sparkline_prices(symbol: str) -> list[float]:
    """Fetch close prices for sparklines. Tries intraday first, falls back to daily candles."""
    redis = None
    cache_key = f"alphasync:indices:sparkline:{symbol}"
    try:
        from cache.redis_client import get_redis
        redis = await get_redis()
        cached = await redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)
    except Exception:
        pass

    candles = None
    # Progressively broaden the window until we get usable data
    for period, interval in [("1d", "5m"), ("1d", "15m"), ("5d", "30m"), ("1mo", "1d")]:
        try:
            candles = await get_historical_data(symbol, period=period, interval=interval)
        except Exception:
            candles = None
        if candles and len(candles) >= 2:
            break

    if candles:
        try:
            prices = [round(float(c["close"]), 2) for c in candles if c.get("close") is not None]
            if len(prices) >= 2:
                if redis:
                    try:
                        import json
                        await redis.setex(cache_key, 300, json.dumps(prices))
                    except Exception:
                        pass
                return prices
        except Exception as e:
            logger.debug(f"Failed to process sparkline candles for {symbol}: {e}")
    return []


_OVERVIEW_CACHE_KEY = "alphasync:market:overview"
_OVERVIEW_CACHE_TTL = 25  # seconds — aligns with the 20s frontend poll


async def get_market_overview_data(user_id: Optional[str] = None) -> dict:
    """Consolidated market overview payload for the premium dashboard."""
    import asyncio
    import json as _json

    # Serve from cache when available to avoid recomputing every request
    _redis = None
    try:
        from cache.redis_client import get_redis
        _redis = await get_redis()
        _cached_raw = await _redis.get(_OVERVIEW_CACHE_KEY)
        if _cached_raw:
            return _json.loads(_cached_raw)
    except Exception:
        _redis = None

    target_indices = [
        {"symbol": "^NSEI", "name": "NIFTY 50"},
        {"symbol": "^BSESN", "name": "SENSEX"},
        {"symbol": "^NSEBANK", "name": "BANK NIFTY"},
        {"symbol": "^CNXFIN", "name": "FINNIFTY"},
        {"symbol": "^CNXIT", "name": "NIFTY IT"},
    ]

    async def _fetch_index(idx_info):
        try:
            if user_id:
                quote = await asyncio.wait_for(get_quote_safe(idx_info["symbol"], user_id), timeout=4.0)
            else:
                quote = await asyncio.wait_for(get_system_quote_safe(idx_info["symbol"]), timeout=4.0)

            if quote:
                quote = _normalize_quote(quote)

            if quote:
                quote["name"] = idx_info["name"]

                async def _task_52w():
                    try:
                        return await asyncio.wait_for(get_52w_high_low(idx_info["symbol"]), timeout=4.0)
                    except Exception:
                        return None, None

                async def _task_spark():
                    try:
                        return await asyncio.wait_for(get_sparkline_prices(idx_info["symbol"]), timeout=5.0)
                    except Exception:
                        return []

                (h_52, l_52), sparkline = await asyncio.gather(_task_52w(), _task_spark())

                quote["high_52w"] = h_52 or quote.get("high") or quote.get("price")
                quote["low_52w"] = l_52 or quote.get("low") or quote.get("price")
                quote["sparkline"] = sparkline
                if quote.get("high") is None or quote.get("high") == 0:
                    quote["high"] = quote.get("price")
                if quote.get("low") is None or quote.get("low") == 0:
                    quote["low"] = quote.get("price")
                return quote
        except Exception as e:
            logger.debug(f"Failed fetching index overview for {idx_info['symbol']}: {e}")
        return {
            "symbol": idx_info["symbol"],
            "name": idx_info["name"],
            "price": None,
            "change": None,
            "change_percent": None,
            "high": None,
            "low": None,
            "high_52w": None,
            "low_52w": None,
            "sparkline": []
        }

    indices_quotes = await asyncio.gather(
        *[_fetch_index(idx) for idx in target_indices],
        return_exceptions=True
    )
    indices_list = [r for r in indices_quotes if isinstance(r, dict)]

    popular_symbols = [s["symbol"] for s in POPULAR_INDIAN_STOCKS]
    try:
        stock_quotes_dict = await asyncio.wait_for(
            get_batch_quotes(popular_symbols, user_id=user_id),
            timeout=6.0,
        )
    except asyncio.TimeoutError:
        logger.warning("get_batch_quotes timed out after 6s, using empty dict")
        stock_quotes_dict = {}

    stock_quotes = []
    for sym, q in stock_quotes_dict.items():
        nq = _normalize_quote(q)
        if nq:
            stock_quotes.append(nq)

    gainers = [s for s in stock_quotes if s.get("change_percent") is not None and s["change_percent"] > 0]
    gainers.sort(key=lambda x: x["change_percent"], reverse=True)
    top_gainers = gainers[:5]

    losers = [s for s in stock_quotes if s.get("change_percent") is not None and s["change_percent"] < 0]
    losers.sort(key=lambda x: x["change_percent"])
    top_losers = losers[:5]

    sector_mappings = [
        {"symbol": "^CNXIT", "name": "NIFTY IT"},
        {"symbol": "^NSEBANK", "name": "NIFTY BANK"},
        {"symbol": "^CNXFIN", "name": "NIFTY FIN SERVICE"},
        {"symbol": "^CNXFMCG", "name": "NIFTY FMCG"},
        {"symbol": "^CNXMETAL", "name": "NIFTY METAL"},
    ]

    sectors_list = []
    for sec in sector_mappings:
        found = next((idx for idx in indices_list if idx["symbol"] == sec["symbol"]), None)
        if not found:
            try:
                if user_id:
                    q = await asyncio.wait_for(get_quote_safe(sec["symbol"], user_id), timeout=2.0)
                else:
                    q = await asyncio.wait_for(get_system_quote_safe(sec["symbol"]), timeout=2.0)
                if q:
                    found = _normalize_quote(q)
            except Exception:
                pass
        if found:
            sectors_list.append({
                "symbol": sec["symbol"],
                "name": sec["name"],
                "price": found.get("price"),
                "change": found.get("change"),
                "change_percent": found.get("change_percent")
            })
        else:
            sectors_list.append({
                "symbol": sec["symbol"],
                "name": sec["name"],
                "price": None,
                "change": None,
                "change_percent": None
            })

    try:
        nifty50_breadth = await asyncio.wait_for(get_index_advances_declines("^NSEI"), timeout=4.0)
    except asyncio.TimeoutError:
        logger.warning("get_index_advances_declines timed out, using defaults")
        nifty50_breadth = {}
    adv = nifty50_breadth.get("advances", 0)
    dec = nifty50_breadth.get("declines", 0)
    unc = nifty50_breadth.get("unchanged", 0)
    total_nifty = adv + dec + unc

    total_mock = 2854
    if total_nifty > 0:
        adv_ratio = adv / total_nifty
        dec_ratio = dec / total_nifty
    else:
        adv_ratio = 0.58
        dec_ratio = 0.38

    adv_projected = int(total_mock * adv_ratio)
    dec_projected = int(total_mock * dec_ratio)
    unc_projected = total_mock - adv_projected - dec_projected

    adv_projected = max(0, adv_projected)
    dec_projected = max(0, dec_projected)
    unc_projected = max(0, unc_projected)

    sentiment_score = int(adv_ratio * 100)
    if sentiment_score >= 70:
        sentiment_label = "Extreme Bullish"
        sentiment_desc = "Strong buying momentum across the sectors."
    elif sentiment_score >= 55:
        sentiment_label = "Bullish"
        sentiment_desc = "Positive sentiment with steady buying interest."
    elif sentiment_score >= 45:
        sentiment_label = "Neutral"
        sentiment_desc = "Balanced market forces with no clear direction."
    elif sentiment_score >= 30:
        sentiment_label = "Bearish"
        sentiment_desc = "Selling pressure dominates the trading session."
    else:
        sentiment_label = "Extreme Bearish"
        sentiment_desc = "Heavy panic selling observed across indices."

    _result = {
        "indices": indices_list,
        "gainers": top_gainers,
        "losers": top_losers,
        "sectors": sectors_list,
        "breadth": {
            "advances": adv_projected,
            "declines": dec_projected,
            "unchanged": unc_projected,
            "total": total_mock
        },
        "sentiment": {
            "score": sentiment_score,
            "label": sentiment_label,
            "description": sentiment_desc
        }
    }

    # Cache the computed result so subsequent requests within the TTL window are instant
    if _redis is not None:
        try:
            await _redis.setex(_OVERVIEW_CACHE_KEY, _OVERVIEW_CACHE_TTL, _json.dumps(_result))
        except Exception:
            pass

    return _result
