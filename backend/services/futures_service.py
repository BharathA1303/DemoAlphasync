"""
Futures Service — Read-only derivatives analytics for NSE futures.

Responsibilities:
    * Load Zebu master contracts, filter for FUTIDX and FUTSTK instruments
    * Provide contract list endpoints grouped by underlying symbol
    * Cache contract lists and quotes in Redis with futures:* namespace
    * Import existing market_data and market_session functions (no duplication)
    * WebSocket integration for live futures prices

Contract metadata from Zebu:
    - Trading symbol (e.g., RELIANCE25MAR2026FUT)
    - Token ID (exchange-internal numeric ID)
    - Expiry date
    - Lot size
    - Tick size
    - Instrument type (FUTIDX or FUTSTK)

This service is READ-ONLY: no order placement, no broker access required.
Operates alongside existing market data infrastructure.
"""

import io
import logging
import re
import zipfile
import time
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

# Canonical index underlying symbols — ordered longest-first for greedy matching.
# This prevents "NIFTY" from matching inside "NIFTYNXT50" or "BANKNIFTY".
_KNOWN_INDEX_UNDERLYINGS = sorted(
    [
        "NIFTYNXT50",
        "MIDCPNIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "NIFTY",
        "SENSEX",
        "BANKEX",
    ],
    key=len,
    reverse=True,
)

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

from cache.redis_client import SNAPSHOT_TTL, get_redis, close_redis
from config.settings import settings
from engines.market_session import market_session, MarketState
from providers.symbol_mapper import (
    canonical_to_zebu,
    is_mcx_symbol,
    load_zebu_contracts,
)

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Zebu master contract CDN URLs — futures/options live in the F&O masters (NFO/BFO),
# NOT the cash NSE master. Using NSE_symbols.txt.zip here yielded zero FUT rows
# which forced the programmatic fallback with empty tokens → blank quotes.
_FNO_CONTRACT_SOURCES = [
    ("NFO", "https://go.mynt.in/NFO_symbols.txt.zip"),
    ("NFO", "https://api.zebull.in/NFO_symbols.txt.zip"),
    ("BFO", "https://go.mynt.in/BFO_symbols.txt.zip"),
    ("BFO", "https://api.zebull.in/BFO_symbols.txt.zip"),
]

# In-memory futures contracts cache, keyed by canonical symbol
# Format: {
#     "RELIANCE": [
#         {"contract_symbol": "RELIANCE25MAR2026FUT", "expiry": "2026-03-25", "lot_size": 250, ...}
#     ]
# }
_futures_contracts: dict = {}
_futures_contracts_loaded: bool = False


