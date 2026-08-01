import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.kernel.primitives import DomainEvent
from app.shared.event_bus import EventBus
from app.shared.transactional_outbox import (
    OutboxRelay,
    OutboxStatus,
    SqlAlchemyOutboxRepository,
    build_outbox_message,
    outbox_table,
    serialize_event,
)
from app.shared.transactional_outbox.models import OutboxMessage


@dataclass(frozen=True)
class _OrderPlacedEvent(DomainEvent):
    order_id: str = ""


@dataclass(frozen=True)
class _OrderFilledEvent(DomainEvent):
    order_id: str = ""
    fill_price: Decimal = Decimal("0")


@pytest.fixture
async def sqlite_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(outbox_table.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


class TestSerializeEvent:
    def test_round_trips_through_json(self) -> None:
        event = _OrderPlacedEvent(order_id="ord_1")
        payload = json.loads(serialize_event(event))
        assert payload["order_id"] == "ord_1"
        assert payload["event_id"] == event.event_id
        assert payload["correlation_id"] == event.correlation_id

    def test_decimal_fields_serialize_as_strings(self) -> None:
        """Decimal isn't natively JSON-serializable and str(Decimal(...))
        preserves exact precision (unlike float), which matters for
        monetary fields like a fill price."""
        event = _OrderFilledEvent(order_id="ord_1", fill_price=Decimal("100.25"))
        payload = json.loads(serialize_event(event))
        assert payload["fill_price"] == "100.25"

    def test_unserializable_field_raises_type_error(self) -> None:
        @dataclass(frozen=True)
        class _EventWithUnserializableField(DomainEvent):
            handle: object = object()

        with pytest.raises(TypeError, match="not JSON serializable"):
            serialize_event(_EventWithUnserializableField())


class TestBuildOutboxMessage:
    def test_produces_pending_message_matching_the_event(self) -> None:
        event = _OrderPlacedEvent(order_id="ord_1")
        message = build_outbox_message(event)

        assert message.status == OutboxStatus.PENDING
        assert message.event_type == "_OrderPlacedEvent"
        assert message.event_id == event.event_id
        assert message.correlation_id == event.correlation_id
        assert json.loads(message.payload)["order_id"] == "ord_1"


class TestSqlAlchemyOutboxRepository:
    async def test_add_then_fetch_pending_returns_the_message(self, sqlite_session: AsyncSession) -> None:
        repo = SqlAlchemyOutboxRepository(sqlite_session)
        message = build_outbox_message(_OrderPlacedEvent(order_id="ord_1"))

        await repo.add(message)
        await sqlite_session.commit()

        pending = await repo.fetch_pending()
        assert len(pending) == 1
        assert pending[0].outbox_id == message.outbox_id
        assert pending[0].status == OutboxStatus.PENDING

    async def test_mark_published_removes_it_from_pending(self, sqlite_session: AsyncSession) -> None:
        repo = SqlAlchemyOutboxRepository(sqlite_session)
        message = build_outbox_message(_OrderPlacedEvent(order_id="ord_1"))
        await repo.add(message)
        await sqlite_session.commit()

        await repo.mark_published(message.outbox_id)

        assert await repo.fetch_pending() == []

    async def test_mark_failed_records_the_error_and_removes_from_pending(
        self, sqlite_session: AsyncSession
    ) -> None:
        repo = SqlAlchemyOutboxRepository(sqlite_session)
        message = build_outbox_message(_OrderPlacedEvent(order_id="ord_1"))
        await repo.add(message)
        await sqlite_session.commit()

        await repo.mark_failed(message.outbox_id, "boom")

        assert await repo.fetch_pending() == []

    async def test_fetch_pending_respects_limit(self, sqlite_session: AsyncSession) -> None:
        repo = SqlAlchemyOutboxRepository(sqlite_session)
        for i in range(5):
            await repo.add(build_outbox_message(_OrderPlacedEvent(order_id=f"ord_{i}")))
        await sqlite_session.commit()

        pending = await repo.fetch_pending(limit=2)
        assert len(pending) == 2


class TestOutboxMessageModel:
    def test_pending_factory_sets_pending_status(self) -> None:
        message = OutboxMessage.pending(
            outbox_id="obx_1", event_type="X", event_id="evt_1", correlation_id="corr_1", payload="{}"
        )
        assert message.status == OutboxStatus.PENDING
        assert message.attempts == 0

    def test_mark_published_returns_new_instance_with_published_status(self) -> None:
        pending = OutboxMessage.pending(
            outbox_id="obx_1", event_type="X", event_id="evt_1", correlation_id="corr_1", payload="{}"
        )
        published = pending.mark_published()

        assert published.status == OutboxStatus.PUBLISHED
        assert published.published_at_utc is not None
        assert published.attempts == 1
        # Original is untouched (immutable value object).
        assert pending.status == OutboxStatus.PENDING

    def test_mark_failed_records_truncated_error(self) -> None:
        pending = OutboxMessage.pending(
            outbox_id="obx_1", event_type="X", event_id="evt_1", correlation_id="corr_1", payload="{}"
        )
        failed = pending.mark_failed("x" * 3000)

        assert failed.status == OutboxStatus.FAILED
        assert failed.last_error is not None
        assert len(failed.last_error) == 2000


class TestOutboxRelay:
    async def test_relay_once_publishes_pending_messages_and_marks_them_published(
        self, sqlite_session: AsyncSession
    ) -> None:
        repo = SqlAlchemyOutboxRepository(sqlite_session)
        bus = EventBus()
        received: list[str] = []

        async def on_placed(event: _OrderPlacedEvent) -> None:
            received.append(event.order_id)

        bus.subscribe(_OrderPlacedEvent, on_placed)

        message = build_outbox_message(_OrderPlacedEvent(order_id="ord_1"))
        await repo.add(message)
        await sqlite_session.commit()

        relay = OutboxRelay(repo, bus)
        relay.register_event_type(_OrderPlacedEvent)
        relayed_count = await relay.relay_once()

        assert relayed_count == 1
        assert received == ["ord_1"]
        assert await repo.fetch_pending() == []

    async def test_relay_once_with_unregistered_event_type_marks_failed_not_published(
        self, sqlite_session: AsyncSession
    ) -> None:
        repo = SqlAlchemyOutboxRepository(sqlite_session)
        bus = EventBus()

        message = build_outbox_message(_OrderPlacedEvent(order_id="ord_1"))
        await repo.add(message)
        await sqlite_session.commit()

        relay = OutboxRelay(repo, bus)  # deliberately NOT registered
        relayed_count = await relay.relay_once()

        assert relayed_count == 0
        assert await repo.fetch_pending() == []

    async def test_relay_once_with_no_pending_messages_returns_zero(
        self, sqlite_session: AsyncSession
    ) -> None:
        repo = SqlAlchemyOutboxRepository(sqlite_session)
        bus = EventBus()
        relay = OutboxRelay(repo, bus)

        assert await relay.relay_once() == 0

    async def test_relay_once_with_malformed_payload_marks_failed_not_published(
        self, sqlite_session: AsyncSession
    ) -> None:
        """A payload that no longer matches the registered event type's
        constructor (e.g. a stored field was renamed/removed since the row
        was written) must not crash the relay loop — it should be recorded
        as FAILED so it's visible for investigation, and the loop should
        continue to the next message."""
        repo = SqlAlchemyOutboxRepository(sqlite_session)
        bus = EventBus()

        message = OutboxMessage.pending(
            outbox_id="obx_bad",
            event_type="_OrderPlacedEvent",
            event_id="evt_1",
            correlation_id="corr_1",
            payload=json.dumps({"unexpected_field": "boom"}),
        )
        await repo.add(message)
        await sqlite_session.commit()

        relay = OutboxRelay(repo, bus)
        relay.register_event_type(_OrderPlacedEvent)

        relayed_count = await relay.relay_once()

        assert relayed_count == 0
        assert await repo.fetch_pending() == []
