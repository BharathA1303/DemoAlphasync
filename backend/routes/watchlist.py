from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from pydantic import BaseModel
import uuid
from database.connection import get_db
from models.user import User
from routes.auth import get_current_user


router = APIRouter(prefix="/api/watchlist", tags=["Watchlist"])


class CreateWatchlistRequest(BaseModel):
    name: str = "My Watchlist"


class RenameWatchlistRequest(BaseModel):
    name: str


class AddItemRequest(BaseModel):
    symbol: str
    exchange: str = "NSE"


def _canonical_watchlist_symbol(symbol: str, exchange: str = "NSE") -> str:
    base = (symbol or "").strip().upper()
    if not base:
        return ""
    if base.startswith("^") or base.endswith(".NS") or base.endswith(".BO"):
        return base
    if exchange == "BSE":
        return f"{base}.BO"
    return f"{base}.NS"


# Each entry: (watchlist_name, [symbols...], exchange)
DEFAULT_WATCHLIST_SEEDS = [
    ("Watchlist 1", [], "NSE"),
    ("NIFTY 50", [
        "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
        "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BHARTIARTL", "BPCL",
        "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY",
        "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
        "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
        "INFY", "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK",
        "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC",
        "ONGC", "POWERGRID", "RELIANCE", "SBIN", "SBILIFE",
        "SUNPHARMA", "TATAMOTORS", "TATACONSUM", "TATASTEEL", "TCS",
        "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
    ], "NSE"),
    ("BANKNIFTY", [
        "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN",
        "INDUSINDBK", "BANDHANBNK", "FEDERALBNK", "IDFCFIRSTB", "AUBANK",
        "PNB", "BANKBARODA",
    ], "NSE"),
    ("SENSEX", [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "LT", "SBIN", "ITC", "BHARTIARTL", "AXISBANK",
        "BAJFINANCE", "KOTAKBANK", "HCLTECH", "WIPRO", "MARUTI",
        "SUNPHARMA", "TITAN", "BAJAJFINSV", "POWERGRID", "NTPC",
        "TATASTEEL", "ASIANPAINT", "NESTLEIND", "M&M", "ULTRACEMCO",
        "TATAMOTORS", "TRENT", "ADANIPORTS", "JSWSTEEL", "HDFCLIFE",
    ], "BSE"),
]

DEFAULT_WATCHLIST_NAMES = {name.strip().lower() for name, _, _exch in DEFAULT_WATCHLIST_SEEDS}

# Legacy auto-seeded lists from previous deployments. These are removed on
# next login so users only see Watchlist 1 + the 3 market indices.
LEGACY_DEFAULT_WATCHLIST_NAMES = {
    'my watchlist',
    'bank nifty',
    'nifty it',
    'nifty auto',
    'nifty pharma',
    'nifty fmcg',
    'nifty metal',
    'nifty next 50',
    'india vix',
}


def _default_watchlist_sort_key(name: str) -> tuple[int, str]:
    normalized = str(name or '').strip().lower()
    if normalized == 'watchlist 1':
        return (0, normalized)
    for index, (seed_name, _, _exch) in enumerate(DEFAULT_WATCHLIST_SEEDS, start=1):
        if normalized == seed_name.strip().lower():
            return (index, normalized)
    return (999, normalized)


async def _seed_missing_default_watchlists(db: AsyncSession, user_uuid: uuid.UUID, existing_names: set[str]):
    seeded = []
    for name, symbols, exchange in DEFAULT_WATCHLIST_SEEDS:
        if name.strip().lower() in existing_names:
            continue
        watchlist_id = uuid.uuid4().hex
        await db.execute(
            text(
                """
                INSERT INTO watchlists (id, user_id, name)
                VALUES (:id, :user_id, :name)
                """
            ),
            {
                "id": watchlist_id,
                "user_id": user_uuid.hex,
                "name": name,
            },
        )

        items = []
        for symbol in symbols:
            item_id = uuid.uuid4().hex
            canonical_symbol = _canonical_watchlist_symbol(symbol, exchange)
            await db.execute(
                text(
                    """
                    INSERT INTO watchlist_items (id, watchlist_id, symbol, exchange)
                    VALUES (:id, :watchlist_id, :symbol, :exchange)
                    """
                ),
                {
                    "id": item_id,
                    "watchlist_id": watchlist_id,
                    "symbol": canonical_symbol,
                    "exchange": exchange,
                },
            )
            items.append({"id": item_id, "symbol": canonical_symbol, "exchange": exchange})

        seeded.append({"id": watchlist_id, "name": name, "items": items})

    if seeded:
        await db.commit()
    return seeded


