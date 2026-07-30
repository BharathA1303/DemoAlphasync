"""
AlphaSync Market Data Providers.

Market data comes from the internal simulation engine (admin-configured, see
models/data_feed_config.py) when enabled, or the built-in ReplayProvider
simulator otherwise. No broker connections are made.

Usage:
    from services.data_feed_session import data_feed_session_manager

    provider = data_feed_session_manager.get_session(user_id)
    if provider:
        quote = await provider.get_quote("RELIANCE.NS")
"""

from providers.base import MarketProvider
from providers.factory import create_provider

__all__ = ["MarketProvider", "create_provider"]
