# ADR-003: Canonical Symbol Internal Standard

* **Status**: APPROVED
* **Date**: 2026-08-01

## Context
Vendor-specific symbol tokens (e.g. Zerodha `RELIANCE`, Dhan `2885`) leak vendor coupling across internal trading, risk, and strategy services.

## Decision
All internal domains strictly use `CanonicalSymbol` (format: `{EXCHANGE}:{SEGMENT}:{TICKER}`). Vendor translation is isolated inside data provider adapters.

## Consequences
- Decouples internal trading and strategy logic from vendor symbol schemas.
- Simplifies multi-exchange tracking.
