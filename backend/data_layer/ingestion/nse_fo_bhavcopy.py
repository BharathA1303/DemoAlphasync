import csv
import io
import time
import zipfile
import logging
from datetime import date, datetime
from typing import List, Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)

# Standard browser headers to avoid 403 Forbidden responses
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.nseindia.com/"
}

# Same throttling/retry approach as the cash-equity (CM) downloader in
# nse_bhavcopy.py - NSE's anti-bot protection applies uniformly across
# segments, so the same defenses apply here.
MIN_REQUEST_INTERVAL_SECONDS = 0.75
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0

# Instrument type codes used by the UDiFF F&O bhavcopy's FinInstrmTp column.
FUTURES_TYPES = {"FUTSTK", "FUTIDX"}
OPTIONS_TYPES = {"OPTSTK", "OPTIDX"}


def get_nse_fo_bhavcopy_url(target_date: date) -> str:
    """
    Constructs the NSE F&O (futures & options) bhavcopy URL using the UDiFF
    format introduced for the FO segment alongside CM (see nse_bhavcopy.py).
    Format: https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip
    """
    date_str = target_date.strftime("%Y%m%d")
    return f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv.zip"


def download_nse_fo_bhavcopy(target_date: date) -> bytes:
    """
    Downloads the zipped NSE F&O bhavcopy for a given date. Mirrors
    download_nse_bhavcopy()'s retry/backoff/anti-bot-detection behavior in
    nse_bhavcopy.py exactly, since both segments sit behind the same NSE
    archive host and anti-bot layer.
    """
    url = get_nse_fo_bhavcopy_url(target_date)

    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"Downloading NSE F&O Bhavcopy from URL: {url} (attempt {attempt}/{MAX_RETRIES})")
        time.sleep(MIN_REQUEST_INTERVAL_SECONDS)

        session = requests.Session()
        try:
            try:
                session.get("https://www.nseindia.com", headers=HEADERS, timeout=10)
            except Exception as e:
                logger.warning(f"Failed to initialize NSE session cookies: {e}")

            response = session.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 404:
                raise FileNotFoundError(f"NSE F&O Bhavcopy not found for {target_date} (likely a market holiday or weekend)")
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "zip" not in content_type and response.content[:2] != b"PK":
                raise ValueError(
                    f"NSE F&O response for {target_date} did not look like a zip file "
                    f"(content-type={content_type!r}) - likely blocked by anti-bot protection"
                )

            return response.content
        except FileNotFoundError:
            raise
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                backoff = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    f"NSE F&O Bhavcopy download attempt {attempt}/{MAX_RETRIES} failed for {target_date}: {e}. "
                    f"Retrying in {backoff:.1f}s..."
                )
                time.sleep(backoff)
        finally:
            session.close()

    raise RuntimeError(
        f"NSE F&O Bhavcopy download failed for {target_date} after {MAX_RETRIES} attempts: {last_error}"
    ) from last_error


def _parse_udiff_date(raw: str) -> Optional[date]:
    """Parses UDiFF date strings, which are typically DD-MMM-YYYY (e.g. '27-Jun-2026')."""
    if not raw:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_nse_fo_bhavcopy_csv(csv_content: str, target_date: date) -> List[Dict[str, Any]]:
    """
    Parses the NSE F&O UDiFF bhavcopy CSV into PriceData-shaped records
    covering both futures (FUTSTK/FUTIDX) and options (OPTSTK/OPTIDX) on
    stocks and indices, with real strikes, expiries, and open interest -
    not synthesized values.
    """
    if csv_content.strip().startswith("<!DOCTYPE") or "<html" in csv_content.lower():
        logger.warning(f"NSE F&O downloaded content for {target_date} is HTML instead of CSV.")
        return []

    records = []
    f = io.StringIO(csv_content)
    reader = csv.DictReader(f)

    if not reader.fieldnames:
        raise ValueError("Empty CSV file or invalid headers in NSE F&O bhavcopy")

    reader.fieldnames = [field.strip() for field in reader.fieldnames if field is not None]

    for row_idx, row in enumerate(reader):
        try:
            cleaned_row = {}
            for k, v in row.items():
                if k is not None:
                    cleaned_row[k.strip()] = v.strip() if (v is not None and hasattr(v, "strip")) else ""

            instrument_type = cleaned_row.get("FinInstrmTp", "")
            is_future = instrument_type in FUTURES_TYPES
            is_option = instrument_type in OPTIONS_TYPES
            if not is_future and not is_option:
                continue  # Skip other instrument types (e.g. currency/commodity derivatives mixed into the same file)

            symbol = cleaned_row.get("TckrSymb", "")
            if not symbol:
                continue

            expiry = _parse_udiff_date(cleaned_row.get("XpryDt", ""))
            if expiry is None:
                logger.debug(f"Skipping row {row_idx}: unparseable expiry date {cleaned_row.get('XpryDt')!r}")
                continue

            open_interest_raw = cleaned_row.get("OpnIntrst", "0") or "0"

            if is_future:
                records.append({
                    "symbol": symbol,
                    "exchange": "NSE",
                    "segment": "FUT",
                    "expiry": expiry,
                    "strike": None,
                    "option_type": None,
                    "open_interest": int(float(open_interest_raw)),
                    "market_timestamp": target_date,
                    "open": float(cleaned_row["OpnPric"]),
                    "high": float(cleaned_row["HghPric"]),
                    "low": float(cleaned_row["LwPric"]),
                    "close": float(cleaned_row["ClsPric"]),
                    "volume": int(float(cleaned_row.get("TtlTradgVol", "0") or "0")),
                })
            else:
                strike_raw = cleaned_row.get("StrkPric", "")
                option_type = cleaned_row.get("OptnTp", "")
                if not strike_raw or option_type not in ("CE", "PE"):
                    continue
                records.append({
                    "symbol": symbol,
                    "exchange": "NSE",
                    "segment": "OPT",
                    "expiry": expiry,
                    "strike": float(strike_raw),
                    "option_type": option_type,
                    "open_interest": int(float(open_interest_raw)),
                    "market_timestamp": target_date,
                    "open": float(cleaned_row["OpnPric"]),
                    "high": float(cleaned_row["HghPric"]),
                    "low": float(cleaned_row["LwPric"]),
                    "close": float(cleaned_row["ClsPric"]),
                    "volume": int(float(cleaned_row.get("TtlTradgVol", "0") or "0")),
                })
        except (KeyError, ValueError) as e:
            logger.debug(f"Skipping F&O row {row_idx} due to parse error: {e}")
            continue

    return records


