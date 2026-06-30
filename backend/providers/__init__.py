"""
AlphaSync Market Data Providers — Simulation-only data layer.

DemoAlphasync uses a single ReplayProvider for all market data.
No live broker connections are made.

Usage:
    from services.broker_session import broker_session_manager

    provider = broker_session_manager.get_session(user_id)
    if provider:
        quote = await provider.get_quote("RELIANCE.NS")
"""

from providers.base import MarketProvider
from providers.factory import create_provider

__all__ = ["MarketProvider", "create_provider"]
