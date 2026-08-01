import time
import uuid
from typing import Protocol


class IIdentifierGenerator(Protocol):
    def generate(self, prefix: str = "") -> str:
        ...


class UUIDv7Generator:
    """Time-sortable UUIDv7 ID generator."""

    def generate(self, prefix: str = "") -> str:
        timestamp_ms = int(time.time() * 1000)
        rand_a = uuid.uuid4().int & 0xFFF
        rand_b = uuid.uuid4().int & 0x3FFFFFFFFFFFFFFF

        uuid_int = (
            (timestamp_ms << 80)
            | (0x7 << 76)
            | (rand_a << 64)
            | (0x2 << 62)
            | rand_b
        )
        raw_id = str(uuid.UUID(int=uuid_int)).replace("-", "")[:20]
        return f"{prefix}_{raw_id}" if prefix else raw_id


default_id_generator = UUIDv7Generator()