async def _fetch_and_parse_contracts() -> dict[str, list[dict]]:
    """
    Download and parse the Zebu master contract file, filtering for futures only.

    Returns a dict mapping canonical symbol → list of sorted futures contracts.
    Contracts are sorted by expiry date (nearest first).
    """
    contracts_by_symbol: dict[str, list[dict]] = {}

    # Download one master per exchange (NFO, BFO). Each segment has its own master;
    # we only need one successful mirror per exchange.
    downloaded: list[tuple[str, bytes]] = []
    seen_exchanges: set[str] = set()
    for exch_code, url in _FNO_CONTRACT_SOURCES:
        if exch_code in seen_exchanges:
            continue
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, follow_redirects=True)
                if resp.status_code == 200 and resp.content:
                    downloaded.append((exch_code, resp.content))
                    seen_exchanges.add(exch_code)
                    logger.info(
                        f"Downloaded Zebu {exch_code} futures master from {url} "
                        f"({len(resp.content):,} bytes)"
                    )
                    continue
                logger.warning(
                    f"Zebu {exch_code} contract download failed: {url} → HTTP {resp.status_code}"
                )
        except Exception as e:
            logger.warning(f"Zebu {exch_code} contract download error ({url}): {e}")

    if not downloaded:
        logger.error("Could not download any Zebu F&O master contracts for futures")
        return {}

    all_lines: list[tuple[str, str]] = []  # (default_exchange, line)
    header_line: Optional[str] = None

    for default_exch, raw_zip in downloaded:
        try:
            with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
                txt_files = [n for n in zf.namelist() if n.endswith(".txt")]
                if not txt_files:
                    logger.error(f"No .txt file found in Zebu {default_exch} ZIP")
                    continue
                with zf.open(txt_files[0]) as f:
                    raw_bytes = f.read()
                    try:
                        content = raw_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        content = raw_bytes.decode("latin-1", errors="replace")

            lines = content.splitlines()
            if not lines:
                continue
            if header_line is None:
                header_line = lines[0]
            for ln in lines[1:]:
                all_lines.append((default_exch, ln))
        except Exception as e:
            logger.error(
                f"Failed to unzip Zebu {default_exch} master: {e}", exc_info=True
            )

    if not header_line or not all_lines:
        return {}

    try:
        lines = [header_line]  # kept for compatibility with header parsing below

        # Parse header to locate relevant columns
        header = [col.strip().lower() for col in lines[0].split("|")]
        try:
            exch_idx = header.index("exchange") if "exchange" in header else 0
            token_idx = next((i for i, h in enumerate(header) if "token" in h), 1)
            sym_idx = next(
                (
                    i
                    for i, h in enumerate(header)
                    if "symbol" in h or "tradingsymbol" in h.replace(" ", "")
                ),
                2,
            )
            expiry_idx = next((i for i, h in enumerate(header) if "expiry" in h), 4)
            lot_size_idx = next(
                (i for i, h in enumerate(header) if "lotsz" in h or "lot" in h), -1
            )
            tick_size_idx = next((i for i, h in enumerate(header) if "tick" in h), -1)
            instrument_idx = next(
                (i for i, h in enumerate(header) if "instrument" in h), -1
            )
        except (ValueError, StopIteration):
            exch_idx, token_idx, sym_idx = 0, 1, 2
            expiry_idx, lot_size_idx, tick_size_idx, instrument_idx = 4, -1, -1, -1

        # Locate instrument-type column (FUTIDX/FUTSTK/OPTIDX/OPTSTK)
        instr_idx = next(
            (i for i, h in enumerate(header) if "instrument" in h), instrument_idx
        )

        # Extract futures contracts (FUTIDX or FUTSTK)
        for default_exch, line in all_lines:
            parts = line.split("|")
            if len(parts) <= max(exch_idx, token_idx, sym_idx, expiry_idx):
                continue

            exch = (
                parts[exch_idx].strip() if exch_idx < len(parts) else default_exch
            ) or default_exch

            # Fast filter: skip options rows before any further parsing
            if instr_idx >= 0 and instr_idx < len(parts):
                row_instr = parts[instr_idx].strip().upper()
                if row_instr and "FUT" not in row_instr:
                    continue
            token = parts[token_idx].strip() if token_idx < len(parts) else ""
            trading_sym = parts[sym_idx].strip() if sym_idx < len(parts) else ""
            expiry = parts[expiry_idx].strip() if expiry_idx < len(parts) else ""
            lot_size_str = (
                parts[lot_size_idx].strip() if 0 <= lot_size_idx < len(parts) else "0"
            )
            tick_size_str = (
                parts[tick_size_idx].strip()
                if 0 <= tick_size_idx < len(parts)
                else "0.05"
            )
            instrument_type = (
                parts[instrument_idx].strip()
                if 0 <= instrument_idx < len(parts)
                else ""
            )

            # Only process futures contracts. Zebu NFO tradingsymbols typically
            # end with a single "F" (e.g. NIFTY24APR26F), NOT "FUT". The reliable
            # discriminator is the instrument-type column (FUTIDX/FUTSTK/FUTCUR/FUTCOM).
            row_instr_upper = (
                parts[instr_idx].strip().upper() if 0 <= instr_idx < len(parts) else ""
            )
            is_future = row_instr_upper.startswith("FUT") or (
                not row_instr_upper
                and (
                    trading_sym.endswith("-FUT")
                    or trading_sym.endswith("FUT")
                    or (
                        trading_sym.endswith("F")
                        and not trading_sym.endswith("CE")
                        and not trading_sym.endswith("PE")
                    )
                )
            )
            if not is_future:
                continue
            # Explicitly exclude options
            if (
                row_instr_upper.startswith("OPT")
                or trading_sym.endswith("CE")
                or trading_sym.endswith("PE")
            ):
                continue

            if not token or not token.isdigit():
                continue

            # Determine if stock or index futures — prefer master-file column
            row_instr = (
                parts[instr_idx].strip().upper() if 0 <= instr_idx < len(parts) else ""
            )
            if row_instr in {"FUTIDX", "FUTSTK", "FUTCUR", "FUTCOM"}:
                inst_type = row_instr
            elif any(
                x in trading_sym for x in ["NIFTY", "SENSEX", "BANKNIFTY", "BANKEX"]
            ):
                inst_type = "FUTIDX"
            else:
                inst_type = "FUTSTK"

            # Extract base symbol using strict underlying parser
            # E.g., "NIFTY24APR26F" → "NIFTY", "NIFTYNXT5024APR26F" → "NIFTYNXT50"
            base_sym = _extract_underlying_from_tsym(trading_sym)
            if not base_sym:
                # Fallback: strip FUT suffix and parse digits
                stripped = trading_sym.replace("FUT", "").replace("-FUT", "").strip()
                expiry_label = ""
                for i in range(len(stripped)):
                    if stripped[i].isdigit():
                        expiry_label = stripped[i:]
                        base_sym = stripped[:i]
                        break
                if not base_sym or not expiry_label:
                    continue
            else:
                # Extract expiry label from the remainder after underlying
                remainder = trading_sym[len(base_sym):]
                remainder = remainder.rstrip("F").rstrip("-")
                expiry_label = remainder.strip()
                if not expiry_label:
                    continue

            # Parse lot size and tick size
            try:
                lot_size = int(float(lot_size_str)) if lot_size_str else 1
            except (ValueError, TypeError):
                lot_size = 1

            try:
                tick_size = float(tick_size_str) if tick_size_str else 0.05
            except (ValueError, TypeError):
                tick_size = 0.05

            # Parse expiry date if available
            expiry_date = _parse_expiry_date(expiry) or _estimate_expiry_from_label(
                expiry_label
            )

            if base_sym not in contracts_by_symbol:
                contracts_by_symbol[base_sym] = []

            contracts_by_symbol[base_sym].append(
                {
                    "contract_symbol": trading_sym,
                    "token": token,
                    "exchange": exch,
                    "expiry_date": expiry_date,
                    "expiry_label": expiry_label,
                    "lot_size": lot_size,
                    "tick_size": tick_size,
                    "instrument_type": inst_type,
                }
            )

        # Sort each symbol's contracts by expiry date (nearest first)
        for base_sym in contracts_by_symbol:
            contracts = contracts_by_symbol[base_sym]

            def expiry_key(c):
                if c.get("expiry_date"):
                    try:
                        return datetime.strptime(
                            c["expiry_date"], "%Y-%m-%d"
                        ).timestamp()
                    except (ValueError, TypeError):
                        return float("inf")
                return float("inf")

            contracts_by_symbol[base_sym] = sorted(contracts, key=expiry_key)

        logger.info(
            f"Parsed {sum(len(v) for v in contracts_by_symbol.values())} futures contracts "
            f"from Zebu NSE master"
        )

    except Exception as e:
        logger.error(f"Failed to parse Zebu futures contracts: {e}", exc_info=True)

    return contracts_by_symbol


