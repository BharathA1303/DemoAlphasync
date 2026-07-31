from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, BigInteger, Boolean, DateTime, Index, text
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class BulkFileIndex(Base):
    """Metadata index tracking rotated CSV bulk files on disk for F&O / MCX ticks.
    Allows DelayEngine and Admin Panel to quickly locate tick files for any target timeframe.
    """

    __tablename__ = "bulk_file_index"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    file_path = Column(String(500), nullable=False, unique=True)
    exchange = Column(String(10), nullable=False)        # NFO, BFO, MCX
    segment = Column(String(20), nullable=False)         # contracts, options
    file_date = Column(String(10), nullable=False)       # YYYY-MM-DD
    row_count = Column(Integer, nullable=False, default=0)
    file_size_bytes = Column(BigInteger, nullable=False, default=0)
    start_timestamp = Column(DateTime(timezone=True), nullable=True)
    end_timestamp = Column(DateTime(timezone=True), nullable=True)
    is_compressed = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        Index("ix_bulk_file_lookup", "exchange", "segment", "file_date"),
        Index("ix_bulk_file_timestamps", "start_timestamp", "end_timestamp"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "file_path": self.file_path,
            "exchange": self.exchange,
            "segment": self.segment,
            "file_date": self.file_date,
            "row_count": self.row_count,
            "file_size_bytes": self.file_size_bytes,
            "start_timestamp": self.start_timestamp.isoformat() if self.start_timestamp else None,
            "end_timestamp": self.end_timestamp.isoformat() if self.end_timestamp else None,
            "is_compressed": self.is_compressed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
