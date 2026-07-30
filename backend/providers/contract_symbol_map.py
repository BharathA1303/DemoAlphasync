"""
Contract Symbol Map — Translates between AlphaSync canonical symbols and
the internal simulation engine data feed's "EXCHANGE:SEGMENT:SYMBOL" instrument format.

AlphaSync uses canonical symbol notation:
    NSE equities:   RELIANCE.NS, TCS.NS, HDFCBANK.NS
    BSE equities:   RELIANCE.BO
    Indices:        ^NSEI, ^BSESN
    Commodities:    GOLD, SILVER, CRUDEOIL, COTTON, SOYBEAN (no suffix)

the internal simulation engine addresses every instrument as "EXCHANGE:SEGMENT:SYMBOL", e.g.:
    NSE:EQ:RELIANCE     (cash equity)
    NSE:FUT:RELIANCE    (futures contract)
    NSE:OPT:RELIANCE    (options — expiry/strike/option_type via query params)
    MCX:FUT:GOLD        (commodity future)

Unlike the legacy Zebu integration this replaces, the internal simulation engine never uses
opaque numeric tokens — every instrument is addressed by its plain symbol
string, so this module is a straightforward canonical <-> the internal simulation engine-symbol
formatter plus a registry of known symbols (populated at startup from
GET /v1/symbols/{exchange} for search/validation), not a token cache.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Known commodity symbols ────────────────────────────────────────
# Used to detect commodity symbols and avoid appending .NS to them.
MCX_COMMODITY_SYMBOLS = {
    "GOLD",
    "GOLDM",
    "GOLDGUINEA",
    "GOLDPETAL",
    "SILVER",
    "SILVERM",
    "SILVERMIC",
    "COPPER",
    "COPPERM",
    "CRUDEOIL",
    "CRUDEOILM",
    "NATURALGAS",
    "NATGASMINI",
    "ALUMINIUM",
    "ALUMINI",
    "ZINC",
    "ZINCMINI",
    "LEAD",
    "LEADMINI",
    "NICKEL",
    "MENTHOIL",
    "COTTONCNDY",
    "KAPAS",
}

NCDEX_COMMODITY_SYMBOLS = {
    "COTTON",
    "CASTORSEED",
    "SOYBEAN",
    "GUARSEED",
    "RMSEED",
    "CHANA",
}


def is_mcx_symbol(symbol: str) -> bool:
    """Check if a symbol is a known MCX commodity."""
    clean = symbol.upper().strip()
    return clean in MCX_COMMODITY_SYMBOLS


def is_ncdex_symbol(symbol: str) -> bool:
    """Check if a symbol is a known NCDEX commodity."""
    clean = symbol.upper().strip()
    return clean in NCDEX_COMMODITY_SYMBOLS


def is_commodity_symbol(symbol: str) -> bool:
    """Check if a symbol is any supported commodity symbol."""
    clean = symbol.upper().strip()
    return clean in MCX_COMMODITY_SYMBOLS or clean in NCDEX_COMMODITY_SYMBOLS


# ── the internal simulation engine symbol registry ──────────────────────────────────────
# Populated at startup from GET /v1/symbols/{exchange} (all NSE/BSE equities,
# plus known MCX/NCDEX commodities and NSE F&O contracts). Registry entries
# map canonical symbol -> {"exchange": str, "segment": str, "symbol": str}.

_SYMBOL_REGISTRY: dict[str, dict] = {
    # ── NSE Indices (well-known index symbols) ───────────────────────
    "^NSEI": {"symbol": "NIFTY", "exchange": "NSE", "segment": "EQ"},
    "^NSEBANK": {"symbol": "BANKNIFTY", "exchange": "NSE", "segment": "EQ"},
    "^CNXIT": {"symbol": "NIFTYIT", "exchange": "NSE", "segment": "EQ"},
    "^BSESN": {"symbol": "SENSEX", "exchange": "BSE", "segment": "EQ"},
    "^CNXFIN": {"symbol": "FINNIFTY", "exchange": "NSE", "segment": "EQ"},
}

# Reverse map: the internal simulation engine "EXCHANGE:SEGMENT:SYMBOL" -> canonical_symbol
_TA_SYMBOL_TO_CANONICAL: dict[str, str] = {}

for _canonical, _mapping in _SYMBOL_REGISTRY.items():
    _key = f"{_mapping['exchange']}:{_mapping['segment']}:{_mapping['symbol']}"
    _TA_SYMBOL_TO_CANONICAL[_key] = _canonical

# NSE/BSE base symbol (no suffix) -> canonical (e.g. TATAMOTORS -> TATAMOTORS.NS)
_BASE_TO_CANONICAL: dict[str, str] = {}

# NSE ticker renames — watchlists/UI may use legacy names; the exchange's
# current master uses the new symbol. Maps legacy canonical -> live canonical
# (same instrument, same underlying contract).
_CANONICAL_EQUITY_ALIASES: dict[str, str] = {
    "TATAMOTORS.NS": "TMPV.NS",
}

# legacy watchlist ticker -> current NSE symbol
_LEGACY_NSE_TICKER_ALIASES: dict[str, str] = {
    "TATAMOTORS": "TMPV",
}


def _normalize_equity_canonical(symbol: str) -> str:
    """Normalize to canonical form used in _SYMBOL_REGISTRY keys."""
    clean = str(symbol or "").strip().upper()
    if not clean:
        return clean
    if clean.startswith("^") or clean.endswith((".NS", ".BO")):
        return clean
    if is_commodity_symbol(clean):
        return clean
    return f"{clean}.NS"


def canonical_to_exchange_symbol(symbol: str) -> Optional[dict]:
    """
    Convert an AlphaSync canonical symbol to the internal simulation engine's addressing format.

    Returns:
        {"symbol": "RELIANCE", "exchange": "NSE", "segment": "EQ"}
        or None if not yet registered (call register_exchange_symbols to
        populate on-demand from GET /v1/symbols/{exchange}).
    """
    canonical = _normalize_equity_canonical(symbol)
    if not canonical:
        return None

    hit = _SYMBOL_REGISTRY.get(canonical)
    if hit:
        return hit

    alias_target = _CANONICAL_EQUITY_ALIASES.get(canonical)
    if alias_target:
        alias_hit = _SYMBOL_REGISTRY.get(alias_target)
        if alias_hit:
            return alias_hit

    base = canonical.replace(".NS", "").replace(".BO", "")
    alt = _BASE_TO_CANONICAL.get(base)
    if alt:
        return _SYMBOL_REGISTRY.get(alt)

    return None


def register_exchange_symbols(contracts: list[dict]) -> int:
    """
    Register / refresh known the internal simulation engine symbols.

    Expected format per entry (matches the internal simulation engine's GET /v1/symbols/{exchange}
    shape once paired with an exchange/segment, or the richer per-contract
    dicts returned by futures/options contract loaders):
        {"symbol": "RELIANCE", "exchange": "NSE", "segment": "EQ"}
        {"symbol": "GOLD",     "exchange": "MCX", "segment": "FUT"}
        {"symbol": "RELIANCE", "exchange": "NSE", "segment": "FUT", "expiry": "2026-06-25"}

    Call this at startup after fetching symbol lists from the internal simulation engine
    (GET /v1/symbols/{exchange}?segment=...). Returns the number of symbols
    registered.
    """
    global _BASE_TO_CANONICAL
    count = 0

    for c in contracts:
        sym = str(c.get("symbol", "")).strip().upper()
        exchange = str(c.get("exchange", "NSE")).strip().upper()
        segment = str(c.get("segment", "EQ")).strip().upper()
        explicit_canonical = str(c.get("canonical", "")).strip().upper()

        if not sym:
            continue

        if explicit_canonical:
            canonical = explicit_canonical
        elif segment in {"FUT", "OPT"}:
            # Derivatives: canonical is the underlying's contract symbol.
            canonical = sym
        elif exchange in {"MCX", "NCDEX"}:
            # Commodities: canonical is just the symbol (e.g. "GOLD", "COTTON")
            canonical = sym
        elif exchange == "NSE":
            canonical = f"{sym}.NS"
        else:
            canonical = f"{sym}.BO"

        _SYMBOL_REGISTRY[canonical] = {
            "symbol": sym,
            "exchange": exchange,
            "segment": segment,
        }
        _TA_SYMBOL_TO_CANONICAL[f"{exchange}:{segment}:{sym}"] = canonical
        _BASE_TO_CANONICAL[sym] = canonical

        # Register legacy NSE tickers that map to this row (e.g. TMPV -> TATAMOTORS).
        if exchange == "NSE" and segment == "EQ":
            for legacy_base, live_base in _LEGACY_NSE_TICKER_ALIASES.items():
                if sym == live_base:
                    legacy_canonical = f"{legacy_base}.NS"
                    _SYMBOL_REGISTRY[legacy_canonical] = {
                        "symbol": sym,
                        "exchange": exchange,
                        "segment": segment,
                    }
                    _BASE_TO_CANONICAL[legacy_base] = legacy_canonical

        count += 1

    logger.info(
        f"Registered {count} the internal simulation engine symbol mappings (total: {len(_SYMBOL_REGISTRY)})"
    )
    return count


def has_exchange_symbol(symbol: str) -> bool:
    """Return True when symbol resolves to a registered the internal simulation engine instrument."""
    return canonical_to_exchange_symbol(symbol) is not None


def search_registered_symbols(query: str, *, segment: str = "EQ", limit: int = 15) -> list[dict]:
    """Substring-search the in-memory the internal simulation engine symbol registry (populated at
    startup from GET /v1/symbols/{exchange}). Returns canonical entries:
    {"canonical": str, "symbol": str, "exchange": str, "segment": str}.
    """
    q = str(query or "").strip().upper()
    if not q:
        return []

    results = []
    for canonical, mapping in _SYMBOL_REGISTRY.items():
        if mapping.get("segment") != segment:
            continue
        sym = str(mapping.get("symbol", "")).upper()
        if q in sym or q in canonical.upper():
            results.append({"canonical": canonical, **mapping})
        if len(results) >= limit:
            break
    return results


def dump_commodity_symbol_map() -> dict:
    """Return all MCX/NCDEX registry entries for diagnostics."""
    commodity_forward = {
        k: v for k, v in _SYMBOL_REGISTRY.items()
        if v.get("exchange") in ("MCX", "NCDEX")
    }
    logger.info(
        f"[MCX/NCDEX SYMBOL DUMP] ({len(commodity_forward)} entries): "
        f"{dict(list(commodity_forward.items())[:15])}"
    )
    return {"forward_map": commodity_forward}


def redis_price_lookup_symbols(symbol: str) -> list[str]:
    """
    Redis read order for a UI symbol.

    Legacy tickers (e.g. TATAMOTORS.NS) are checked AFTER the live canonical
    (TMPV.NS) so stale pre-rename frozen keys are not returned first.
    """
    canonical = _normalize_equity_canonical(symbol)
    if not canonical:
        return []

    ordered: list[str] = []
    live = _CANONICAL_EQUITY_ALIASES.get(canonical)
    if live:
        ordered.append(live)
        ordered.append(canonical)
    else:
        ordered.append(canonical)
        for legacy, live_base in _LEGACY_NSE_TICKER_ALIASES.items():
            if canonical == f"{legacy}.NS":
                ordered.append(f"{live_base}.NS")

    base = canonical.replace(".NS", "").replace(".BO", "")
    if base:
        ordered.append(base)

    deduped: list[str] = []
    for item in ordered:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def mirror_canonicals_for_quote(canonical: str) -> list[str]:
    """All canonical Redis keys that must receive the same live quote."""
    canonical = _normalize_equity_canonical(canonical)
    keys = [canonical]
    for legacy_base, live_base in _LEGACY_NSE_TICKER_ALIASES.items():
        legacy_c = f"{legacy_base}.NS"
        live_c = f"{live_base}.NS"
        if canonical == live_c:
            keys.append(legacy_c)
        elif canonical == legacy_c:
            keys.append(live_c)
    return list(dict.fromkeys(keys))