def _extract_underlying_from_tsym(tsym: str) -> Optional[str]:
    """
    Extract the canonical underlying symbol from a Zebu futures trading symbol.

    Uses strict prefix matching against known index symbols (longest-first),
    then falls back to extracting everything before the first digit sequence
    that represents expiry (DDMMMYY pattern).

    Examples:
        NIFTY24APR26F       -> NIFTY
        NIFTYNXT5024APR26F  -> NIFTYNXT50
        BANKNIFTY24APR26F   -> BANKNIFTY
        RELIANCE24APR26F    -> RELIANCE
        MIDCPNIFTY24APR26F  -> MIDCPNIFTY

    NEVER uses substring/contains logic.
    """
    tsym = tsym.strip().upper()
    if not tsym:
        return None

    # Check known index underlyings via strict prefix match (longest first)
    for idx_sym in _KNOWN_INDEX_UNDERLYINGS:
        if tsym.startswith(idx_sym):
            remainder = tsym[len(idx_sym):]
            if remainder and remainder[0].isdigit():
                return idx_sym

    # For stock futures: extract everything before the expiry digits.
    # Expiry pattern is DD + MMM (3 alpha) + YY/YYYY, e.g. "24APR26"
    match = re.match(r"^([A-Z&]+?)(\d{1,2}[A-Z]{3}\d{2,4})", tsym)
    if match:
        return match.group(1)

    return None


def _parse_expiry_date(expiry_str: str) -> Optional[str]:
    """
    Parse Zebu expiry date string to YYYY-MM-DD format.
    Handles various formats: "25MAR2026", "25-Mar-2026", etc.
    Returns None if parsing fails.
    """
    if not expiry_str:
        return None

    # Try common Indian date format: "25MAR2026"
    try:
        dt = datetime.strptime(expiry_str.strip(), "%d%b%Y")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass

    # Try ISO format with hyphens: "25-Mar-2026"
    try:
        dt = datetime.strptime(expiry_str.strip(), "%d-%b-%Y")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass

    # Try lowercase: "25mar2026"
    try:
        dt = datetime.strptime(expiry_str.strip().upper(), "%d%b%Y")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass

    return None


def _estimate_expiry_from_label(label: str) -> Optional[str]:
    """
    Estimate expiry date from expiry label like "25MAR2026".
    Used as fallback when explicit expiry field is unavailable.
    """
    import re

    cleaned = label.strip().rstrip("F").rstrip("-")
    # Try 4-digit year first: "25MAR2026"
    match = re.match(r"(\d{1,2})([A-Za-z]{3})(\d{4})", cleaned)
    if match:
        day_str, month_str, year_str = match.groups()
        try:
            dt = datetime.strptime(f"{day_str}{month_str.upper()}{year_str}", "%d%b%Y")
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass
    # Try 2-digit year: "24APR26" (Zebu NFO format)
    match = re.match(r"(\d{1,2})([A-Za-z]{3})(\d{2})$", cleaned)
    if match:
        day_str, month_str, year_str = match.groups()
        try:
            dt = datetime.strptime(f"{day_str}{month_str.upper()}{year_str}", "%d%b%y")
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass
    return None


