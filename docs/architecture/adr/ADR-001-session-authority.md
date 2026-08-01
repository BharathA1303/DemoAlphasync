# ADR-001: Session as Single Authority for Execution Environment

* **Status**: APPROVED
* **Date**: 2026-08-01

## Context
Previously, commands carried duplicated `execution_mode` flags (e.g. `LIVE`, `PAPER`, `REPLAY`), creating state ambiguity if the session environment differed from the command flag.

## Decision
`session_id` is the single source of truth for runtime context (`LIVE`, `PAPER`, `REPLAY`, `BACKTEST`). Commands carry `session_id`; execution adapters query `Session Domain` to determine behavior.

## Consequences
- Prevents state duplication and execution mode mismatches.
- Simplifies command payloads.