async def _seed_default_watchlists(db: AsyncSession, user_uuid: uuid.UUID):
    return await _seed_missing_default_watchlists(db, user_uuid, set())


async def _repair_default_watchlists(db: AsyncSession, watchlist_rows) -> bool:
    """For existing users: enforce exact default constituents for seeded index watchlists.

    - Inserts missing seed symbols
    - Removes symbols that are not part of the current seed set
    Returns True if any rows were changed.
    """
    changed = False
    for name, symbols, exchange in DEFAULT_WATCHLIST_SEEDS:
        if not symbols:
            continue
        matching_row = next(
            (r for r in watchlist_rows if str(r[1]).strip().lower() == name.strip().lower()),
            None,
        )
        if not matching_row:
            continue
        wl_id = matching_row[0]

        existing_result = await db.execute(
            text("SELECT id, UPPER(symbol) FROM watchlist_items WHERE watchlist_id = :wid"),
            {"wid": wl_id},
        )
        existing_rows = existing_result.fetchall()
        existing_symbols = {row[1] for row in existing_rows}
        desired_symbols = {
            _canonical_watchlist_symbol(symbol, exchange).upper() for symbol in symbols
        }

        # Remove stale / unwanted symbols so default index watchlists stay clean.
        for item_id, existing_symbol in existing_rows:
            if existing_symbol not in desired_symbols:
                await db.execute(
                    text("DELETE FROM watchlist_items WHERE id = :id"),
                    {"id": item_id},
                )
                changed = True

        for symbol in symbols:
            canonical = _canonical_watchlist_symbol(symbol, exchange)
            if canonical.upper() not in existing_symbols:
                item_id = uuid.uuid4().hex
                await db.execute(
                    text(
                        "INSERT INTO watchlist_items (id, watchlist_id, symbol, exchange) "
                        "VALUES (:id, :wid, :symbol, :exchange)"
                    ),
                    {"id": item_id, "wid": wl_id, "symbol": canonical, "exchange": exchange},
                )
                changed = True

    if changed:
        await db.commit()
    return changed


async def _remove_legacy_default_watchlists(db: AsyncSession, user_uuid: uuid.UUID, watchlist_rows):
    legacy_rows = [row for row in watchlist_rows if str(row[1]).strip().lower() in LEGACY_DEFAULT_WATCHLIST_NAMES]
    if not legacy_rows:
        return watchlist_rows

    legacy_ids = [str(row[0]) for row in legacy_rows]
    if legacy_ids:
        id_list = ','.join(f":id{i}" for i in range(len(legacy_ids)))
        params = {f"id{i}": legacy_ids[i] for i in range(len(legacy_ids))}
        params["uid"] = str(user_uuid)
        await db.execute(
            text(f"DELETE FROM watchlist_items WHERE watchlist_id IN ({id_list})"),
            params,
        )
        await db.execute(
            text(f"DELETE FROM watchlists WHERE id IN ({id_list}) AND user_id IN (:uid, :uid_hex)"),
            {**params, "uid_hex": user_uuid.hex},
        )
        await db.commit()

    return [row for row in watchlist_rows if row not in legacy_rows]


