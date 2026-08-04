"""Initial schema: create all base tables from SQLAlchemy metadata.

This migration is the root of the chain (down_revision = None).
It imports all models and calls Base.metadata.create_all() so every
table is created with the exact columns that the ORM models define.
No column drift is possible with this approach.

Revision ID: 000_initial_schema
Revises:
Create Date: 2026-08-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "000_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Enable uuid-ossp extension for gen_random_uuid()
    bind.execute(sa.text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))

    # Import ALL models so Base.metadata is populated with every table
    # Order matters: import base models before dependent ones
    from database.connection import Base  # noqa

    # Core models
    from models import tenant          # noqa — Tenant, UserTenantRole
    from models import user            # noqa — User, UserSession, AdminAuditLog, EmailNotificationLog
    from models import portfolio       # noqa — Portfolio, Holding, Transaction
    from models import order           # noqa — Order
    from models import watchlist       # noqa — Watchlist, WatchlistItem
    from models import algo            # noqa — AlgoStrategy, AlgoTrade, AlgoLog
    from models import futures_order   # noqa — FuturesOrder
    from models import futures_watchlist  # noqa — FuturesWatchlist, FuturesWatchlistItem
    from models import historical_ticks   # noqa
    from models.data_feed_config import DataFeedConfig   # noqa
    from models.symbol_master import SymbolMaster        # noqa
    from models.raw_ticks import RawTick                 # noqa
    from models.bulk_file_index import BulkFileIndex     # noqa
    from models import academy as academy_models          # noqa — Academy LMS tables
    from strategies.zeroloss import models as zeroloss_models  # noqa
    from data_layer.db.models import PriceData, APIKey, IngestionLog  # noqa

    # Create all tables that don't exist yet — idempotent, skips existing ones
    Base.metadata.create_all(bind=bind.engine.sync_engine)


def downgrade() -> None:
    # Import all models to get the full metadata
    from database.connection import Base  # noqa
    from models import tenant, user, portfolio, order, watchlist, algo  # noqa
    from models import futures_order, futures_watchlist, historical_ticks  # noqa
    from models.data_feed_config import DataFeedConfig  # noqa
    from models.symbol_master import SymbolMaster  # noqa
    from models.raw_ticks import RawTick  # noqa
    from models.bulk_file_index import BulkFileIndex  # noqa
    from models import academy as academy_models  # noqa
    from strategies.zeroloss import models as zeroloss_models  # noqa

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind.engine.sync_engine)
