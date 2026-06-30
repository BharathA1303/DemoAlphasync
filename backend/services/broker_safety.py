"""
Broker Safety Guards — Prevent accidental real trade execution.

This module ensures that AlphaSync NEVER places real orders, transfers
funds, or modifies positions through broker APIs.  The system only
uses broker credentials for:

    1. Authenticating the market-data WebSocket connection
    2. Reading real-time price ticks

All other broker API interactions are blocked.

Architecture:
    - ALLOWED_ENDPOINTS: Whitelist of safe Zebu API paths
    - BLOCKED_PATTERNS:  Patterns that indicate dangerous operations
    - validate_api_call(): Check before any outbound broker API call
    - SafeHttpClient:     Wrapper around httpx that enforces the guard
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ── Whitelisted safe endpoints (regex patterns) ────────────────────
# These are the ONLY Zebu API endpoints AlphaSync is allowed to call.
ALLOWED_ENDPOINTS: list[str] = [
    # Authentication
    r"/QuickAuth$",
    r"/UserDetails$",
    r"/Logout$",
    # Market data (read-only)
    r"/GetQuotes$",
    r"/GetIndexList$",
    r"/SearchScrip$",
    r"/GetTimePriceSeries$",
    r"/GetOptionChain$",
    r"/TPSeries$",
    r"/GetSecurityInfo$",
    r"/ExchMsg$",
    r"/GetTopList.*$",
    # WebSocket (handled separately, not HTTP)
]

# ── Blocked dangerous patterns ─────────────────────────────────────
# Any API path matching these patterns is ALWAYS blocked, even if
# it somehow gets added to the whitelist.
BLOCKED_PATTERNS: list[str] = [
    r"(?i)placeorder",
    r"(?i)modifyorder",
    r"(?i)cancelorder",
    r"(?i)exitorder",
    r"(?i)ordermargin",
    r"(?i)basketorder",
    r"(?i)multileg",
    r"(?i)spanmargin",
    r"(?i)funds",
    r"(?i)transfer",
    r"(?i)withdraw",
    r"(?i)payin",
    r"(?i)payout",
    r"(?i)edis",
    r"(?i)holdings",  # Block holdings modification (not read)
    r"(?i)convertposition",
    r"(?i)productconversion",
    r"(?i)squareoff",
    r"(?i)bracket",
    r"(?i)cover",
    r"(?i)amo",  # After-Market Orders
]

# ── Compiled regex (done once at import time) ──────────────────────
_allowed_re = [re.compile(p) for p in ALLOWED_ENDPOINTS]
_blocked_re = [re.compile(p) for p in BLOCKED_PATTERNS]


class BrokerSafetyError(Exception):
    """Raised when a blocked broker API call is attempted."""

    pass


def validate_api_call(url: str, method: str = "GET") -> bool:
    """
    Validate that an outbound broker API call is safe.

    Args:
        url:    Full URL or path component of the API call.
        method: HTTP method (GET, POST, etc.)

    Returns:
        True if the call is allowed.

    Raises:
        BrokerSafetyError if the call is blocked.
    """
    # Extract path from full URL
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path = parsed.path

    # ── Check blocked patterns first (always wins) ──────────────────
    for pattern in _blocked_re:
        if pattern.search(path):
            msg = (
                f"BLOCKED broker API call: {method} {path} "
                f"(matched blocked pattern: {pattern.pattern})"
            )
            logger.critical(msg)
            raise BrokerSafetyError(msg)

    # ── Check against whitelist ─────────────────────────────────────
    for pattern in _allowed_re:
        if pattern.search(path):
            logger.debug(f"Allowed broker API call: {method} {path}")
            return True

    # ── Not in whitelist → block ────────────────────────────────────
    msg = (
        f"BLOCKED broker API call: {method} {path} "
        f"(not in allowed endpoints whitelist)"
    )
    logger.warning(msg)
    raise BrokerSafetyError(msg)


class SafeHttpClient:
    """
    HTTP client wrapper that enforces safety guards on all requests.

    Usage:
        client = SafeHttpClient()
        data = await client.post("https://api.zebull.in/.../QuickAuth", json=payload)
    """

    def __init__(self, base_url: Optional[str] = None):
        import httpx

        self._client = httpx.AsyncClient(
            base_url=base_url or "",
            timeout=15.0,
        )

    async def get(self, url: str, **kwargs) -> dict:
        validate_api_call(url, "GET")
        resp = await self._client.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def post(self, url: str, **kwargs) -> dict:
        validate_api_call(url, "POST")
        resp = await self._client.post(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


def is_safe_websocket_message(msg: dict) -> bool:
    """
    Validate that an outbound WebSocket message is safe to send.

    Only subscription, heartbeat, and connection messages are allowed.
    """
    msg_type = msg.get("t", "")

    allowed_types = {
        "c",  # connection / auth
        "t",  # touchline subscribe
        "u",  # touchline unsubscribe
        "d",  # depth subscribe
        "ud",  # depth unsubscribe
        "h",  # heartbeat
    }

    if msg_type in allowed_types:
        return True

    # Any order-related message types
    blocked_types = {"o", "O", "om"}  # order messages
    if msg_type in blocked_types:
        logger.critical(
            f"BLOCKED WebSocket message type: {msg_type} "
            f"(order-related messages are not permitted)"
        )
        return False

    logger.warning(f"Unknown WebSocket message type: {msg_type}")
    return False
