"""SQLAlchemy-backed IOutboxRepository implementation.

Table name (per the "same public schema, new table names" decision for
this rewrite) is `outbox_messages` — distinct from any legacy table.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.transactional_outbox.models import OutboxMessage, OutboxStatus

metadata = MetaData()

outbox_table = Table(
    "outbox_messages",
    metadata,
    Column("outbox_id", String(40), primary_key=True),
    Column("event_type", String(200), nullable=False, index=True),
    Column("event_id", String(40), nullable=False),
    Column("correlation_id", String(40), nullable=False, index=True),
    Column("payload", Text, nullable=False),
    Column("status", String(20), nullable=False, default=OutboxStatus.PENDING.value, index=True),
    Column("created_at_utc", DateTime(timezone=True), nullable=False),
    Column("published_at_utc", DateTime(timezone=True), nullable=True),
    Column("attempts", Integer, nullable=False, default=0),
    Column("last_error", Text, nullable=True),
)


def _row_to_message(row: object) -> OutboxMessage:
    return OutboxMessage(
        outbox_id=row.outbox_id,  # type: ignore[attr-defined]
        event_type=row.event_type,  # type: ignore[attr-defined]
        event_id=row.event_id,  # type: ignore[attr-defined]
        correlation_id=row.correlation_id,  # type: ignore[attr-defined]
        payload=row.payload,  # type: ignore[attr-defined]
        status=OutboxStatus(row.status),  # type: ignore[attr-defined]
        created_at_utc=row.created_at_utc,  # type: ignore[attr-defined]
        published_at_utc=row.published_at_utc,  # type: ignore[attr-defined]
        attempts=row.attempts,  # type: ignore[attr-defined]
        last_error=row.last_error,  # type: ignore[attr-defined]
    )


class SqlAlchemyOutboxRepository:
    """Outbox repository bound to a single AsyncSession.

    `add()` MUST be called using the same AsyncSession as the UnitOfWork
    that owns the surrounding transaction — the caller is responsible for
    handing this repository the correct session (see
    `unit_of_work.SqlAlchemyUnitOfWork`), so the outbox insert and the
    aggregate's own row changes commit or roll back together.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, message: OutboxMessage) -> None:
        await self._session.execute(
            outbox_table.insert().values(
                outbox_id=message.outbox_id,
                event_type=message.event_type,
                event_id=message.event_id,
                correlation_id=message.correlation_id,
                payload=message.payload,
                status=message.status.value,
                created_at_utc=message.created_at_utc,
                published_at_utc=message.published_at_utc,
                attempts=message.attempts,
                last_error=message.last_error,
            )
        )

    async def fetch_pending(self, limit: int = 100) -> list[OutboxMessage]:
        stmt = (
            select(outbox_table)
            .where(outbox_table.c.status == OutboxStatus.PENDING.value)
            .order_by(outbox_table.c.created_at_utc.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [_row_to_message(row) for row in result.fetchall()]

    async def mark_published(self, outbox_id: str) -> None:
        await self._session.execute(
            update(outbox_table)
            .where(outbox_table.c.outbox_id == outbox_id)
            .values(
                status=OutboxStatus.PUBLISHED.value,
                published_at_utc=datetime.now(timezone.utc),
                attempts=outbox_table.c.attempts + 1,
            )
        )
        await self._session.commit()

    async def mark_failed(self, outbox_id: str, error: str) -> None:
        await self._session.execute(
            update(outbox_table)
            .where(outbox_table.c.outbox_id == outbox_id)
            .values(
                status=OutboxStatus.FAILED.value,
                attempts=outbox_table.c.attempts + 1,
                last_error=error[:2000],
            )
        )
        await self._session.commit()
