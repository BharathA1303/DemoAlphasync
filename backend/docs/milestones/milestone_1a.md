# Milestone 1A — Kernel & Shared Infrastructure

Status: **Complete**. 155 tests passing, 99% branch coverage on `app/kernel`
and `app/shared`, zero `ruff` findings, zero `mypy --strict` findings.

This milestone implements the foundation every later milestone builds on:
the pure kernel (no dependencies on anything outside itself) and the shared
cross-cutting infrastructure (CommandBus, EventBus, UnitOfWork,
Transactional Outbox, Configuration, Dependency Injection, Logging,
Observability). No domain logic (OMS, Risk, Portfolio, etc.) exists yet —
that begins in Milestone 1B.

## Directory layout delivered

```
backend/app/
  kernel/
    ids/            OrderId, UserId, SessionId, InstrumentId, PortfolioId,
                     PositionId — typed IDs, no primitive obsession.
                     UUIDv7Generator — time-sortable ID generation.
    value_objects/   CanonicalSymbol, Money, Price, Quantity.
    enums/           OrderSide, OrderType, OrderStatus, SessionEnvironment.
    primitives/      Command, DomainEvent, BaseAggregateRoot, Result.
    exceptions/      DomainException and its subtypes.

  shared/
    configuration/   AppSettings (Pydantic v2 BaseSettings), section-scoped
                      (database, redis, data_provider, observability).
    logging/         ContextLogger (contextvars-based correlation/session
                      propagation), JSONFormatter, configure_logging().
    dependency_injection/  Container — explicit, typed, no service locator.
    command_bus/     CommandBus — single-handler point-to-point dispatch.
    event_bus/       EventBus — multi-subscriber pub/sub, returns whether
                      every subscriber succeeded.
    unit_of_work/    InMemoryUnitOfWork (tests only) and
                      SqlAlchemyUnitOfWork (production) — see below.
    transactional_outbox/  OutboxMessage, IOutboxRepository,
                      SqlAlchemyOutboxRepository, OutboxRelay.
    observability/   correlation id extraction/binding, latency budgets.

backend/tests/app/    Mirrors the above 1:1. 155 tests.
backend/pyproject.toml  ruff + mypy(strict) + pytest + coverage config.
backend/requirements-dev.txt  mypy, ruff, pytest, pytest-asyncio, pytest-cov.
```

## Key design decisions and why

### UnitOfWork + Transactional Outbox: single delivery path, no race

Per the frozen architecture: *"UnitOfWork publishes events after commit"*
and *"Aggregates never publish events."* `BaseAggregateRoot._record_event`
only appends to an in-memory list on the aggregate itself — it has no
reference to an `EventBus`, so it is structurally incapable of publishing
(enforced by a test that asserts the aggregate has no `publish`/`event_bus`
attribute at all).

`SqlAlchemyUnitOfWork.commit()` is the sole place that turns those
recorded-but-uncommitted events into durable state:

1. For every registered aggregate, collect its uncommitted events and
   write one `outbox_messages` row per event, using the **same
   `AsyncSession`** as everything else in the transaction.
2. `await self.session.commit()` — the aggregate's own row changes and the
   outbox rows commit or roll back **together**. If this raises, nothing
   is ever published (verified by
   `test_rollback_on_exception_leaves_no_outbox_row_and_publishes_nothing`).
3. Only after that DB commit succeeds, relay each event to the `EventBus`
   in-process, and mark its outbox row `PUBLISHED` (all subscribers
   succeeded) or `FAILED` (`EventBus.publish` reported at least one
   subscriber raised).

This is deliberately **one** delivery path, not two racing ones. An
earlier draft had `commit()` relay events but never mark the outbox rows
published, which would leave `outbox_messages` permanently full of
already-delivered rows and, if a separate always-on `OutboxRelay` also
polled for `PENDING` rows, double-publish everything `commit()` already
delivered. The fix: `commit()` owns delivery end-to-end; `OutboxRelay`
exists only as a crash-recovery tool for the narrow window between "DB
commit succeeded" and "mark-published ran" if the process dies in between
— it is not meant to run continuously in steady state.

`InMemoryUnitOfWork` exists purely for fast, isolated unit tests of
handlers/aggregates — it has no real transaction and no outbox, so it must
never be used for anything that needs a durability guarantee.

### EventBus.publish() returns success, doesn't raise

`EventBus.publish` runs every subscriber via
`asyncio.gather(..., return_exceptions=True)`, so one broken consumer
(e.g. a down Streaming Gateway) never blocks delivery to healthy ones
(e.g. Portfolio recalculation). It returns `bool` — `True` only if every
subscriber completed without raising — so a caller with its own
delivery-tracking concern (`SqlAlchemyUnitOfWork.commit()`) can tell
success from partial failure without `publish()` itself raising and
without re-implementing per-handler exception bookkeeping.

### Dependency Injection: explicit container, not a service locator

