"""
Zebu Master Contract Loader — fetches NSE/BSE/MCX/NCDEX symbol-token mappings.

Zebu (MYNT) publishes master contract files at public CDN URLs.
These files map every tradeable instrument's token to its trading symbol.

Called at startup in main.py so the symbol_mapper has full coverage
beyond the 20 hardcoded stocks.
"""

import io
import logging
import zipfile
from datetime import date as _date, datetime as _datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Public Zebu/MYNT contract CDN (no auth required)
_NSE_CONTRACT_URLS = [
    "https://go.mynt.in/NSE_symbols.txt.zip",
    "https://api.zebull.in/NSE_symbols.txt.zip",
]
_BSE_CONTRACT_URLS = [
    "https://go.mynt.in/BSE_symbols.txt.zip",
    "https://api.zebull.in/BSE_symbols.txt.zip",
]

# MCX / NCDEX commodity contract CDN URLs
_MCX_CONTRACT_URLS = [
    "https://go.mynt.in/MCX_symbols.txt.zip",
    "https://api.zebull.in/MCX_symbols.txt.zip",
]
_NCDEX_CONTRACT_URLS = [
    "https://go.mynt.in/NCDEX_symbols.txt.zip",
    "https://api.zebull.in/NCDEX_symbols.txt.zip",
]

# Known commodity base symbols — we load the nearest-expiry FUT contract for each
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


async def fetch_zebu_contracts(exchange: str = "NSE") -> list[dict]:
    """
    Download and parse the Zebu master contract file for an exchange.

    Args:
        exchange: "NSE" or "BSE"

    Returns a list of dicts with keys: symbol, token, exchange
    Only equity instruments (TradingSymbol ending in -EQ) are included.
    """
    urls = (
        _NSE_CONTRACT_URLS
        if exchange == "NSE"
        else _BSE_CONTRACT_URLS
        if exchange == "BSE"
        else []
    )

    raw_zip: Optional[bytes] = None
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, follow_redirects=True)
                if resp.status_code == 200 and resp.content:
                    raw_zip = resp.content
                    logger.info(
                        f"Downloaded Zebu {exchange} contracts from {url} "
                        f"({len(raw_zip):,} bytes)"
                    )
                    break
                else:
                    logger.warning(
                        f"Zebu contract download failed: {url} → HTTP {resp.status_code}"
                    )
        except Exception as e:
            logger.warning(f"Zebu contract download error ({url}): {e}")

    if not raw_zip:
        logger.error(f"Could not download Zebu {exchange} master contracts")
        return []

    return _parse_contract_zip(raw_zip, exchange)


def _detect_contract_delimiter(header_line: str) -> str:
    """Zebu publishes comma-separated masters; older builds used pipe-delimited rows."""
    if "|" in header_line and header_line.count("|") > header_line.count(","):
        return "|"
    if "," in header_line:
        return ","
    return "|"


def _parse_contract_header(header_line: str, delimiter: str) -> tuple[int, int, int, int]:
    """Return exchange, token, base symbol, and trading symbol column indices."""
    header = [col.strip().lower() for col in header_line.split(delimiter)]
    exch_idx = header.index("exchange") if "exchange" in header else 0
    token_idx = next((i for i, h in enumerate(header) if h == "token"), 1)
    base_idx = next((i for i, h in enumerate(header) if h == "symbol"), None)
    trading_idx = next(
        (
            i
            for i, h in enumerate(header)
            if "tradingsymbol" in h.replace(" ", "") or h == "tradingsymbol"
        ),
        None,
    )
    if trading_idx is None:
        trading_idx = base_idx if base_idx is not None else 2
    if base_idx is None:
        base_idx = trading_idx
    return exch_idx, token_idx, base_idx, trading_idx