async def initialize_futures():
    """
    Called at startup to load futures contracts into memory.
    Populates _futures_contracts global cache from Zebu contract sources only.
    """
    global _futures_contracts, _futures_contracts_loaded

    try:
        logger.info("Initializing futures contracts from Zebu CDN...")
        _futures_contracts = await _fetch_and_parse_contracts()

        if _futures_contracts:
            # Pre-register futures token mappings so quote/subscription paths are token-ready.
            contracts_to_register = []
            for contract_list in _futures_contracts.values():
                for item in contract_list:
                    tsym = str(item.get("contract_symbol") or "").strip().upper()
                    token = str(item.get("token") or "").strip()
                    exch = str(item.get("exchange") or "NFO").strip().upper()
                    if not tsym or not token:
                        continue
                    contracts_to_register.append(
                        {
                            "symbol": tsym,
                            "canonical": tsym,
                            "trading_symbol": tsym,
                            "token": token,
                            "exchange": exch,
                        }
                    )

            if contracts_to_register:
                load_zebu_contracts(contracts_to_register)

            # Subscribe near-expiry futures for popular symbols to the master WS feed
            # so the UI receives live tick updates without per-request subscribes.
            try:
                await _subscribe_near_expiry_futures()
            except Exception as e:
                logger.debug(f"Futures WS pre-subscribe skipped: {e}")

            _futures_contracts_loaded = True
            total_contracts = sum(len(v) for v in _futures_contracts.values())
            logger.info(
                f"Futures contracts loaded successfully: {len(_futures_contracts)} symbols, "
                f"{total_contracts} total contracts from Zebu CDN"
            )
        else:
            logger.warning(
                "Zebu CDN returned empty contracts; futures contracts remain unavailable until Zebu data is restored"
            )
            _futures_contracts = {}
            _futures_contracts_loaded = False
    except Exception as e:
        logger.error(f"Failed to initialize futures contracts: {e}", exc_info=True)
        _futures_contracts = {}
        _futures_contracts_loaded = False


async def _subscribe_near_expiry_futures() -> None:
    """Subscribe the nearest-expiry futures of popular underlyings to master WS."""
    popular = {
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
        "NIFTYNXT50",
        "RELIANCE",
        "TCS",
        "HDFCBANK",
        "INFY",
        "ICICIBANK",
        "SBIN",
        "ITC",
        "LT",
        "AXISBANK",
        "HINDUNILVR",
        "MARUTI",
        "WIPRO",
        "SUNPHARMA",
        "KOTAKBANK",
        "BAJFINANCE",
        "TATAMOTORS",
        "BHARTIARTL",
        "ADANIENT",
    }
    symbols: list[str] = []
    for base, contracts in _futures_contracts.items():
        if base not in popular or not contracts:
            continue
        tsym = str(contracts[0].get("contract_symbol") or "").strip()
        if tsym:
            symbols.append(tsym)

    if not symbols:
        return

    from services.broker_session import broker_session_manager

    provider = broker_session_manager.get_any_session()
    if provider is None:
        try:
            from services.master_session import master_session_service

            if await master_session_service.initialize():
                provider = broker_session_manager.get_any_session()
        except Exception as e:
            logger.debug(f"Master-session recovery failed for futures subscribe: {e}")
    if provider is None:
        logger.info("No provider session — skipping futures WS pre-subscribe")
        return

    try:
        await provider.subscribe(symbols)
        logger.info(f"Subscribed {len(symbols)} near-expiry futures to WS")
    except Exception as e:
        logger.warning(f"Futures WS subscribe failed: {e}")


def get_contracts(symbol: str, limit: Optional[int] = None) -> list[dict]:
    """
    Get all futures contracts for a given symbol (canonical or trading format).
    """
    symbol = symbol.upper().strip().replace(".NS", "").replace(".BO", "")
    contracts = _futures_contracts.get(symbol, [])

    # Do not surface synthetic fallback entries with missing tokens because
    # they can resolve to wrong instruments at quote time.
    contracts = [c for c in contracts if str(c.get("token") or "").strip()]

    if not contracts:
        # Generate simulated contracts (Near, Mid, Far)
        import calendar
        from datetime import datetime, timedelta
        from market_data.replay.simulation_clock import simulation_clock

        now = simulation_clock.now()
        sim_contracts = []
        
        # Determine lot size
        lot_size = 250
        if symbol == "NIFTY":
            lot_size = 50
        elif symbol == "BANKNIFTY":
            lot_size = 15
        elif symbol == "FINNIFTY":
            lot_size = 40
        elif symbol == "SENSEX":
            lot_size = 10
        elif symbol in ("GOLD", "SILVER"):
            lot_size = 1

        # Determine instrument type
        inst_type = "FUTIDX" if symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "BANKEX") else "FUTSTK"

        # Generate expiries for current month, next month, and month after
        months_labels = ["Near", "Mid", "Far"]
        for idx, offset in enumerate(range(3)):
            # Calculate target month and year
            target_month = now.month + offset
            target_year = now.year
            while target_month > 12:
                target_month -= 12
                target_year += 1
            
            # Find the last Thursday of the target month
            c = calendar.monthcalendar(target_year, target_month)
            # Thursday is index 3 in monthcalendar (Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6)
            thursdays = []
            for week in c:
                if week[3] != 0:
                    thursdays.append(week[3])
            last_thursday = thursdays[-1]
            expiry_dt = datetime(target_year, target_month, last_thursday)
            
            # Form contract symbol: e.g. NIFTY26JUNFUT
            month_abbr = expiry_dt.strftime("%b").upper() # e.g. JUN
            year_abbr = expiry_dt.strftime("%y") # e.g. 26
            contract_symbol = f"{symbol}{year_abbr}{month_abbr}FUT"

            sim_contracts.append({
                "contract_symbol": contract_symbol,
                "token": contract_symbol,
                "expiry_date": expiry_dt.strftime("%Y-%m-%d"),
                "expiry_label": months_labels[idx],
                "lot_size": lot_size,
                "tick_size": 0.05,
                "instrument_type": inst_type,
                "exchange": "NFO" if inst_type in ("FUTIDX", "FUTSTK") else "MCX",
            })

        contracts = sim_contracts

    if limit:
        contracts = contracts[:limit]

    return contracts