def _normalize_uuid(value: str, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")


def _uuid_variants(value: str, field_name: str) -> tuple[str, str]:
    normalized = _normalize_uuid(value, field_name)
    parsed = uuid.UUID(normalized)
    return str(parsed), parsed.hex


@router.get("")
async def get_watchlists(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import logging
    logger = logging.getLogger(__name__)

    try:
        # Support both dashed UUID and hex formats (SQLite stores as CHAR(36),
        # but create_watchlist used .hex format via raw SQL in some versions)
        user_uuid = uuid.UUID(str(user.id))
        user_id_dash = str(user_uuid)       # "550e8400-e29b-41d4-..."
        user_id_hex = user_uuid.hex          # "550e8400e29b41d4..."

        # Query with both formats to handle any stored format
        result = await db.execute(
            text("SELECT id, name, created_at FROM watchlists WHERE user_id IN (:uid_dash, :uid_hex) ORDER BY created_at"),
            {"uid_dash": user_id_dash, "uid_hex": user_id_hex},
        )
        watchlist_rows = result.fetchall()

        existing_names = {str(row[1]).strip().lower() for row in watchlist_rows}

        watchlist_rows = await _remove_legacy_default_watchlists(db, user_uuid, watchlist_rows)
        existing_names = {str(row[1]).strip().lower() for row in watchlist_rows}

        if not watchlist_rows:
            seeded = await _seed_default_watchlists(db, user_uuid)
            return {"watchlists": seeded}

        # Fill in any missing default lists on every load so new market indices appear
        missing_defaults = DEFAULT_WATCHLIST_NAMES.difference(existing_names)
        if missing_defaults:
            await _seed_missing_default_watchlists(db, user_uuid, existing_names)
            result = await db.execute(
                text("SELECT id, name, created_at FROM watchlists WHERE user_id IN (:uid_dash, :uid_hex) ORDER BY created_at"),
                {"uid_dash": user_id_dash, "uid_hex": user_id_hex},
            )
            watchlist_rows = result.fetchall()

        # Repair existing default watchlists that are missing seed symbols (e.g. old partial seeds)
        await _repair_default_watchlists(db, watchlist_rows)

        watchlist_rows = sorted(watchlist_rows, key=lambda row: _default_watchlist_sort_key(row[1]))

        wl_list = []
        for row in watchlist_rows:
            wl_id = row[0]
            wl_name = row[1]
            items_result = await db.execute(
                text("SELECT id, symbol, exchange FROM watchlist_items WHERE watchlist_id = :wid"),
                {"wid": wl_id},
            )
            items = items_result.fetchall()
            wl_list.append(
                {
                    "id": str(wl_id),
                    "name": wl_name,
                    "items": [
                        {"id": str(i[0]), "symbol": i[1], "exchange": i[2]}
                        for i in items
                    ],
                }
            )

        return {"watchlists": wl_list}
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching watchlists for user {user.id}: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {type(e).__name__}")
    except Exception as e:
        logger.error(f"Unexpected error fetching watchlists for user {user.id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Server error: {type(e).__name__}: {e}")


@router.post("")
async def create_watchlist(
    req: CreateWatchlistRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new watchlist — unlimited per user."""
    name = req.name.strip() or "My Watchlist"
    watchlist_id = uuid.uuid4().hex
    user_id = uuid.UUID(_normalize_uuid(str(user.id), "user_id")).hex
    await db.execute(
        text(
            """
            INSERT INTO watchlists (id, user_id, name)
            VALUES (:id, :user_id, :name)
            """
        ),
        {
            "id": watchlist_id,
            "user_id": user_id,
            "name": name,
        },
    )
    await db.commit()
    return {"id": watchlist_id, "name": name, "items": []}


@router.patch("/{watchlist_id}")
async def rename_watchlist(
    watchlist_id: str,
    req: RenameWatchlistRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    watchlist_id_dash, watchlist_id_hex = _uuid_variants(watchlist_id, "watchlist_id")
    user_id_dash, user_id_hex = _uuid_variants(str(user.id), "user_id")

    wl_result = await db.execute(
        text(
            """
            SELECT id
            FROM watchlists
            WHERE id IN (:wid_dash, :wid_hex)
              AND user_id IN (:uid_dash, :uid_hex)
            LIMIT 1
            """
        ),
        {
            "wid_dash": watchlist_id_dash,
            "wid_hex": watchlist_id_hex,
            "uid_dash": user_id_dash,
            "uid_hex": user_id_hex,
        },
    )
    wl_row = wl_result.first()
    if not wl_row:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    db_watchlist_id = wl_row[0]
    await db.execute(
        text("UPDATE watchlists SET name = :name WHERE id = :watchlist_id"),
        {"name": name, "watchlist_id": db_watchlist_id},
    )
    await db.commit()
    return {"id": str(db_watchlist_id), "name": name}


@router.post("/{watchlist_id}/items")
async def add_item(
    watchlist_id: str,
    req: AddItemRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    watchlist_uuid = uuid.UUID(_normalize_uuid(watchlist_id, "watchlist_id"))
    user_uuid = uuid.UUID(_normalize_uuid(str(user.id), "user_id"))

    watchlist_id_dash = str(watchlist_uuid)
    watchlist_id_hex = watchlist_uuid.hex
    user_id_dash = str(user_uuid)
    user_id_hex = user_uuid.hex

    symbol = (req.symbol or "").strip().upper()
    exchange = (req.exchange or "NSE").strip().upper()

    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")

    if exchange != "MCX":
        symbol = _canonical_watchlist_symbol(symbol)

    try:
        wl_result = await db.execute(
            text(
                """
                SELECT id
                FROM watchlists
                WHERE id IN (:wid_dash, :wid_hex)
                  AND user_id IN (:uid_dash, :uid_hex)
                LIMIT 1
                """
            ),
            {
                "wid_dash": watchlist_id_dash,
                "wid_hex": watchlist_id_hex,
                "uid_dash": user_id_dash,
                "uid_hex": user_id_hex,
            },
        )
        wl_row = wl_result.first()
        if not wl_row:
            raise HTTPException(status_code=404, detail="Watchlist not found")
        db_watchlist_id = wl_row[0]

        existing_result = await db.execute(
            text(
                """
                SELECT id, symbol, exchange
                FROM watchlist_items
                WHERE watchlist_id = :watchlist_id
                  AND UPPER(symbol) = :symbol
                LIMIT 1
                """
            ),
            {
                "watchlist_id": db_watchlist_id,
                "symbol": symbol,
            },
        )
        existing_row = existing_result.first()
        if existing_row:
            raise HTTPException(status_code=400, detail="Symbol already in watchlist")

        item_id = uuid.uuid4().hex
        await db.execute(
            text(
                """
                INSERT INTO watchlist_items (id, watchlist_id, symbol, exchange)
                VALUES (:id, :watchlist_id, :symbol, :exchange)
                """
            ),
            {
                "id": item_id,
                "watchlist_id": db_watchlist_id,
                "symbol": symbol,
                "exchange": exchange,
            },
        )
        await db.commit()
        return {"id": item_id, "symbol": symbol, "exchange": exchange}
    except HTTPException:
        raise
    except IntegrityError:
        await db.rollback()
        # Idempotent behavior on race/duplicate insert attempts.
        existing = await db.execute(
            text(
                """
                SELECT id, symbol, exchange
                FROM watchlist_items
                WHERE watchlist_id IN (:wid_dash, :wid_hex)
                  AND UPPER(symbol) = :symbol
                LIMIT 1
                """
            ),
            {
                "wid_dash": watchlist_id_dash,
                "wid_hex": watchlist_id_hex,
                "symbol": symbol,
            },
        )
        existing_item = existing.first()
        if existing_item:
            return {
                "id": str(existing_item[0]),
                "symbol": existing_item[1],
                "exchange": existing_item[2],
            }
        raise HTTPException(status_code=400, detail="Symbol already in watchlist")
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to add symbol: {type(e).__name__}")
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to add symbol: {type(e).__name__}: {e}")


@router.delete("/{watchlist_id}")
async def delete_watchlist(
    watchlist_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    watchlist_id_dash, watchlist_id_hex = _uuid_variants(watchlist_id, "watchlist_id")
    user_id_dash, user_id_hex = _uuid_variants(str(user.id), "user_id")

    wl_result = await db.execute(
        text(
            """
            SELECT id
            FROM watchlists
            WHERE id IN (:wid_dash, :wid_hex)
              AND user_id IN (:uid_dash, :uid_hex)
            LIMIT 1
            """
        ),
        {
            "wid_dash": watchlist_id_dash,
            "wid_hex": watchlist_id_hex,
            "uid_dash": user_id_dash,
            "uid_hex": user_id_hex,
        },
    )
    wl_row = wl_result.first()
    if not wl_row:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    await db.execute(
        text("DELETE FROM watchlist_items WHERE watchlist_id = :watchlist_id"),
        {"watchlist_id": wl_row[0]},
    )
    await db.execute(
        text("DELETE FROM watchlists WHERE id = :watchlist_id"),
        {"watchlist_id": wl_row[0]},
    )
    await db.commit()
    return {"message": "Watchlist deleted"}


@router.delete("/{watchlist_id}/items/{item_id}")
async def remove_item(
    watchlist_id: str,
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    watchlist_id_dash, watchlist_id_hex = _uuid_variants(watchlist_id, "watchlist_id")
    item_id_dash, item_id_hex = _uuid_variants(item_id, "item_id")
    user_id_dash, user_id_hex = _uuid_variants(str(user.id), "user_id")

    wl_result = await db.execute(
        text(
            """
            SELECT id
            FROM watchlists
            WHERE id IN (:wid_dash, :wid_hex)
              AND user_id IN (:uid_dash, :uid_hex)
            LIMIT 1
            """
        ),
        {
            "wid_dash": watchlist_id_dash,
            "wid_hex": watchlist_id_hex,
            "uid_dash": user_id_dash,
            "uid_hex": user_id_hex,
        },
    )
    wl_row = wl_result.first()
    if not wl_row:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    db_watchlist_id = wl_row[0]

    item_result = await db.execute(
        text(
            """
            SELECT id
            FROM watchlist_items
            WHERE id IN (:item_dash, :item_hex)
              AND watchlist_id = :watchlist_id
            LIMIT 1
            """
        ),
        {
            "item_dash": item_id_dash,
            "item_hex": item_id_hex,
            "watchlist_id": db_watchlist_id,
        },
    )
    item_row = item_result.first()
    if not item_row:
        raise HTTPException(status_code=404, detail="Item not found")

    await db.execute(
        text("DELETE FROM watchlist_items WHERE id = :item_id"),
        {"item_id": item_row[0]},
    )
    await db.commit()
    return {"message": "Item removed"}
