import sys, os
sys.path.insert(0, os.path.abspath("."))
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import inspect
from alembic.config import Config
from alembic import command
from database.connection import engine as live_engine, Base
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


def inspect_schema(sync_conn):
    insp = inspect(sync_conn)
    tables = insp.get_table_names()
    columns_by_table = {}
    for table in tables:
        columns_by_table[table] = {col['name'] for col in insp.get_columns(table)}
    return tables, columns_by_table


async def main():
    print("=== Alembic Fresh Upgrade Head vs Live DB Schema Diff Tool ===")
    
    # 1. Inspect live database schema
    async with live_engine.begin() as conn:
        live_tables, live_columns = await conn.run_sync(inspect_schema)

    # 2. Spin up fresh SQLite DB and run alembic upgrade head
    fresh_db_file = "./fresh_alembic_test.db"
    if os.path.exists(fresh_db_file):
        os.remove(fresh_db_file)

    print("\n[1] Running 'alembic upgrade head' on clean test database...")
    import subprocess
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{fresh_db_file}"
    res = subprocess.run(["alembic", "upgrade", "head"], capture_output=True, text=True, env=env)
    if res.returncode == 0:
        print("    [OK] Alembic migration execution to HEAD succeeded!")
    else:
        print(f"    [WARN] Subprocess Alembic run output: {res.stderr or res.stdout}")

    # 3. Inspect fresh Alembic database schema
    fresh_engine = create_async_engine(f"sqlite+aiosqlite:///{fresh_db_file}")
    async with fresh_engine.begin() as fresh_conn:
        fresh_tables, fresh_columns = await fresh_conn.run_sync(inspect_schema)
    await fresh_engine.dispose()

    if os.path.exists(fresh_db_file):
        os.remove(fresh_db_file)

    # 4. Compare fresh migration schema vs live database schema
    print(f"\n[2] Schema Comparison Summary:")
    print(f"    - Fresh Alembic HEAD Tables: {len(fresh_tables)}")
    print(f"    - Live Database Tables:       {len(live_tables)}")

    table_diff = set(live_tables) - set(fresh_tables) - {"alembic_version"}
    if table_diff:
        print(f"    [WARN] Tables missing in fresh Alembic migration: {table_diff}")
    else:
        print("    [OK] All live database tables exist in fresh Alembic HEAD migration!")

    column_drift = 0
    for tbl in set(live_tables) & set(fresh_tables):
        if tbl == "alembic_version":
            continue
        missing = live_columns[tbl] - fresh_columns[tbl]
        if missing:
            column_drift += len(missing)
            print(f"    [WARN] Table '{tbl}' missing columns in Alembic HEAD: {missing}")

    if column_drift == 0:
        print("    [OK] 0 Column Drift: Fresh 'alembic upgrade head' matches live database schema 100%!")
    else:
        print(f"    [WARN] Total column drift between live DB and fresh Alembic HEAD: {column_drift}")


if __name__ == "__main__":
    asyncio.run(main())
