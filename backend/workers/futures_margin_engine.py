"""
Futures Margin Engine — SPAN-like margin calculation for simulated futures.

Replaces the flat 10% margin with a realistic tiered system:

SPAN Margin (Initial Margin):
- Index futures (NIFTY, BANKNIFTY, etc.): ~9-12% of contract value
- Stock futures: ~15-25% depending on volatility group

Exposure Margin (Additional Margin):
- Index futures: 3% of contract value
- Stock futures: 5% of contract value (higher for volatile stocks)

Total Margin = SPAN Margin + Exposure Margin

Dynamic Adjustments:
- Higher margin for volatile underlyings
- Slightly higher margin for far-expiry contracts (time risk)
- Reduced margin for hedged positions (future enhancement)

This module is ONLY used by futures systems. Does NOT affect equity/options/commodities.
"""

from decimal import Decimal
from typing import Optional
import re

# ---------------------------------------------------------------------------
# Volatility groups for stock futures (approximate NSE classifications)
# Group I: Low volatility (large caps) — ~15% SPAN
# Group II: Medium volatility — ~20% SPAN
# Group III: High volatility — ~25% SPAN
# ---------------------------------------------------------------------------

_VOLATILITY_GROUP_I = {
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR",
    "ITC", "SBIN", "BAJFINANCE", "BHARTIARTL", "KOTAKBANK", "LT",
    "AXISBANK", "MARUTI", "TITAN", "ASIANPAINT", "NESTLEIND",
    "ULTRACEMCO", "WIPRO", "HCLTECH", "TECHM", "POWERGRID",
    "NTPC", "ONGC", "SUNPHARMA", "DRREDDY", "CIPLA",
}

_VOLATILITY_GROUP_II = {
    "TATAMOTORS", "TATASTEEL", "ADANIENT", "ADANIPORTS", "JSWSTEEL",
    "HINDALCO", "COALINDIA", "GRASIM", "BPCL", "IOC",
    "INDUSINDBK", "BAJAJFINSV", "DIVISLAB", "HEROMOTOCO", "EICHERMOT",
    "APOLLOHOSP", "SHRIRAMFIN", "TRENT", "PIDILITIND", "HAVELLS",
    "ZOMATO", "JIOFIN", "ABB", "SIEMENS", "BEL",
}

# Everything else → Group III (highest margin)

# ---------------------------------------------------------------------------
# Index futures margin rates
# ---------------------------------------------------------------------------

_INDEX_MARGIN_RATES = {
    "NIFTY": {"span": Decimal("0.09"), "exposure": Decimal("0.03")},
    "BANKNIFTY": {"span": Decimal("0.10"), "exposure": Decimal("0.03")},
    "FINNIFTY": {"span": Decimal("0.10"), "exposure": Decimal("0.03")},
    "MIDCPNIFTY": {"span": Decimal("0.11"), "exposure": Decimal("0.035")},
    "NIFTYNXT50": {"span": Decimal("0.10"), "exposure": Decimal("0.03")},
    "SENSEX": {"span": Decimal("0.09"), "exposure": Decimal("0.03")},
    "BANKEX": {"span": Decimal("0.10"), "exposure": Decimal("0.03")},
}

# Stock futures margin by volatility group
_STOCK_MARGIN_RATES = {
    "group_i": {"span": Decimal("0.15"), "exposure": Decimal("0.05")},
    "group_ii": {"span": Decimal("0.20"), "exposure": Decimal("0.05")},
    "group_iii": {"span": Decimal("0.25"), "exposure": Decimal("0.075")},
}

# Known index underlyings (for classification)
_KNOWN_INDICES = set(_INDEX_MARGIN_RATES.keys())

# Far-expiry surcharge: contracts > 30 days out get slightly higher margin
_FAR_EXPIRY_SURCHARGE = Decimal("0.02")  # +2% for far expiries
_FAR_EXPIRY_THRESHOLD_DAYS = 30


def _extract_underlying(contract_symbol: str) -> str:
    """Extract underlying from contract symbol."""
    contract_symbol = contract_symbol.strip().upper()

    # Check known indices (longest first)
    for idx in sorted(_KNOWN_INDICES, key=len, reverse=True):
        if contract_symbol.startswith(idx):
            remainder = contract_symbol[len(idx):]
            if remainder and remainder[0].isdigit():
                return idx

    # Stock futures: everything before first digit
    match = re.match(r"^([A-Z&]+?)(\d{1,2}[A-Z]{3}\d{2,4})", contract_symbol)
    if match:
        return match.group(1)

    return contract_symbol