`Container` requires the caller to name an exact `Type[T]` and register it
explicitly — either as a shared `register_instance` (constructed once) or
a per-call `register_factory`. There is no module-level container
instance anywhere in `app/shared/dependency_injection` (enforced by
`test_no_module_level_global_container_exists`, which scans the module for
any `Container` instance and fails if one is found). The composition root
(arriving in Milestone 1C's app factory) will construct exactly one
`Container`, register every dependency, and pass it down explicitly —
nothing reaches into a global to resolve a dependency implicitly.

### Configuration: typed, validated, constructed once

`AppSettings` composes section-specific `BaseSettings` subclasses
(`DatabaseSettings`, `RedisSettings`, `DataProviderSettings`,
`ObservabilitySettings`), each reading its own env-var prefix
(`ALPHASYNC_DB_*`, `ALPHASYNC_REDIS_*`, etc.). `DatabaseSettings` validates
the DSN scheme is `postgresql+asyncpg` — the only driver compatible with
async SQLAlchemy 2 — and rejects anything else at construction time rather
than failing confusingly later at connection time.

`load_settings()` uses `functools.lru_cache` as a single, deliberate,
documented exception to "no global state": configuration is genuinely
immutable for the process lifetime, read once, never mutated. It is not a
service locator (nothing is resolved by type from a hidden registry) and
tests that need different settings construct `AppSettings(...)` directly,
bypassing the cache entirely.

### Observability: correlation propagation + latency budgets

`shared/logging` owns *context* (contextvars holding `correlation_id`/
`session_id`, consumed by `JSONFormatter` so every log line carries them
automatically). `shared/observability` owns *transport* — extracting a
correlation id from an inbound boundary (e.g. an HTTP header) or minting a
new one, then binding it into the logging context — plus latency
measurement against the frozen non-functional requirements:
`API_LATENCY_BUDGET` (50ms) and `PAPER_ORDER_LATENCY_BUDGET` (10ms). This
split matches the spec's directory listing, which separates `logging/`
from `observability/`.

## Divergences from the initial scaffold, and why

Some `app/kernel` and `app/shared` scaffolding pre-existed this milestone
(from earlier work not part of this conversation). It was reviewed in full
against the frozen spec rather than assumed correct or discarded
wholesale:

- **Kept as-is**: `kernel/ids`, `kernel/value_objects`, `kernel/enums`,
  `kernel/primitives`, `kernel/exceptions`, `shared/command_bus`,
  `shared/event_bus` (before the `publish()` return-value change above),
  `shared/logging`. All matched spec intent and needed no changes beyond
  ruff/mypy cleanup.
- **`shared/uow/` renamed to `shared/unit_of_work/`**: the spec's directory
  list names it `unit_of_work`; the pre-existing folder was `uow`.
- **`SqlAlchemyUnitOfWork` added**: the pre-existing `UnitOfWork` was
  in-memory only — it published events immediately with no real database
  transaction or outbox table behind it, which cannot satisfy "UnitOfWork
  publishes events after commit" against a real database (there was no
  "commit" to be after). It's kept as `InMemoryUnitOfWork` for fast unit
  tests; `SqlAlchemyUnitOfWork` is the production implementation described
  above.
- **`shared/transactional_outbox/` added in full**: the spec lists it as
  its own directory alongside `unit_of_work`; it did not exist before this
  milestone.

## Non-functional requirements status

| Requirement | Status |
|---|---|
| Every log carries `correlation_id`, `session_id` | Done — `ContextLogger` + `JSONFormatter`, tested. |
| Every command is typed | Done — `Command` is a frozen dataclass; concrete commands subclass it. |
| Every event is immutable | Done — `DomainEvent` is `frozen=True`; enforced by tests attempting mutation. |
| Domain layer 100% coverage on critical aggregates | N/A yet — no aggregates exist until Milestone 1B. `app/kernel` + `app/shared` are at 99% branch coverage (one coverage-tool artifact on an already-exercised line; see `tests/app`). |
| API latency < 50ms / paper order < 10ms | Instrumentation (`measure_latency`, `API_LATENCY_BUDGET`, `PAPER_ORDER_LATENCY_BUDGET`) is in place; nothing to measure yet until Milestone 1B/1C add real request paths. |

## How to run

```bash
cd backend
pip install -r requirements-dev.txt

ruff check app/kernel app/shared tests/app
mypy app/kernel app/shared tests/app
pytest tests/app --cov=app.kernel --cov=app.shared --cov-report=term-missing
```

## What's deliberately NOT in this milestone

- No `control_plane/*` or `runtime_plane/*` domains — those begin in
  Milestone 1B (Session, OMS, Risk, Paper Execution, Position, Portfolio).
- No REST API, no WebSocket gateway — Milestone 1C.
- No MYNT adapter, no replay engine — Milestone 2.
- No FastAPI app factory / composition root wiring the `Container` to real
  dependencies yet — that lands alongside the first real aggregate in 1B,
  once there is something to wire.
