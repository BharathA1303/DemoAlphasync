# ADR-004: Hot Path vs. Cold Path Storage Isolation

* **Status**: APPROVED
* **Date**: 2026-08-01

## Context
Synchronous database disk IO during tick ingestion creates latency bottlenecks for real-time strategy evaluation and WebSocket streaming.

## Decision
Split data pipeline into **Hot Path** (In-memory SmartCache, strategies, paper execution, streaming gateway — zero disk wait) and **Cold Path** (async Data Recorder writing to TimescaleDB / Parquet for historical archives and compliance logging).

## Consequences
- Sub-microsecond price stream processing.
- Zero disk IO contention on live tick feeds.