def generate_mock_nse_fo_data(target_date: date) -> List[Dict[str, Any]]:
    """
    Generates realistic mock NSE F&O records (one futures contract and a
    handful of option strikes per underlying) for testing and local dev,
    mirroring the shape of real UDiFF F&O data without hitting the network.
    """
    logger.info(f"Generating mock NSE F&O data for {target_date}")
    import random

    # Anchors mirror _NSE_MOCK_ANCHORS in nse_bhavcopy.py so a given
    # underlying's futures/options spot reference stays consistent with its
    # cash-equity price series (see mock_price_continuity.py).
    mock_underlyings = {
        "RELIANCE": (2800.0, 0.0004),
        "TCS": (3600.0, 0.0003),
        "INFY": (1500.0, 0.0004),
        "HDFCBANK": (1650.0, 0.0003),
        "ICICIBANK": (1050.0, 0.00035),
    }

    # Major index underlyings — these are the most important for the options
    # desk (NIFTY/BANKNIFTY chain). Without these, the _internal_sim_option_chain
    # endpoint returns zero results for every leg query with segment="OPT".
    mock_index_underlyings = {
        "NIFTY": (24500.0, 0.0003),
        "BANKNIFTY": (51500.0, 0.0004),
        "FINNIFTY": (23000.0, 0.00035),
    }

    records = []
    from data_layer.ingestion.mock_price_continuity import anchor_price_for_date

    # Monthly expiry: last Thursday of next month, matching real NSE convention.
    from datetime import timedelta
    year, month = target_date.year, target_date.month + 1
    if month > 12:
        month = 1
        year += 1
    if month == 12:
        last_day = date(year, 12, 31)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    while last_day.weekday() != 3:
        last_day -= timedelta(days=1)
    expiry = last_day

    # Also compute the nearest weekly expiry (next Thursday).
    weekly_expiry = target_date
    while weekly_expiry.weekday() != 3:
        weekly_expiry += timedelta(days=1)
    if weekly_expiry <= target_date:
        weekly_expiry += timedelta(days=7)

    # ── Stock futures + options ──────────────────────────────────────────
    for symbol, (anchor, drift) in mock_underlyings.items():
        seed = int(target_date.strftime("%Y%m%d")) + sum(ord(c) for c in symbol)
        rng = random.Random(seed)
        spot = anchor_price_for_date(anchor, drift, target_date)

        # Futures contract (small premium/contango over spot).
        fut_close = spot * 1.002
        fut_open = spot * 1.0015
        records.append({
            "symbol": symbol, "exchange": "NSE", "segment": "FUT",
            "expiry": expiry, "strike": None, "option_type": None,
            "open_interest": rng.randint(50000, 500000),
            "market_timestamp": target_date,
            "open": round(fut_open, 2), "high": round(fut_close * 1.01, 2),
            "low": round(fut_open * 0.99, 2), "close": round(fut_close, 2),
            "volume": rng.randint(10000, 200000),
        })

        # Option chain: 7 strikes around spot, both CE and PE.
        strike_step = 50.0 if spot < 1000 else 100.0
        atm_strike = round(spot / strike_step) * strike_step
        for offset in (-3, -2, -1, 0, 1, 2, 3):
            strike = atm_strike + offset * strike_step
            for option_type in ("CE", "PE"):
                intrinsic = max(0.0, (spot - strike) if option_type == "CE" else (strike - spot))
                premium = intrinsic + rng.uniform(5.0, 40.0)
                records.append({
                    "symbol": symbol, "exchange": "NSE", "segment": "OPT",
                    "expiry": expiry, "strike": strike, "option_type": option_type,
                    "open_interest": rng.randint(1000, 100000),
                    "market_timestamp": target_date,
                    "open": round(premium * 0.98, 2), "high": round(premium * 1.1, 2),
                    "low": round(premium * 0.9, 2), "close": round(premium, 2),
                    "volume": rng.randint(500, 50000),
                })

    # ── Index futures + options (NIFTY, BANKNIFTY, FINNIFTY) ────────────
    # These are critical: the options desk chains for indices only work if
    # OPT rows exist in PriceData with segment='OPT' for these underlyings.
    for symbol, (anchor, drift) in mock_index_underlyings.items():
        seed = int(target_date.strftime("%Y%m%d")) + sum(ord(c) for c in symbol)
        rng = random.Random(seed)
        spot = anchor_price_for_date(anchor, drift, target_date)

        strike_step = 100.0 if symbol == "BANKNIFTY" else 50.0
        atm_strike = round(spot / strike_step) * strike_step

        # Monthly futures
        fut_close = spot * 1.002
        fut_open = spot * 1.0015
        records.append({
            "symbol": symbol, "exchange": "NSE", "segment": "FUT",
            "expiry": expiry, "strike": None, "option_type": None,
            "open_interest": rng.randint(100000, 2000000),
            "market_timestamp": target_date,
            "open": round(fut_open, 2), "high": round(fut_close * 1.008, 2),
            "low": round(fut_open * 0.992, 2), "close": round(fut_close, 2),
            "volume": rng.randint(50000, 1000000),
        })

        # Weekly futures (for near-term contracts)
        wfut_close = spot * 1.0005
        records.append({
            "symbol": symbol, "exchange": "NSE", "segment": "FUT",
            "expiry": weekly_expiry, "strike": None, "option_type": None,
            "open_interest": rng.randint(50000, 800000),
            "market_timestamp": target_date,
            "open": round(wfut_close * 0.999, 2), "high": round(wfut_close * 1.006, 2),
            "low": round(wfut_close * 0.993, 2), "close": round(wfut_close, 2),
            "volume": rng.randint(20000, 500000),
        })

        # Weekly options chain: 10 strikes around ATM, both monthly + weekly expiry
        for exp_date in (weekly_expiry, expiry):
            for offset in range(-5, 6):
                strike = atm_strike + offset * strike_step
                if strike <= 0:
                    continue
                for option_type in ("CE", "PE"):
                    intrinsic = max(0.0, (spot - strike) if option_type == "CE" else (strike - spot))
                    time_val = max(10.0, 200.0 - abs(offset) * 30.0) if symbol == "BANKNIFTY" else max(5.0, 150.0 - abs(offset) * 20.0)
                    premium = intrinsic + rng.uniform(time_val * 0.8, time_val * 1.2)
                    records.append({
                        "symbol": symbol, "exchange": "NSE", "segment": "OPT",
                        "expiry": exp_date, "strike": strike, "option_type": option_type,
                        "open_interest": rng.randint(5000, 5000000),
                        "market_timestamp": target_date,
                        "open": round(premium * 0.97, 2), "high": round(premium * 1.12, 2),
                        "low": round(premium * 0.88, 2), "close": round(premium, 2),
                        "volume": rng.randint(1000, 2000000),
                    })

    return records


def get_nse_fo_data(target_date: date, use_mock: bool = False) -> List[Dict[str, Any]]:
    """Main entrypoint to get NSE F&O records. Downloads or mocks them."""
    if use_mock:
        return generate_mock_nse_fo_data(target_date)

    try:
        zip_bytes = download_nse_fo_bhavcopy(target_date)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            csv_filenames = [name for name in z.namelist() if name.endswith(".csv")]
            if not csv_filenames:
                raise ValueError("No CSV file found inside NSE F&O bhavcopy zip")

            with z.open(csv_filenames[0]) as f:
                csv_content = f.read().decode("utf-8", errors="ignore")

        return parse_nse_fo_bhavcopy_csv(csv_content, target_date)
    except FileNotFoundError as e:
        logger.warning(str(e))
        return []
    except Exception as e:
        logger.error(f"Error fetching/parsing NSE F&O Bhavcopy for {target_date}: {e}")
        raise e