def _parse_contract_zip(raw_zip: bytes, exchange: str) -> list[dict]:
    """
    Parse a Zebu master contract ZIP file.

    Current Zebu CDN files are comma-separated, e.g.:
        Exchange,Token,LotSize,Symbol,TradingSymbol,Instrument,...

    Older files used pipe-delimited rows. Both are supported.
    We only extract cash equity instruments (TradingSymbol ends in -EQ).
    """
    contracts = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
            # Find the .txt file inside the ZIP
            txt_files = [n for n in zf.namelist() if n.endswith(".txt")]
            if not txt_files:
                logger.error("No .txt file found in Zebu contract ZIP")
                return []

            with zf.open(txt_files[0]) as f:
                raw_bytes = f.read()
                try:
                    content = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    content = raw_bytes.decode("latin-1", errors="replace")

        lines = content.splitlines()
        if not lines:
            return []

        delimiter = _detect_contract_delimiter(lines[0])
        exch_idx, token_idx, base_idx, trading_idx = _parse_contract_header(
            lines[0], delimiter
        )

        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split(delimiter)
            if len(parts) <= max(exch_idx, token_idx, base_idx, trading_idx):
                continue

            exch = parts[exch_idx].strip()
            token = parts[token_idx].strip()
            trading_sym = parts[trading_idx].strip()
            base_sym = parts[base_idx].strip() or trading_sym

            # NSE equities are usually RELIANCE-EQ. BSE cash symbols from
            # Zebu can be plain RELIANCE, so keep those as BSE equities too.
            is_equity = trading_sym.endswith("-EQ") or (
                (exch or exchange).upper() == "BSE"
                and not trading_sym.endswith(("FUT", "CE", "PE"))
            )
            if not is_equity:
                continue
            if not token or not token.isdigit():
                continue

            if trading_sym.endswith("-EQ") and not base_sym.endswith("-EQ"):
                pass  # base_sym already set from Symbol column (e.g. M&M)
            elif trading_sym.endswith("-EQ"):
                base_sym = trading_sym[:-3]

            contracts.append(
                {
                    "symbol": base_sym,
                    "token": token,
                    "exchange": exch or exchange,
                    "trading_symbol": trading_sym,
                }
            )

        logger.info(
            f"Parsed {len(contracts)} equity instruments from "
            f"Zebu {exchange} master contracts"
        )
    except Exception as e:
        logger.error(f"Failed to parse Zebu contract ZIP: {e}", exc_info=True)

    return contracts


async def fetch_commodity_contracts() -> list[dict]:
    """
    Download and parse MCX and NCDEX master contracts.

    For each known commodity base symbol (GOLD, SILVER, CRUDEOIL, etc.), picks
    the nearest active (non-expired) futures contract and registers it so that
    get_quote("GOLD") resolves to the correct MCX token without a SearchScrip
    round-trip at quote time.

    Returns a list of dicts compatible with load_zebu_contracts().
    """
    results = []

    exchange_configs = [
        ("MCX", _MCX_CONTRACT_URLS, _MCX_COMMODITY_BASE),
        ("NCDEX", _NCDEX_CONTRACT_URLS, _NCDEX_COMMODITY_BASE),
    ]

    for exchange_name, urls, known_base_symbols in exchange_configs:
        raw_zip: Optional[bytes] = None
        for url in urls:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(url, follow_redirects=True)
                    if resp.status_code == 200 and resp.content:
                        raw_zip = resp.content
                        logger.info(
                            f"Downloaded Zebu {exchange_name} contracts from {url} "
                            f"({len(raw_zip):,} bytes)"
                        )
                        break
                    else:
                        logger.warning(
                            f"Zebu {exchange_name} contract download failed: "
                            f"{url} → HTTP {resp.status_code}"
                        )
            except Exception as e:
                logger.warning(
                    f"Zebu {exchange_name} contract download error ({url}): {e}"
                )

        if not raw_zip:
            logger.warning(
                f"Could not download Zebu {exchange_name} contracts — "
                f"commodity symbol resolution will fall back to SearchScrip"
            )
            continue

        contracts = _parse_commodity_zip(raw_zip, exchange_name, known_base_symbols)
        results.extend(contracts)
        logger.info(
            f"Loaded {len(contracts)} {exchange_name} near-expiry commodity contracts"
        )

    return results


