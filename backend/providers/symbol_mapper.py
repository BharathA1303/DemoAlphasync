"""
Symbol Mapper — Translates between AlphaSync canonical symbols and
provider-specific symbol formats.

AlphaSync uses canonical symbol notation:
    NSE equities:   RELIANCE.NS, TCS.NS, HDFCBANK.NS
    Indices:        ^NSEI, ^BSESN
    Commodities:    GOLD, SILVER, CRUDEOIL, COTTON, SOYBEAN (no suffix)

Each provider may use different formats:
    - Zebu NSE: RELIANCE-EQ  (exchange token-based, NSE segment)
    - Zebu MCX: GOLD, GOLDM, CRUDEOIL  (exchange token-based, MCX segment)
    - Zebu NCDEX: COTTON, SOYBEAN, CHANA (exchange token-based, NCDEX segment)

The map starts empty and is populated at startup by fetch_zebu_contracts()
which downloads the full master contract file directly from Zebu's API.
Any symbol not yet in the map is resolved on-demand via SearchScrip.
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


# ── Zebu symbol mapping ────────────────────────────────────────────
# Populated at startup from Zebu master contracts (all ~1800 NSE equities).
# Also populated on-demand via _resolve_symbol() → SearchScrip API.
# Format: canonical_symbol -> { "trading_symbol": str, "token": str, "exchange": str }

_ZEBU_SYMBOL_MAP: dict[str, dict] = {
    # ── NSE Indices (Zebu well-known index tokens) ───────────────────
    "^NSEI": {"trading_symbol": "Nifty 50", "token": "26000", "exchange": "NSE"},
    "^NSEBANK": {"trading_symbol": "Nifty Bank", "token": "26009", "exchange": "NSE"},
    "^CNXIT": {"trading_symbol": "Nifty IT", "token": "26008", "exchange": "NSE"},
    "^BSESN": {"trading_symbol": "SENSEX", "token": "1", "exchange": "BSE"},
    "^CNXFIN": {"trading_symbol": "Nifty Fin Services", "token": "26037", "exchange": "NSE"},
}

# Reverse map for incoming ticks:
#   token -> canonical_symbol (only when token is globally unique)
#   EXCHANGE|token -> canonical_symbol (preferred)
_TOKEN_TO_CANONICAL: dict[str, str] = {}
_AMBIGUOUS_TOKENS: set[str] = set()

for _canonical, _mapping in _ZEBU_SYMBOL_MAP.items():
    _token = str(_mapping.get("token", "")).strip()
    _exchange = str(_mapping.get("exchange", "")).strip().upper()
    if not _token:
        continue
    _TOKEN_TO_CANONICAL[_token] = _canonical
    if _exchange:
        _TOKEN_TO_CANONICAL[f"{_exchange}|{_token}"] = _canonical

# Reverse map: trading_symbol -> canonical_symbol
_TRADING_TO_CANONICAL: dict[str, str] = {
    v["trading_symbol"]: k for k, v in _ZEBU_SYMBOL_MAP.items()
}

# NSE/BSE base symbol (no suffix) -> canonical (e.g. TATAMOTORS -> TATAMOTORS.NS)
_BASE_TO_CANONICAL: dict[str, str] = {}

# NSE ticker renames — watchlists/UI may use legacy names; Zebu master uses new Symbol.
# Maps legacy canonical -> live Zebu master canonical (same instrument, exact token).
_CANONICAL_EQUITY_ALIASES: dict[str, str] = {
    "TATAMOTORS.NS": "TMPV.NS",
}

# legacy watchlist ticker -> current NSE Symbol column in Zebu master file
_LEGACY_NSE_TICKER_ALIASES: dict[str, str] = {
    "TATAMOTORS": "TMPV",
}


def _normalize_equity_canonical(symbol: str) -> str:
    """Normalize to canonical form used in _ZEBU_SYMBOL_MAP keys."""
    clean = str(symbol or "").strip().upper()
    if not clean:
        return clean
    if clean.startswith("^") or clean.endswith((".NS", ".BO")):
        return clean
    if is_commodity_symbol(clean):
        return clean
    return f"{clean}.NS"


def canonical_to_zebu(symbol: str) -> Optional[dict]:
    """
    Convert AlphaSync canonical symbol to Zebu format.

    Returns:
        {"trading_symbol": "RELIANCE-EQ", "token": "2885", "exchange": "NSE"}
        or None if not yet mapped (call _resolve_symbol to populate on-demand).
    """
    canonical = _normalize_equity_canonical(symbol)
    if not canonical:
        return None

    hit = _ZEBU_SYMBOL_MAP.get(canonical)
    if hit:
        return hit

    alias_target = _CANONICAL_EQUITY_ALIASES.get(canonical)
    if alias_target:
        alias_hit = _ZEBU_SYMBOL_MAP.get(alias_target)
        if alias_hit:
            return alias_hit

    base = canonical.replace(".NS", "").replace(".BO", "")
    alt = _BASE_TO_CANONICAL.get(base)
    if alt:
        return _ZEBU_SYMBOL_MAP.get(alt)

    for trading_key in (f"{base}-EQ", base):
        mapped_canonical = _TRADING_TO_CANONICAL.get(trading_key)
        if mapped_canonical:
            return _ZEBU_SYMBOL_MAP.get(mapped_canonical)

    return None


def zebu_token_to_canonical(
    token: str, exchange: Optional[str] = None
) -> Optional[str]:
    """Convert Zebu exchange token to AlphaSync canonical symbol.

    Prefer exchange-scoped token mapping because token namespaces can overlap
    across exchanges.
    """
    tok = str(token or "").strip()
    if not tok:
        return None

    if exchange:
        exch = str(exchange).strip().upper()
        if exch:
            mapped = _TOKEN_TO_CANONICAL.get(f"{exch}|{tok}")
            if mapped:
                return mapped

    if tok in _AMBIGUOUS_TOKENS:
        return None
    return _TOKEN_TO_CANONICAL.get(tok)


def zebu_trading_to_canonical(trading_symbol: str) -> Optional[str]:
    """Convert Zebu trading symbol to AlphaSync canonical symbol."""
    return _TRADING_TO_CANONICAL.get(trading_symbol)


def get_all_zebu_tokens() -> list[dict]:
    """Return all mapped Zebu tokens for bulk subscription."""
    return [{"canonical": k, **v} for k, v in _ZEBU_SYMBOL_MAP.items()]


def load_zebu_contracts(contracts: list[dict]) -> int:
    """
    Load / refresh Zebu symbol mappings from master contract data.

    Expected format per contract:
        {"symbol": "RELIANCE", "token": "2885", "exchange": "NSE", ...}
        {"symbol": "GOLD",     "token": "...",  "exchange": "MCX", "trading_symbol": "GOLD"}

    Call this at startup after fetching the master contract file from Zebu.
    Returns the number of symbols loaded.
    """
    global _ZEBU_SYMBOL_MAP, _TOKEN_TO_CANONICAL, _TRADING_TO_CANONICAL
    global _AMBIGUOUS_TOKENS, _BASE_TO_CANONICAL
    count = 0

    for c in contracts:
        sym = c.get("symbol", "").strip()
        token = str(c.get("token", "")).strip()
        exchange = c.get("exchange", "NSE").strip().upper()
        explicit_canonical = c.get("canonical", "").strip()
        explicit_trading = c.get("trading_symbol", "").strip()

        if not sym or not token:
            continue

        if explicit_canonical:
            canonical = explicit_canonical.upper()
            trading = explicit_trading or sym
        elif exchange in {"MCX", "NCDEX"}:
            # Commodities: canonical is just the symbol (e.g. "GOLD", "COTTON")
            canonical = sym.upper()
            trading = c.get("trading_symbol", sym.upper())
        elif exchange in {"NFO", "BFO", "CDS", "NSE_FO", "BSE_FO"}:
            # Derivatives: keep canonical and trading symbol as contract symbol.
            canonical = sym.upper()
            trading = explicit_trading or sym.upper()
        elif exchange == "NSE":
            canonical = f"{sym}.NS"
            trading = explicit_trading or f"{sym}-EQ"
        else:
            canonical = f"{sym}.BO"
            trading = explicit_trading or f"{sym}-EQ"

        _ZEBU_SYMBOL_MAP[canonical] = {
            "trading_symbol": trading,
            "token": token,
            "exchange": exchange,
        }
        existing = _TOKEN_TO_CANONICAL.get(token)
        if existing and existing != canonical:
            _AMBIGUOUS_TOKENS.add(token)

        if token in _AMBIGUOUS_TOKENS:
            _TOKEN_TO_CANONICAL.pop(token, None)
        else:
            _TOKEN_TO_CANONICAL[token] = canonical

        _TOKEN_TO_CANONICAL[f"{exchange}|{token}"] = canonical
        _TRADING_TO_CANONICAL[trading] = canonical
        _TRADING_TO_CANONICAL[trading.upper()] = canonical
        _BASE_TO_CANONICAL[sym.upper()] = canonical

        # Register legacy NSE tickers that map to this master row (e.g. TMPV -> TATAMOTORS).
        if exchange == "NSE":
            for legacy_base, live_base in _LEGACY_NSE_TICKER_ALIASES.items():
                if sym.upper() == live_base:
                    legacy_canonical = f"{legacy_base}.NS"
                    _ZEBU_SYMBOL_MAP[legacy_canonical] = {
                        "trading_symbol": trading,
                        "token": token,
                        "exchange": exchange,
                    }
                    _BASE_TO_CANONICAL[legacy_base] = legacy_canonical
                    _TRADING_TO_CANONICAL[f"{legacy_base}-EQ"] = legacy_canonical

        count += 1

    logger.info(
        f"Loaded {count} Zebu contract mappings (total: {len(_ZEBU_SYMBOL_MAP)})"
    )
    return count


def has_zebu_mapping(symbol: str) -> bool:
    """Return True when symbol resolves to a Zebu token (master file or prior resolve)."""
    return canonical_to_zebu(symbol) is not None


def dump_commodity_token_map() -> dict:
    """Return all MCX/NCDEX entries in _TOKEN_TO_CANONICAL and _ZEBU_SYMBOL_MAP for diagnostics."""
    commodity_forward = {
        k: v for k, v in _ZEBU_SYMBOL_MAP.items()
        if v.get("exchange") in ("MCX", "NCDEX")
    }
    commodity_reverse = {
        k: v for k, v in _TOKEN_TO_CANONICAL.items()
        if k.startswith(("MCX|", "NCDEX|")) or is_commodity_symbol(str(v))
    }
    logger.info(
        f"[MCX TOKEN DUMP] forward_map ({len(commodity_forward)} entries): "
        f"{dict(list(commodity_forward.items())[:15])}"
    )
    logger.info(
        f"[MCX TOKEN DUMP] reverse_map ({len(commodity_reverse)} entries): "
        f"{dict(list(commodity_reverse.items())[:15])}"
    )
    return {
        "forward_map": commodity_forward,
        "reverse_map": commodity_reverse,
        "ambiguous_tokens": list(_AMBIGUOUS_TOKENS),
    }


def redis_price_lookup_symbols(symbol: str) -> list[str]:
    """
    Redis read order for a UI symbol.

    Legacy tickers (e.g. TATAMOTORS.NS) are checked AFTER the live Zebu master
    canonical (TMPV.NS) so stale pre-rename frozen keys are not returned first.
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
    """All canonical Redis keys that must receive the same live Zebu quote."""
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
