"""
Centralized registry for all futures contracts (NFO/BFO).

Pre-loads from futures_service._futures_contracts (populated at startup from Zebu CDN)
and maintains multiple in-memory indexes for fast, reconnect-safe lookups without any
API/REST calls.
"""

import logging
from datetime import datetime
from typing import Optional

from services import futures_service

logger = logging.getLogger(__name__)

# Lot sizes for well-known index futures.
INDEX_LOT_SIZES: dict[str, int] = {
    "NIFTY": 75,
    "BANKNIFTY": 35,
    "FINNIFTY": 65,
    "MIDCPNIFTY": 100,
    "SENSEX": 20,
    "NIFTYNXT50": 25,
}


class FuturesContractRegistry:
    """
    Single-threaded (asyncio-safe) in-memory registry that indexes every futures
    contract by token, symbol, underlying, and expiry date.
    """

    def __init__(self) -> None:
        # exchange|token -> contract dict
        self.token_to_contract: dict[str, dict] = {}
        # contract_symbol -> token string
        self.contract_to_token: dict[str, str] = {}
        # underlying -> [contracts sorted by expiry]
        self.underlying_to_contracts: dict[str, list[dict]] = {}
        # "YYYY-MM-DD" -> [contracts expiring that day]
        self.expiry_groups: dict[str, list[dict]] = {}
        # underlying -> {"near": contract, "mid": contract, "far": contract}
        self.near_mid_far: dict[str, dict[str, Optional[dict]]] = {}

        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Build all indexes from futures_service in-memory cache."""
        self._clear_indexes()

        source: dict = futures_service._futures_contracts
        if not source:
            logger.warning(
                "FuturesContractRegistry: futures_service._futures_contracts is empty; "
                "indexes will be empty until refresh_from_service() is called"
            )
            self._initialized = True
            return

        total = 0
        expired_count = 0
        today_str = datetime.now().strftime("%Y-%m-%d")

        for underlying, contracts in source.items():
            active_contracts: list[dict] = []
            for c in contracts:
                contract_symbol = str(c.get("contract_symbol") or "").strip().upper()
                token = str(c.get("token") or "").strip()
                exchange = str(c.get("exchange") or "NFO").strip().upper()
                expiry_date = str(c.get("expiry_date") or "").strip()

                if not contract_symbol or not token:
                    continue

                if expiry_date and expiry_date < today_str:
                    expired_count += 1
                    continue

                total += 1
                active_contracts.append(c)

                key = f"{exchange}|{token}"
                self.token_to_contract[key] = c
                self.contract_to_token[contract_symbol] = token

                self.expiry_groups.setdefault(expiry_date, []).append(c)

            if active_contracts:
                active_contracts.sort(key=lambda x: x.get("expiry_date") or "9999-12-31")
                self.underlying_to_contracts[underlying.upper()] = active_contracts

        self._build_near_mid_far()
        self._initialized = True

        logger.info(
            "FuturesContractRegistry initialized: %d active contracts, "
            "%d underlyings, %d expired (skipped)",
            total,
            len(self.underlying_to_contracts),
            expired_count,
        )

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_contract(self, contract_symbol: str) -> Optional[dict]:
        """Return the contract dict for a given contract symbol, or None."""
        contract_symbol = contract_symbol.strip().upper()
        token = self.contract_to_token.get(contract_symbol)
        if token is None:
            return None
        for key, c in self.token_to_contract.items():
            if str(c.get("contract_symbol", "")).strip().upper() == contract_symbol:
                return c
        return None

    def get_token(self, contract_symbol: str) -> Optional[str]:
        """Return the token string for a contract symbol, or None."""
        return self.contract_to_token.get(contract_symbol.strip().upper())

    def get_exchange(self, contract_symbol: str) -> str:
        """Return the exchange for a contract symbol (defaults to 'NFO')."""
        c = self.get_contract(contract_symbol)
        if c:
            return str(c.get("exchange") or "NFO").strip().upper()
        return "NFO"

    def get_contracts_for_underlying(self, symbol: str) -> list[dict]:
        """Return all active contracts for an underlying, sorted by expiry."""
        return list(self.underlying_to_contracts.get(symbol.strip().upper(), []))

    def get_near_contract(self, symbol: str) -> Optional[dict]:
        """Return the nearest-expiry contract for an underlying."""
        group = self.near_mid_far.get(symbol.strip().upper())
        if group:
            return group.get("near")
        return None

    def get_expiry_group(self, date_str: str) -> list[dict]:
        """Return all contracts expiring on the given date (YYYY-MM-DD)."""
        return list(self.expiry_groups.get(date_str.strip(), []))

    def is_expired(self, contract_symbol: str) -> bool:
        """Check whether a contract's expiry date is in the past."""
        c = self.get_contract(contract_symbol)
        if not c:
            return True
        expiry = c.get("expiry_date") or ""
        if not expiry:
            return False
        return expiry < datetime.now().strftime("%Y-%m-%d")

    def get_all_active_tokens(self) -> list[tuple[str, str]]:
        """Return (exchange, token) tuples for every active contract — ready for subscription."""
        result: list[tuple[str, str]] = []
        for key in self.token_to_contract:
            parts = key.split("|", 1)
            if len(parts) == 2:
                result.append((parts[0], parts[1]))
        return result

    def resolve_contract(self, contract_symbol: str) -> Optional[dict]:
        """
        Return a normalized dict with all essential fields for a contract symbol,
        or None if not found.
        """
        c = self.get_contract(contract_symbol)
        if not c:
            return None
        symbol = contract_symbol.strip().upper()
        return {
            "contract_symbol": symbol,
            "token": str(c.get("token") or ""),
            "exchange": str(c.get("exchange") or "NFO").strip().upper(),
            "lot_size": int(c.get("lot_size") or 0),
            "tick_size": float(c.get("tick_size") or 0.05),
            "expiry_date": str(c.get("expiry_date") or ""),
            "expiry_label": str(c.get("expiry_label") or ""),
            "instrument_type": str(c.get("instrument_type") or ""),
        }

    # ------------------------------------------------------------------
    # Expiry rollover & cleanup
    # ------------------------------------------------------------------

    def cleanup_expired(self) -> int:
        """
        Remove expired contracts from every index and re-build near/mid/far.
        Returns the number of contracts removed.
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        removed = 0

        expired_symbols: list[str] = []
        for sym, token in list(self.contract_to_token.items()):
            c = self._find_contract_by_symbol(sym)
            if c and (c.get("expiry_date") or "") < today_str:
                expired_symbols.append(sym)

        for sym in expired_symbols:
            self._remove_contract(sym)
            removed += 1

        if removed:
            self._rebuild_expiry_groups()
            self._build_near_mid_far()
            logger.info("FuturesContractRegistry: cleaned up %d expired contracts", removed)

        return removed

    # ------------------------------------------------------------------
    # Refresh / re-sync
    # ------------------------------------------------------------------

    async def refresh_from_service(self) -> None:
        """Re-sync all indexes from futures_service (e.g. after live SearchScrip updates)."""
        logger.info("FuturesContractRegistry: refreshing from futures_service...")
        await self.initialize()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clear_indexes(self) -> None:
        self.token_to_contract.clear()
        self.contract_to_token.clear()
        self.underlying_to_contracts.clear()
        self.expiry_groups.clear()
        self.near_mid_far.clear()

    def _build_near_mid_far(self) -> None:
        """Assign near/mid/far for every underlying from sorted contract lists."""
        self.near_mid_far.clear()
        for underlying, contracts in self.underlying_to_contracts.items():
            near = contracts[0] if len(contracts) > 0 else None
            mid = contracts[1] if len(contracts) > 1 else None
            far = contracts[2] if len(contracts) > 2 else None
            self.near_mid_far[underlying] = {"near": near, "mid": mid, "far": far}

    def _find_contract_by_symbol(self, contract_symbol: str) -> Optional[dict]:
        """Locate a contract dict by symbol across all underlying lists."""
        for contracts in self.underlying_to_contracts.values():
            for c in contracts:
                if str(c.get("contract_symbol", "")).strip().upper() == contract_symbol:
                    return c
        return None

    def _remove_contract(self, contract_symbol: str) -> None:
        """Remove a single contract from all indexes."""
        contract_symbol = contract_symbol.strip().upper()
        token = self.contract_to_token.pop(contract_symbol, None)

        # Remove from token_to_contract
        keys_to_remove = [
            k for k, v in self.token_to_contract.items()
            if str(v.get("contract_symbol", "")).strip().upper() == contract_symbol
        ]
        for k in keys_to_remove:
            del self.token_to_contract[k]

        # Remove from underlying_to_contracts
        for underlying, contracts in self.underlying_to_contracts.items():
            self.underlying_to_contracts[underlying] = [
                c for c in contracts
                if str(c.get("contract_symbol", "")).strip().upper() != contract_symbol
            ]

        # Remove empty underlyings
        empty = [u for u, cl in self.underlying_to_contracts.items() if not cl]
        for u in empty:
            del self.underlying_to_contracts[u]

    def _rebuild_expiry_groups(self) -> None:
        """Rebuild expiry_groups from current token_to_contract contents."""
        self.expiry_groups.clear()
        for c in self.token_to_contract.values():
            expiry = str(c.get("expiry_date") or "").strip()
            if expiry:
                self.expiry_groups.setdefault(expiry, []).append(c)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
futures_contract_registry = FuturesContractRegistry()