def _parse_commodity_zip(
    raw_zip: bytes, exchange_name: str, known_base_symbols: set
) -> list[dict]:
    """
    Parse a MCX/NCDEX master contract ZIP.

    For each known commodity base symbol, collects all active (non-expired) FUT
    contracts and returns only the nearest-expiry one per symbol.
    """
    # base_symbol → list of (expiry_date, token, trading_symbol)
    by_base: dict[str, list] = {}

    try:
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
            txt_files = [n for n in zf.namelist() if n.endswith(".txt")]
            if not txt_files:
                logger.error(
                    f"No .txt file found in Zebu {exchange_name} contract ZIP"
                )
                return []

            with zf.open(txt_files[0]) as f:
                raw_bytes = f.read()
                try:
                    content = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    content = raw_bytes.decode("latin-1", errors="replace")

        lines = content.splitlines()
        if not lines:
            return []

        delimiter = _detect_contract_delimiter(lines[0])
        header = [col.strip().lower() for col in lines[0].split(delimiter)]
        exch_idx = header.index("exchange") if "exchange" in header else 0
        token_idx = next((i for i, h in enumerate(header) if "token" in h), 1)
        trading_idx = next(
            (
                i
                for i, h in enumerate(header)
                if "tradingsymbol" in h.replace(" ", "")
            ),
            None,
        )
        sym_idx = next(
            (i for i, h in enumerate(header) if h == "symbol" or h.endswith("symbol")),
            trading_idx if trading_idx is not None else 2,
        )
        if trading_idx is None:
            trading_idx = sym_idx
        expiry_idx = next((i for i, h in enumerate(header) if "expiry" in h), 4)
        instrument_idx = next(
            (i for i, h in enumerate(header) if "instrument" in h), -1
        )

        today = _date.today()

        for line in lines[1:]:
            parts = line.split(delimiter)
            if len(parts) <= max(exch_idx, token_idx, sym_idx, trading_idx, expiry_idx):
                continue

            token = parts[token_idx].strip()
            base_sym = parts[sym_idx].strip().upper()
            trading_sym = parts[trading_idx].strip().upper()
            expiry_raw = parts[expiry_idx].strip()
            instrument = (
                parts[instrument_idx].strip().upper()
                if 0 <= instrument_idx < len(parts)
                else ""
            )

            if not token or not token.isdigit():
                continue

            # Only futures instruments (skip options, spreads, etc.)
            if instrument and "FUT" not in instrument:
                continue
            if not instrument and not trading_sym.endswith("FUT"):
                continue

            # Match against known commodity base symbols
            matched_base: Optional[str] = None
            for base in sorted(known_base_symbols, key=len, reverse=True):
                # Symbol must START with the base and next char (if any) must be a digit
                # e.g. "GOLD" matches "GOLD24APR25" but not "GOLDM24APR25"
                for candidate_sym in (base_sym, trading_sym):
                    if not candidate_sym.startswith(base):
                        continue
                    remainder = candidate_sym[len(base):]
                    if not remainder or remainder[0].isdigit():
                        matched_base = base
                        break
                if matched_base:
                    break

            if not matched_base:
                continue

            # Parse expiry date
            expiry_date: Optional[_date] = None
            for fmt in ["%d%b%Y", "%d-%b-%Y", "%Y-%m-%d", "%d%b%y", "%d-%b-%y"]:
                try:
                    expiry_date = _datetime.strptime(
                        expiry_raw.upper(), fmt
                    ).date()
                    break
                except Exception:
                    continue

            if not expiry_date or expiry_date < today:
                continue  # skip expired contracts

            by_base.setdefault(matched_base, []).append(
                (expiry_date, token, trading_sym)
            )

    except Exception as e:
        logger.error(
            f"Failed to parse Zebu {exchange_name} commodity contracts: {e}",
            exc_info=True,
        )
        return []

    # Pick nearest-expiry contract for each base symbol
    contracts = []
    for base_sym, contract_list in by_base.items():
        contract_list.sort(key=lambda x: x[0])  # sort by expiry ascending
        expiry_date, token, trading_sym = contract_list[0]
        contracts.append(
            {
                "symbol": base_sym,
                "canonical": base_sym,
                "token": token,
                "exchange": exchange_name,
                "trading_symbol": trading_sym,
            }
        )
        logger.info(
            f"  {exchange_name} {base_sym} → {trading_sym} "
            f"(token={token}, expiry={expiry_date})"
        )

    return contracts


