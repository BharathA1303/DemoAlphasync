from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.kernel.ids.generator import default_id_generator


@dataclass(frozen=True)
class Command:
    """Base immutable CQS Command primitive."""

    command_id: str = field(default_factory=lambda: default_id_generator.generate("cmd"))
    version: int = 1
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str = field(default_factory=lambda: default_id_generator.generate("corr"))
    idempotency_key: str = field(default_factory=lambda: default_id_generator.generate("idem"))
