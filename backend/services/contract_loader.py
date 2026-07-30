"""
Contract Loader — fetches NSE/BSE/MCX/NCDEX symbol lists from the internal simulation engine
data feed (GET /v1/symbols/{exchange}) so the contract_symbol_map registry
has full coverage beyond the handful of hardcoded indices.

Unlike the legacy Zebu integration this replaces, the internal simulation engine addresses every
instrument by plain symbol string, not an opaque numeric token — so the
"token" field returned here is just the symbol itself, kept only so
existing "does this contract have a token" truthiness checks elsewhere
keep working unchanged.

Called at startup in main.py so contract_symbol_map has full coverage.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Known commodity base symbols — the nearest active FUT contract for each
# is what we care about at startup (matches the previous Zebu behavior of
# pre-registering one near-expiry commodity future per base symbol).
_MCX_COMMODITY_BASE = {
    "GOLD", "GOLDM", "GOLDGUINEA", "GOLDPETAL",
    "SILVER", "SILVERM", "SILVERMIC",
    "COPPER", "COPPERM",
    "ALUMINIUM", "ALUMINI",
    "ZINC", "ZINCMINI",
    "LEAD", "LEADMINI",
    "NICKEL",
    "CRUDEOIL", "CRUDEOILM",
    "NATURALGAS", "NATGASMINI",
    "COTTONCNDY", "KAPAS", "MENTHOIL",
}
_NCDEX_COMMODITY_BASE = {
    "COTTON", "CASTORSEED", "SOYBEAN", "GUARSEED", "RMSEED", "CHANA",
}


async def fetch_exchange_symbols(exchange: str, segment: str = "EQ") -> list[dict]:
    """
    Fetch the internal simulation engine symbol list directly from the local database layer.
    """
    from database.connection import async_session
    from data_layer.core.delay_gate import get_eligible_symbols

    try:
        async with async_session() as db:
            symbols = await get_eligible_symbols(db, exchange, segment=segment)
    except Exception as e:
        logger.warning(f"Local symbol fetch failed for {exchange} {segment}: {e}")
        return []

    contracts = [
        {
            "symbol": str(sym).strip().upper(),
            "trading_symbol": str(sym).strip().upper(),
            "exchange": exchange.upper(),
            "segment": segment.upper(),
        }
        for sym in symbols
        if str(sym or "").strip()
    ]
    logger.info(f"Fetched {len(contracts)} {exchange} {segment} symbols locally from database")
    return contracts


async def fetch_commodity_contracts() -> list[dict]:
    """
    Fetch MCX and NCDEX commodity symbols known to the internal simulation engine, filtered down
    to our known base-symbol list (matches contract_symbol_map's commodity
    classification sets).

    Returns a list of dicts compatible with register_exchange_symbols().
    """
    results: list[dict] = []

    for exchange_name, known_base_symbols in (
        ("MCX", _MCX_COMMODITY_BASE),
        ("NCDEX", _NCDEX_COMMODITY_BASE),
    ):
        contracts = await fetch_exchange_symbols(exchange_name, segment="FUT")
        if not contracts:
            logger.warning(
                f"the internal simulation engine returned no {exchange_name} symbols — "
                f"commodity quotes will fall back to the local simulator"
            )
            continue

        matched = [
            c for c in contracts
            if c["symbol"] in known_base_symbols
        ]
        results.extend(matched)
        logger.info(f"Matched {len(matched)} known {exchange_name} commodity symbols")

    return results


# In-memory cache of fetched NSE symbols (per-process, not Redis).
_NSE_CONTRACTS_CACHE: Optional[list[dict]] = None
_COMMODITY_CONTRACTS_CACHE: Optional[list[dict]] = None


async def get_commodity_contracts_cached(force_refresh: bool = False) -> list[dict]:
    """Return MCX/NCDEX commodity symbols, fetching from the internal simulation engine once per process."""
    global _COMMODITY_CONTRACTS_CACHE
    if _COMMODITY_CONTRACTS_CACHE is None or force_refresh:
        _COMMODITY_CONTRACTS_CACHE = await fetch_commodity_contracts()
    return list(_COMMODITY_CONTRACTS_CACHE or [])


async def ensure_commodity_contract_mappings(
    symbols: Optional[list[str]] = None,
    *,
    force_refresh: bool = False,
) -> int:
    """
    Register the internal simulation engine symbol mappings for commodities missing from the
    in-memory registry. Uses the same the internal simulation engine symbol source as startup.
    """
    from providers.contract_symbol_map import (
        MCX_COMMODITY_SYMBOLS,
        NCDEX_COMMODITY_SYMBOLS,
        canonical_to_exchange_symbol,
        register_exchange_symbols,
    )

    if symbols:
        check_symbols = [str(sym or "").strip().upper() for sym in symbols if str(sym or "").strip()]
    else:
        check_symbols = sorted(MCX_COMMODITY_SYMBOLS | NCDEX_COMMODITY_SYMBOLS)

    missing = [sym for sym in check_symbols if sym and not canonical_to_exchange_symbol(sym)]
    if not missing:
        return 0

    contracts = await get_commodity_contracts_cached(force_refresh=force_refresh)
    if not contracts:
        logger.warning(
            "ensure_commodity_contract_mappings: the internal simulation engine commodity symbols unavailable for %s",
            sorted(missing),
        )
        return 0

    missing_set = set(missing)
    to_register = [c for c in contracts if c.get("symbol") in missing_set]
    if not to_register:
        logger.warning(
            "ensure_commodity_contract_mappings: no the internal simulation engine rows for %s",
            sorted(missing),
        )
        return 0

    loaded = register_exchange_symbols(to_register)
    if loaded:
        logger.info(
            "Registered %d the internal simulation engine commodity mappings for: %s",
            loaded,
            sorted(missing_set),
        )
    return loaded


async def get_nse_contracts_cached(force_refresh: bool = False) -> list[dict]:
    """Return NSE equity symbols, fetching from the internal simulation engine once per process."""
    global _NSE_CONTRACTS_CACHE
    if _NSE_CONTRACTS_CACHE is None or force_refresh:
        _NSE_CONTRACTS_CACHE = await fetch_exchange_symbols("NSE", segment="EQ")
    return list(_NSE_CONTRACTS_CACHE or [])


async def ensure_nse_equity_mappings(canonical_symbols: list[str]) -> int:
    """
    Register the internal simulation engine symbol mappings for equities missing from the
    in-memory registry. Uses the same the internal simulation engine symbol source as startup.
    Does not touch Redis hot/frozen state.
    """
    from providers.contract_symbol_map import canonical_to_exchange_symbol, register_exchange_symbols

    missing_bases: set[str] = set()
    for sym in canonical_symbols or []:
        if canonical_to_exchange_symbol(sym):
            continue
        raw = str(sym or "").strip().upper()
        if not raw or raw.startswith("^"):
            continue
        base = raw.replace(".NS", "").replace(".BO", "")
        if base:
            missing_bases.add(base)

    if not missing_bases:
        return 0

    contracts = await get_nse_contracts_cached()
    if not contracts:
        logger.warning(
            "ensure_nse_equity_mappings: the internal simulation engine NSE symbols unavailable for %s",
            sorted(missing_bases),
        )
        return 0

    to_register = [c for c in contracts if c.get("symbol") in missing_bases]
    if not to_register:
        logger.warning(
            "ensure_nse_equity_mappings: no the internal simulation engine NSE rows for %s",
            sorted(missing_bases),
        )
        return 0

    loaded = register_exchange_symbols(to_register)
    if loaded:
        logger.info(
            "Registered %d the internal simulation engine mappings from NSE symbols for: %s",
            loaded,
            sorted(missing_bases),
        )
    return loaded
