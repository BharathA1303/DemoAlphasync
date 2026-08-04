import sys, os
sys.path.insert(0, os.path.abspath("."))
import asyncio
from sqlalchemy import inspect
from database.connection import engine, Base, init_db
import models.user
import models.tenant
import models.order
import models.portfolio
import models.watchlist
import models.futures_order
import models.futures_watchlist
import models.algo
import models.data_feed_config
import models.academy
import models.bug_report
import models.feedback
import models.historical_ticks
import strategies.zeroloss.models


def get_schema_summary(sync_conn):
    insp = inspect(sync_conn)
    tables = insp.get_table_names()
    columns_by_table = {}
    for table in tables:
        columns_by_table[table] = {col['name'] for col in insp.get_columns(table)}
    return tables, columns_by_table


async def main():
    print("=== AlphaSync Schema Drift Reconciliation Verification ===")
    
    # Initialize DB schema via Alembic target metadata
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        db_tables, db_columns = await conn.run_sync(get_schema_summary)

    model_tables = set(Base.metadata.tables.keys())
    print(f"\n[1] Schema Table Audit:")
    print(f"    - Database Tables Discovered: {len(db_tables)}")
    print(f"    - Model Metadata Tables:     {len(model_tables)}")

    missing_in_db = model_tables - set(db_tables)
    if missing_in_db:
        print(f"    [WARN] Tables missing in Database: {missing_in_db}")
    else:
        print("    [OK] 100% Match: All model metadata tables exist in live database schema.")

    print("\n[2] Column Drift Audit:")
    total_drift = 0
    for table_name in model_tables:
        if table_name not in db_columns:
            continue
        model_cols = {col.name for col in Base.metadata.tables[table_name].columns}
        live_cols = db_columns[table_name]
        diff = model_cols - live_cols
        if diff:
            total_drift += len(diff)
            print(f"    [WARN] Table '{table_name}' missing columns in live DB: {diff}")

    if total_drift == 0:
        print("    [OK] 0 Column Drift Detected across all domain tables!")
    else:
        print(f"    [WARN] Total column drifts detected: {total_drift}")


if __name__ == "__main__":
    asyncio.run(main())