async def get_contracts_live(symbol: str, limit: Optional[int] = None) -> list[dict]:
    """Fetch live futures contracts from Noren SearchScrip for one underlying."""
    symbol = symbol.upper().strip().replace(".NS", "").replace(".BO", "")

    from services.broker_session import broker_session_manager

    provider = broker_session_manager.get_any_session()
    if provider is None:
        try:
            from services.master_session import master_session_service

            if await master_session_service.initialize():
                provider = broker_session_manager.get_any_session()
        except Exception as e:
            logger.debug(f"Futures live contract recovery failed for {symbol}: {e}")

    if provider is None:
        return get_contracts(symbol, limit=limit)

    exch = "BFO" if symbol in {"SENSEX", "BANKEX"} else "NFO"
    data = await provider._rest_post("/SearchScrip", {"exch": exch, "stext": symbol})
    if not data or data.get("stat") != "Ok":
        return get_contracts(symbol, limit=limit)

    values = data.get("values") or []

    def _parse_expiry(tsym: str) -> Optional[str]:
        m = re.search(r"(\d{2}[A-Z]{3}\d{2,4})", tsym)
        if not m:
            return None
        raw = m.group(1)
        for fmt in ("%d%b%y", "%d%b%Y"):
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except Exception:
                continue
        return None

    contracts: list[dict] = []
    for item in values:
        tsym = str(item.get("tsym") or "").upper().strip()
        token = str(item.get("token") or "").strip()
        if not tsym or not token:
            continue

        # Keep only futures of this underlying.
        if not (tsym.endswith("F") or tsym.endswith("FUT")):
            continue
        # Strict underlying match — never use substring/contains logic
        extracted = _extract_underlying_from_tsym(tsym)
        if extracted != symbol:
            continue

        expiry_date = _parse_expiry(tsym)
        lot_raw = item.get("ls") or item.get("lotsize") or item.get("lot_size") or 1
        tick_raw = item.get("ti") or item.get("tick_size") or 0.05

        try:
            lot_size = int(float(lot_raw))
        except Exception:
            lot_size = 1
        try:
            tick_size = float(tick_raw)
        except Exception:
            tick_size = 0.05

        contracts.append(
            {
                "contract_symbol": tsym,
                "token": token,
                "exchange": exch,
                "expiry_date": expiry_date,
                "expiry_label": "",
                "lot_size": lot_size,
                "tick_size": tick_size,
                "instrument_type": (
                    "FUTIDX"
                    if symbol
                    in {
                        "NIFTY",
                        "BANKNIFTY",
                        "FINNIFTY",
                        "MIDCPNIFTY",
                        "NIFTYNXT50",
                        "SENSEX",
                        "BANKEX",
                    }
                    else "FUTSTK"
                ),
            }
        )

    if not contracts:
        return get_contracts(symbol, limit=limit)

    # Stable nearest-first sorting using parsed expiry.
    contracts.sort(key=lambda c: c.get("expiry_date") or "9999-12-31")

    # Refresh in-memory cache and symbol map with live contracts.
    _futures_contracts[symbol] = contracts
    try:
        load_zebu_contracts(
            [
                {
                    "symbol": c["contract_symbol"],
                    "canonical": c["contract_symbol"],
                    "trading_symbol": c["contract_symbol"],
                    "token": c["token"],
                    "exchange": c.get("exchange") or exch,
                }
                for c in contracts
            ]
        )
    except Exception as e:
        logger.debug(f"Futures live contract mapping refresh failed for {symbol}: {e}")

    if limit:
        contracts = contracts[:limit]

    return contracts


def label_expiry(expiry_date: str, ref_date: Optional[datetime] = None) -> str:
    """
    Classify an expiry as "Near", "Mid", or "Far" based on position in contract chain.
    In a typical 3-contract chain: Near (current), Mid (next), Far (third+).
    """
    if ref_date is None:
        ref_date = datetime.now().date()
    elif isinstance(ref_date, datetime):
        ref_date = ref_date.date()

    # This is set by contract position in the sorted list, not by calculation.
    # Handled at the API layer where we assign labels based on contract index.
    return "Near"  # Caller will override based on index


