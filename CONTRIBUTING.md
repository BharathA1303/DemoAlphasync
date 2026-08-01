# AlphaSync Academy Engineering Standards & Guidelines

**Architecture Version**: v1.0 (Frozen)

## 1. Architectural Layering Rule
Dependencies flow strictly in **ONE** direction:

`Kernel` ← `Domain` ← `Application` ← `API / Adapters`

No domain may import code from another domain's internal packages. All inter-domain communication occurs via Kernel value objects, Commands, and Events.

---

## 2. Five Inviolable Engineering Rules
1. **Never bypass the buses**: All state mutations must use `CommandBus`; all side-effects must use `EventBus`.
2. **No internal domain cross-imports**: Domains communicate strictly via Kernel primitives or domain events.
3. **One Aggregate = One Transaction**: Aggregate boundaries strictly enforce transactional consistency.
4. **Never publish inside aggregates**: Aggregates collect typed events in `self._uncommitted_events`; `UnitOfWork` publishes after DB commit.
5. **Zero Primitive Obsession**: Always use typed Kernel objects (`Price`, `Quantity`, `Money`, `CanonicalSymbol`, strongly-typed `ID`s).

---

## 3. Logging & Testing Guidelines
- Every command, event, and log entry **MUST** carry a `correlation_id` and `session_id`.
- Critical domain aggregates (`OrderAggregate`, `RiskEngine`, `PortfolioAggregate`, `PositionAggregate`, `FillPolicy`) **MUST** maintain 100% unit test coverage.

---

## 4. Architectural Decision Records (ADRs)
No architectural boundary may be altered without an approved **Architecture Decision Record (ADR)** committed under `docs/architecture/adr/`.
