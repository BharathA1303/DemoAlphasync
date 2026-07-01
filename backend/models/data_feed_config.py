# models/data_feed_config.py - Database model for managing live AMDP data feed configuration
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Text, text
from sqlalchemy.dialects.postgresql import UUID
from database.connection import Base


def _utcnow():
    return datetime.now(timezone.utc)


class DataFeedConfig(Base):
    __tablename__ = "data_feed_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    api_key = Column(String(255), nullable=True)
    api_secret = Column(String(255), nullable=True)
    base_url = Column(String(500), nullable=True, default="http://localhost:3000/api/v1")
    is_enabled = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    connection_status = Column(String(50), default="disconnected")  # disconnected, connecting, connected, error
    error_message = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=text("CURRENT_TIMESTAMP"))
