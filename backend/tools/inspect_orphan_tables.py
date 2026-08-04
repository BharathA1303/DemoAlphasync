import sys, os
sys.path.insert(0, os.path.abspath("."))
import asyncio
from sqlalchemy import inspect
from database.connection import engine, Base
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
import strategies.zeroloss.models

def get_tables(sync_conn):
    return set(inspect(sync_conn).get_table_names())

async def main():
    async with engine.begin() as conn:
        db_tables = await conn.run_sync(get_tables)
    model_tables = set(Base.metadata.tables.keys())
    
    orphan_tables = db_tables - model_tables
    print(f"Discovered {len(orphan_tables)} orphan table(s) in DB:")
    for tbl in sorted(orphan_tables):
        print(f"  - {tbl}")

if __name__ == "__main__":
    asyncio.run(main())
