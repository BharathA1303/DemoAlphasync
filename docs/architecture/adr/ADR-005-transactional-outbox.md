# ADR-005: Transactional Outbox Pattern for Domain Events

* **Status**: APPROVED
* **Date**: 2026-08-01

## Context
Publishing an event directly to a message bus after database commit can fail if the application process crashes between the DB commit and event publish call, leading to lost events or inconsistent downstream states.

## Decision
Write domain events to an `Outbox` table within the exact same database transaction as aggregate state mutations. An `OutboxWorker` asynchronously polls and publishes events to the EventBus.

## Consequences
- Guarantees at-least-once event delivery.
- Enforces transactional consistency between database mutations and published domain events.