def _history_period_for_interval(interval: str) -> str:
    """Map chart interval to Zebu history period (aligns with equity terminal)."""
    iv = str(interval or "5m").lower()
    if iv in ("1m", "2m", "3m"):
        return "1d"
    if iv in ("5m", "10m", "15m", "30m", "1h", "2h", "4h"):
        return "5d"
    return "1mo"


async def _get_stream_last_quote(contract_symbol: str) -> Optional[dict]:
    """In-process last tick from FuturesStreamManager (same server session)."""
    try:
        from websocket.futures_stream import futures_stream_manager

        return futures_stream_manager.get_last_quote(contract_symbol)
    except Exception:
        return None


async def _quote_from_snapshot_history(contract_symbol: str) -> Optional[dict]:
    """Build a futures LTP quote from the latest persisted chart candle."""
    sym = str(contract_symbol or "").strip().upper()
    if not sym:
        return None

    for interval in ("1m", "5m"):
        candles = await get_snapshot_history(sym, interval=interval, limit=2)
        if not candles:
            continue

        last = candles[-1]
        try:
            close_price = round(float(last.get("close")), 2)
        except (TypeError, ValueError):
            continue
        if close_price <= 0:
            continue

        try:
            ts = int(float(last.get("time") or last.get("timestamp") or time.time()))
        except (TypeError, ValueError):
            ts = int(time.time())
        if not _is_current_closed_session_timestamp(ts):
            logger.debug("Rejected stale futures history snapshot for %s ts=%s", sym, ts)
            continue

        prev_close = None
        if len(candles) >= 2:
            try:
                prior_close = round(float(candles[-2].get("close")), 2)
                if prior_close > 0:
                    prev_close = prior_close
            except (TypeError, ValueError):
                prev_close = None

        quote = {
            "contract_symbol": sym,
            "symbol": sym,
            "ltp": close_price,
            "price": close_price,
            "lp": close_price,
            "last_price": close_price,
            "open": last.get("open"),
            "high": last.get("high"),
            "low": last.get("low"),
            "volume": last.get("volume") or 0,
            "timestamp": ts,
            "source": "history_snapshot",
            "market_session": "closed",
            "frozen": True,
        }
        if prev_close is not None:
            quote["prev_close"] = prev_close
        quote = _with_day_change(quote)
        await set_cache_quote(sym, quote)
        return quote

    return None


