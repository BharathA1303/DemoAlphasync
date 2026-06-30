import asyncio
import datetime
import json
import os
import sqlite3

import asyncpg


ORDER = [
    "users",
    "admin_totp_secrets",
    "admin_sessions",
    "admin_audit_log",
    "email_notifications_log",
    "user_sessions",
    "broker_accounts",
    "portfolios",
    "holdings",
    "orders",
    "transactions",
    "watchlists",
    "watchlist_items",
    "algo_strategies",
    "algo_trades",
    "algo_logs",
    "futures_positions",
    "futures_orders",
    "zeroloss_runtime_state",
    "zeroloss_performance",
    "zeroloss_signals",
]


def qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def to_bool(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "t", "true", "yes", "y")
    return bool(value)


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def normalize_temporal(value, pg_udt_name: str):
    if value is None:
        return None
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return None

    normalized = text.replace("Z", "+00:00")

    try:
        if pg_udt_name in ("timestamp", "timestamptz"):
            return datetime.datetime.fromisoformat(normalized)
        if pg_udt_name == "date":
            return datetime.date.fromisoformat(normalized[:10])
        if pg_udt_name in ("time", "timetz"):
            return datetime.time.fromisoformat(normalized)
    except Exception:
        return value

    return value


def normalize_json(value):
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            return json.dumps(parsed)
        except Exception:
            return json.dumps(value)
    if isinstance(value, (dict, list, tuple, bool, int, float)):
        return json.dumps(value)
    return json.dumps(str(value))


async def main():
    sqlite_path = require_env("SQLITE_PATH")
    if not os.path.exists(sqlite_path):
        raise RuntimeError(f"SQLite file not found: {sqlite_path}")

    sq = sqlite3.connect(sqlite_path)
    pg = await asyncpg.connect(
        user=require_env("PGUSER"),
        password=require_env("PGPASSWORD"),
        database=require_env("PGDATABASE"),
        host=require_env("PGHOST"),
        port=int(require_env("PGPORT")),
    )

    try:
        sqlite_tables = [
            r[0]
            for r in sq.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        pg_tables = {
            r["table_name"]
            for r in await pg.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
        }

        tables = [t for t in ORDER if t in sqlite_tables and t in pg_tables]
        tables += [t for t in sqlite_tables if t in pg_tables and t not in tables]

        await pg.execute("SET session_replication_role = replica;")

        for table in tables:
            col_rows = await pg.fetch(
                "SELECT column_name, udt_name FROM information_schema.columns WHERE table_schema='public' AND table_name=$1 ORDER BY ordinal_position",
                table,
            )
            pg_types = {r["column_name"]: r["udt_name"] for r in col_rows}
            pg_cols = [r["column_name"] for r in col_rows]

            sq_cols = [
                r[1] for r in sq.execute(f"PRAGMA table_info({qi(table)})").fetchall()
            ]
            cols = [c for c in sq_cols if c in pg_cols]
            if not cols:
                print(f"{table}: skip (no common columns)")
                continue

            await pg.execute(f"TRUNCATE TABLE {qi(table)} RESTART IDENTITY CASCADE;")

            query = f"SELECT {', '.join(qi(c) for c in cols)} FROM {qi(table)}"
            cur = sq.execute(query)

            stmt = (
                f"INSERT INTO {qi(table)} ({', '.join(qi(c) for c in cols)}) "
                f"VALUES ({', '.join(f'${i}' for i in range(1, len(cols) + 1))})"
            )

            moved = 0
            while True:
                chunk = cur.fetchmany(1000)
                if not chunk:
                    break

                out = []
                for row in chunk:
                    values = []
                    for col_name, raw in zip(cols, row):
                        typ = pg_types[col_name]
                        if typ == "bool":
                            values.append(to_bool(raw))
                        elif typ in ("timestamp", "timestamptz", "date", "time", "timetz"):
                            values.append(normalize_temporal(raw, typ))
                        elif typ in ("json", "jsonb"):
                            values.append(normalize_json(raw))
                        else:
                            values.append(raw)
                    out.append(tuple(values))

                await pg.executemany(stmt, out)
                moved += len(out)

            print(f"{table}: migrated {moved} rows")

        await pg.execute("SET session_replication_role = origin;")
        print("Data migration completed.")
    finally:
        await pg.close()
        sq.close()


if __name__ == "__main__":
    asyncio.run(main())