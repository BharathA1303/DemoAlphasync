from dataclasses import dataclass, field
from datetime import datetime, timezone
from app.kernel.ids.generator import default_id_generator


@dataclass(frozen=True)
class DomainEvent:
    """Base immutable Domain Event primitive."""

    event_id: str = field(default_factory=lambda: default_id_generator.generate("evt"))
    version: int = 1
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str = field(default_factory=lambda: default_id_generator.generate("corr"))
    idempotency_key: str = field(default_factory=lambda: default_id_generator.generate("idem"))
