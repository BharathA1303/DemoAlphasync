# ADR-002: Strict Separation of Commands (CQS) and Events (Pub/Sub)

* **Status**: APPROVED
* **Date**: 2026-08-01

## Context
Using a single event bus for both point-to-point intent dispatching and pub/sub fact broadcasting causes race conditions, feedback loops, and tight coupling.

## Decision
Introduce a point-to-point `CommandBus` (one handler per command, representing an intent to mutate state) and an async `EventBus` (pub/sub fan-out to N subscribers, announcing immutable facts).

## Consequences
- Eliminates circular command-event loops.
- Provides predictable, single-handler command dispatching.