def _parse_epoch_seconds(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        ts = float(value)
        if ts > 1_000_000_000_000:
            ts /= 1000.0
        return ts if ts > 0 else None
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return None


def _quote_timestamp(quote: dict) -> Optional[float]:
    return _parse_epoch_seconds(
        quote.get("official_close_timestamp")
        or quote.get("exchange_timestamp")
        or quote.get("timestamp")
        or quote.get("last_trade_time")
        or quote.get("ft")
        or quote.get("frozen_at")
    )


def _is_current_closed_session_timestamp(value) -> bool:
    ts = _parse_epoch_seconds(value)
    if ts is None:
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


def _is_current_closed_session_quote(quote: dict) -> bool:
    return isinstance(quote, dict) and _is_current_closed_session_timestamp(
        _quote_timestamp(quote)
    )


def _with_day_change(quote: dict) -> dict:
    """Ensure futures quote has change/change_pct when close is available."""
    out = dict(quote or {})
    ltp_raw = out.get("ltp") or out.get("price") or out.get("lp")
    close_raw = out.get("prev_close") or out.get("previous_close") or out.get("close") or out.get("c")
    try:
        ltp = float(ltp_raw)
        prev_close = float(close_raw)
    except (TypeError, ValueError):
        return out
    if ltp <= 0 or prev_close <= 0:
        return out
    if out.get("change") is None:
        out["change"] = round(ltp - prev_close, 2)
    if out.get("change_pct") is None and out.get("change_percent") is None:
        out["change_pct"] = round((float(out["change"]) / prev_close) * 100.0, 2)
    out.setdefault("change_percent", out.get("change_pct"))
    out.setdefault("prev_close", prev_close)
    return out


async def get_snapshot_quote(contract_symbol: str) -> Optional[dict]:
    """
    Last-known futures quote for closed/holiday sessions.
    Order: stream memory → Redis snapshot → hot cache → equity frozen snapshot.
    """
    sym = str(contract_symbol or "").strip().upper()
    if not sym:
        return None

    market_frozen = market_session.get_current_state() != MarketState.OPEN
    if market_frozen:
        history_quote = await _quote_from_snapshot_history(sym)
        if history_quote:
            return history_quote

    try:
        redis = await get_redis(settings.REDIS_URL)
        raw = await redis.get(f"futures:snapshot:quote:{sym}")
        if raw:
            import json

            snap = json.loads(raw)
            if snap:
                if market_frozen and not _is_current_closed_session_quote(snap):
                    logger.debug(
                        "Rejected stale futures Redis snapshot for %s ts=%s",
                        sym,
                        _quote_timestamp(snap),
                    )
                    snap = None
                if snap:
                    snap.setdefault("source", "futures_snapshot")
                    return _with_day_change(snap)
    except Exception as e:
        logger.debug(f"Futures snapshot quote read failed for {sym}: {e}")

    cached = await get_cache_quote(sym)
    if cached:
        if market_frozen and not _is_current_closed_session_quote(cached):
            logger.debug(
                "Rejected stale futures hot cache for %s ts=%s",
                sym,
                _quote_timestamp(cached),
            )
        else:
            cached.setdefault("source", cached.get("source") or "futures_cache")
            return _with_day_change(cached)

    stream_q = await _get_stream_last_quote(sym)
    if stream_q and (stream_q.get("ltp") or stream_q.get("price") or stream_q.get("lp")):
        if market_frozen and not _is_current_closed_session_quote(stream_q):
            logger.debug(
                "Rejected stale futures stream quote for %s ts=%s",
                sym,
                _quote_timestamp(stream_q),
            )
        else:
            return _with_day_change({**stream_q, "source": stream_q.get("source") or "futures_stream"})

    try:
        from services.market_data import get_system_quote_live_only

        frozen = await get_system_quote_live_only(sym, allow_recover=False)
        if frozen and (frozen.get("ltp") or frozen.get("price") or frozen.get("lp")):
            frozen.setdefault("source", frozen.get("source") or "frozen")
            return _with_day_change(frozen)
    except Exception as e:
        logger.debug(f"Frozen equity-path quote failed for {sym}: {e}")

    return None


async def get_snapshot_history(
    contract_symbol: str, interval: str = "5m", limit: int = 500
) -> list[dict]:
    """Persisted OHLCV for closed market — futures snapshot then shared Redis history."""
    sym = str(contract_symbol or "").strip().upper()
    if not sym:
        return []

    try:
        redis = await get_redis(settings.REDIS_URL)
        raw = await redis.get(f"futures:snapshot:history:{sym}:{interval}")
        if raw:
            import json

            rows = json.loads(raw)
            if isinstance(rows, list) and rows:
                return rows[-limit:] if limit else rows
    except Exception as e:
        logger.debug(f"Futures snapshot history read failed for {sym}: {e}")

    period = _history_period_for_interval(interval)
    try:
        from cache.redis_client import get_history as redis_get_history
        from cache.redis_client import get_last_history as redis_get_last_history
        from services.market_data import normalize_history_candles

        for fetch in (
            lambda: redis_get_history(sym, period, interval),
            lambda: redis_get_last_history(sym, period, interval),
        ):
            try:
                cached = await fetch()
            except Exception:
                cached = None
            normalized = normalize_history_candles(cached or [])
            if normalized:
                return normalized[-limit:] if limit else normalized
    except Exception as e:
        logger.debug(f"Shared Redis history fallback failed for {sym}: {e}")

    return []


async def get_quote(contract_symbol: str) -> dict:
    """
    Fetch quote for a futures contract from market data service.

    Uses existing market_data.get_system_quote() which integrates with
    Zebu master session. Falls back to cached data if fresh fetch unavailable.

    Args:
        contract_symbol: Zebu futures contract symbol (e.g., "RELIANCE25MAR2026FUT")

    Returns:
        Quote dict with keys: ltp, open, high, low, close, volume, oi, etc.
        Returns empty dict if quote unavailable.
    """
    sym = str(contract_symbol or "").strip().upper()
    if not sym:
        return {}

    market_frozen = market_session.get_current_state() != MarketState.OPEN

    if market_frozen:
        snap = await get_snapshot_quote(sym)
        if snap:
            return snap

    try:
        from services.market_data import get_system_quote_live_only

        quote = await get_system_quote_live_only(sym, allow_recover=True)
        if quote:
            try:
                await set_cache_quote(sym, quote)
            except Exception as e:
                logger.debug(f"Cache set failed for {sym}: {e}")
            return quote

        cached = await get_cache_quote(sym)
        if cached:
            return cached

        snap = await get_snapshot_quote(sym)
        return snap if snap else {}

    except Exception as e:
        logger.error(f"Live quote fetch error for {sym}: {e}", exc_info=True)
        snap = await get_snapshot_quote(sym)
        return snap if snap else {}


async def get_history(
    contract_symbol: str, interval: str = "5m", limit: int = 30
) -> list[dict]:
    """
    Fetch OHLCV history for a futures contract (for sparkline).

    Args:
        contract_symbol: Zebu futures symbol
        interval: Candlestick interval (1m, 5m, 15m, 1h, 1d)
        limit: Number of candles to return

    Returns:
        List of OHLCV dicts: [{"timestamp": "...", "open": ..., "close": ...}, ...]
        Returns empty list if unavailable.
    """
    sym = str(contract_symbol or "").strip().upper()
    if not sym:
        return []

    period = _history_period_for_interval(interval)
    market_frozen = market_session.get_current_state() != MarketState.OPEN

    if market_frozen:
        snap_hist = await get_snapshot_history(sym, interval=interval, limit=limit)
        if snap_hist:
            return snap_hist

    try:
        if market_frozen:
            from services.market_data import get_historical_data

            history = await get_historical_data(
                symbol=sym,
                period=period,
                interval=interval,
                user_id=None,
            )
        else:
            from services.market_data import get_historical_data_live_only

            history = await get_historical_data_live_only(
                symbol=sym,
                period=period,
                interval=interval,
                user_id=None,
                allow_recover=True,
            )

        if history:
            trimmed = history[-limit:] if limit else history
            await set_snapshot_history(sym, interval, trimmed)
            return trimmed

        if market_frozen:
            return await get_snapshot_history(sym, interval=interval, limit=limit)

    except Exception as e:
        logger.warning(f"History fetch failed for {sym}: {e}")

    return await get_snapshot_history(sym, interval=interval, limit=limit)


async def get_cache_quote(contract_symbol: str) -> Optional[dict]:
    """
    Attempt to get quote from Redis cache first, before calling market_data.

    Cache key: futures:quote:{contract_symbol}
    TTL depends on market state: 3s if open, 300s if closed.

    Returns:
        Cached quote or None if not in cache.
    """
    try:
        redis = await get_redis(settings.REDIS_URL)
        cache_key = f"futures:quote:{contract_symbol}"
        cached = await redis.get(cache_key)

        if cached:
            import json

            return json.loads(cached)
    except Exception as e:
        logger.debug(f"Redis cache read failed: {e}")

    return None


async def set_snapshot_history(
    contract_symbol: str, interval: str, candles: list
) -> None:
    """Persist last good futures candle set for closed/holiday chart display."""
    sym = str(contract_symbol or "").strip().upper()
    if not sym or not candles:
        return
    try:
        import json

        redis = await get_redis(settings.REDIS_URL)
        await redis.setex(
            f"futures:snapshot:history:{sym}:{interval}",
            SNAPSHOT_TTL,
            json.dumps(candles),
        )
        period = _history_period_for_interval(interval)
        from cache.redis_client import set_history as redis_set_history

        await redis_set_history(sym, period, interval, candles)

        last = candles[-1]
        try:
            close_price = round(float(last.get("close")), 2)
        except (TypeError, ValueError):
            close_price = None
        if close_price and close_price > 0:
            try:
                ts = int(float(last.get("time") or last.get("timestamp") or time.time()))
            except (TypeError, ValueError):
                ts = int(time.time())
            await set_cache_quote(
                sym,
                {
                    "contract_symbol": sym,
                    "symbol": sym,
                    "ltp": close_price,
                    "price": close_price,
                    "lp": close_price,
                    "last_price": close_price,
                    "open": last.get("open"),
                    "high": last.get("high"),
                    "low": last.get("low"),
                    "volume": last.get("volume") or 0,
                    "timestamp": ts,
                    "source": "history_snapshot",
                    "market_session": "closed",
                    "frozen": True,
                },
            )
    except Exception as e:
        logger.debug(f"Futures snapshot history write failed for {sym}: {e}")


async def set_cache_quote(contract_symbol: str, quote: dict) -> None:
    """
    Cache a futures quote in Redis with appropriate TTL.

    Hot key TTL: 3s open / 300s closed. Snapshot key retained 7 days (equity parity).
    """
    sym = str(contract_symbol or "").strip().upper()
    if not sym or not quote:
        return
    try:
        redis = await get_redis(settings.REDIS_URL)
        cache_key = f"futures:quote:{sym}"

        market_state = market_session.get_current_state()
        if market_state == MarketState.OPEN:
            ttl = 3
        elif market_state == MarketState.CLOSED:
            ttl = 300
        else:
            ttl = 60

        import json

        payload = json.dumps(quote)
        await redis.setex(cache_key, ttl, payload)
        await redis.setex(f"futures:snapshot:quote:{sym}", SNAPSHOT_TTL, payload)

    except Exception as e:
        logger.debug(f"Redis cache write failed: {e}")


async def cache_contracts(symbol: str) -> None:
    """
    Cache the futures contracts list for a symbol in Redis.

    Cache key: futures:contracts:{symbol}
    TTL: 60 seconds (relatively stable during trading day)
    """
    try:
        contracts = get_contracts(symbol)
        if not contracts:
            return

        redis = await get_redis(settings.REDIS_URL)
        cache_key = f"futures:contracts:{symbol}"

        import json

        await redis.setex(cache_key, 60, json.dumps(contracts))

    except Exception as e:
        logger.debug(f"Redis contracts cache write failed: {e}")


async def get_cached_contracts_snapshot(symbol: str) -> list[dict]:
    """
    Return cached futures contracts without touching live provider.

    Order: Redis cache → in-memory contracts.
    """
    sym = str(symbol or "").strip().upper().replace(".NS", "").replace(".BO", "")
    if not sym:
        return []
    try:
        redis = await get_redis(settings.REDIS_URL)
        raw = await redis.get(f"futures:contracts:{sym}")
        if raw:
            import json

            cached = json.loads(raw)
            if isinstance(cached, list):
                return cached
    except Exception as e:
        logger.debug(f"Futures contracts snapshot read failed for {sym}: {e}")

    return _futures_contracts.get(sym, [])