# In-memory cache of parsed NSE master contracts (CDN download, not Redis).
_NSE_CONTRACTS_CACHE: Optional[list[dict]] = None
_COMMODITY_CONTRACTS_CACHE: Optional[list[dict]] = None


async def get_commodity_contracts_cached(force_refresh: bool = False) -> list[dict]:
    """Return parsed MCX/NCDEX near-expiry contracts, downloading from Zebu CDN once per process."""
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
    Register Zebu token mappings for commodities missing from the in-memory map.

    Uses the official Zebu MCX/NCDEX master contract files (same source as startup).
    """
    from providers.symbol_mapper import (
        MCX_COMMODITY_SYMBOLS,
        NCDEX_COMMODITY_SYMBOLS,
        canonical_to_zebu,
        load_zebu_contracts,
    )

    if symbols:
        check_symbols = [str(sym or "").strip().upper() for sym in symbols if str(sym or "").strip()]
    else:
        check_symbols = sorted(MCX_COMMODITY_SYMBOLS | NCDEX_COMMODITY_SYMBOLS)

    missing = [sym for sym in check_symbols if sym and not canonical_to_zebu(sym)]
    if not missing:
        return 0

    contracts = await get_commodity_contracts_cached(force_refresh=force_refresh)
    if not contracts:
        logger.warning(
            "ensure_commodity_contract_mappings: MCX/NCDEX master contracts unavailable for %s",
            sorted(missing),
        )
        return 0

    missing_set = set(missing)
    to_register = [
        c
        for c in contracts
        if str(c.get("symbol", "")).strip().upper() in missing_set
    ]
    if not to_register:
        logger.warning(
            "ensure_commodity_contract_mappings: no master rows for %s",
            sorted(missing),
        )
        return 0

    loaded = load_zebu_contracts(to_register)
    if loaded:
        logger.info(
            "Registered %d Zebu commodity mappings from master for: %s",
            loaded,
            sorted(missing_set),
        )
    return loaded


async def get_nse_contracts_cached(force_refresh: bool = False) -> list[dict]:
    """Return parsed NSE equity contracts, downloading from Zebu CDN once per process."""
    global _NSE_CONTRACTS_CACHE
    if _NSE_CONTRACTS_CACHE is None or force_refresh:
        _NSE_CONTRACTS_CACHE = await fetch_zebu_contracts("NSE")
    return list(_NSE_CONTRACTS_CACHE or [])


async def ensure_nse_equity_mappings(canonical_symbols: list[str]) -> int:
    """
    Register Zebu token mappings for equities missing from the in-memory map.

    Uses the official Zebu NSE master contract file (same source as startup).
    Does not touch Redis hot/frozen state.
    """
    from providers.symbol_mapper import canonical_to_zebu, load_zebu_contracts

    missing_bases: set[str] = set()
    for sym in canonical_symbols or []:
        if canonical_to_zebu(sym):
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
            "ensure_nse_equity_mappings: NSE master contracts unavailable for %s",
            sorted(missing_bases),
        )
        return 0

    to_register = [
        c
        for c in contracts
        if str(c.get("symbol", "")).strip().upper() in missing_bases
    ]
    if not to_register:
        logger.warning(
            "ensure_nse_equity_mappings: no NSE master rows for %s",
            sorted(missing_bases),
        )
        return 0

    loaded = load_zebu_contracts(to_register)
    if loaded:
        logger.info(
            "Registered %d Zebu mappings from NSE master for: %s",
            loaded,
            sorted(missing_bases),
        )
    return loaded
