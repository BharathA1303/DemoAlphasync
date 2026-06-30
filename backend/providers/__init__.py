"""
AlphaSync Market Data Providers — Pluggable market data architecture.

Per-user provider model: each authenticated user gets their own
ZebuProvider instance, managed by BrokerSessionManager.

No global singleton.

Usage:
    from services.broker_session import broker_session_manager

    provider = broker_session_manager.get_session(user_id)
    if provider:
        quote = await provider.get_quote("RELIANCE.NS")
"""

from providers.base import MarketProvider
from providers.factory import create_zebu_provider

__all__ = ["MarketProvider", "create_zebu_provider"]