def _get_volatility_group(underlying: str) -> str:
    """Classify a stock underlying into volatility group."""
    underlying = underlying.upper()
    if underlying in _VOLATILITY_GROUP_I:
        return "group_i"
    elif underlying in _VOLATILITY_GROUP_II:
        return "group_ii"
    return "group_iii"


def _estimate_days_to_expiry(contract_symbol: str) -> Optional[int]:
    """Estimate days to expiry from contract symbol."""
    from datetime import datetime

    match = re.search(r"(\d{1,2})([A-Z]{3})(\d{2,4})", contract_symbol)
    if not match:
        return None

    day, month, year = match.groups()
    for fmt in ("%d%b%y", "%d%b%Y"):
        try:
            expiry = datetime.strptime(f"{day}{month}{year}", fmt)
            days = (expiry.date() - datetime.now().date()).days
            return max(0, days)
        except (ValueError, TypeError):
            continue

    return None


def get_margin_rates(contract_symbol: str) -> dict:
    """
    Get SPAN + Exposure margin rates for a contract.

    Returns:
        {
            "span_rate": Decimal,
            "exposure_rate": Decimal,
            "total_rate": Decimal,
            "underlying": str,
            "category": "index" | "stock",
            "volatility_group": str | None,
            "far_expiry_surcharge": Decimal,
        }
    """
    underlying = _extract_underlying(contract_symbol)

    # Index futures
    if underlying in _INDEX_MARGIN_RATES:
        rates = _INDEX_MARGIN_RATES[underlying]
        span_rate = rates["span"]
        exposure_rate = rates["exposure"]
        category = "index"
        vol_group = None
    else:
        # Stock futures
        vol_group = _get_volatility_group(underlying)
        rates = _STOCK_MARGIN_RATES[vol_group]
        span_rate = rates["span"]
        exposure_rate = rates["exposure"]
        category = "stock"

    # Far-expiry surcharge
    days = _estimate_days_to_expiry(contract_symbol)
    far_surcharge = Decimal("0")
    if days is not None and days > _FAR_EXPIRY_THRESHOLD_DAYS:
        far_surcharge = _FAR_EXPIRY_SURCHARGE

    total_rate = span_rate + exposure_rate + far_surcharge

    return {
        "span_rate": span_rate,
        "exposure_rate": exposure_rate,
        "total_rate": total_rate,
        "underlying": underlying,
        "category": category,
        "volatility_group": vol_group,
        "far_expiry_surcharge": far_surcharge,
    }


def get_margin_fraction(contract_symbol: str) -> Decimal:
    """
    Get the total margin fraction for a contract (SPAN + Exposure + surcharges).
    This is the single entry point used by trading service and settlement worker.
    """
    rates = get_margin_rates(contract_symbol)
    return rates["total_rate"]


def calculate_margin_required(
    contract_symbol: str,
    price: Decimal,
    quantity: int,
) -> dict:
    """
    Calculate full margin requirement for a futures position.

    Args:
        contract_symbol: Zebu futures contract symbol
        price: Execution/current price
        quantity: Number of units (not lots — raw qty)

    Returns:
        {
            "contract_value": Decimal,
            "span_margin": Decimal,
            "exposure_margin": Decimal,
            "far_expiry_surcharge": Decimal,
            "total_margin": Decimal,
            "margin_percent": Decimal (as percentage, e.g. 12.0),
            "rates": dict,
        }
    """
    rates = get_margin_rates(contract_symbol)
    contract_value = price * quantity

    span_margin = contract_value * rates["span_rate"]
    exposure_margin = contract_value * rates["exposure_rate"]
    far_surcharge_amount = contract_value * rates["far_expiry_surcharge"]
    total_margin = span_margin + exposure_margin + far_surcharge_amount

    return {
        "contract_value": contract_value,
        "span_margin": span_margin,
        "exposure_margin": exposure_margin,
        "far_expiry_surcharge": far_surcharge_amount,
        "total_margin": total_margin,
        "margin_percent": rates["total_rate"] * 100,
        "rates": rates,
    }
