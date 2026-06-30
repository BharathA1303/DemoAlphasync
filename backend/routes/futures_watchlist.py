"""
Futures Watchlist Router — Manage futures contract watchlists.

Separate from equity watchlists, stores only futures contract symbols.
Endpoints mirror watchlist.py but for futures contracts.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from pydantic import BaseModel
import uuid
from database.connection import get_db
from models.user import User
from models.futures_watchlist import FuturesWatchlist, FuturesWatchlistItem
from routes.auth import get_current_user

router = APIRouter(prefix="/api/futures-watchlist", tags=["Futures Watchlist"])


class CreateFuturesWatchlistRequest(BaseModel):
    name: str = "My Futures Watchlist"


class RenameFuturesWatchlistRequest(BaseModel):
    name: str


class AddFuturesItemRequest(BaseModel):
    contract_symbol: str  # e.g., "NIFTY25MAR2026FUT", "RELIANCE25MAR2026FUT"


@router.get("")
async def get_futures_watchlists(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all futures watchlists for the current user."""
    try:
        query = select(FuturesWatchlist).where(
            FuturesWatchlist.user_id == user.id
        ).order_by(FuturesWatchlist.created_at)
        
        result = await db.execute(query)
        watchlists = result.scalars().all()

        wl_list = []
        for watchlist in watchlists:
            items = [
                {
                    "id": str(item.id),
                    "contract_symbol": item.contract_symbol,
                    "added_at": item.added_at.isoformat() if item.added_at else None,
                }
                for item in watchlist.items
            ]
            wl_list.append(
                {
                    "id": str(watchlist.id),
                    "name": watchlist.name,
                    "items": items,
                    "created_at": watchlist.created_at.isoformat() if watchlist.created_at else None,
                }
            )

        # Seed default futures watchlist if empty
        if not wl_list:
            default_wl = FuturesWatchlist(
                user_id=user.id,
                name="Watchlist 1"
            )
            db.add(default_wl)
            await db.commit()
            await db.refresh(default_wl)
            wl_list.append({
                "id": str(default_wl.id),
                "name": default_wl.name,
                "items": [],
                "created_at": default_wl.created_at.isoformat() if default_wl.created_at else None,
            })

        return {"watchlists": wl_list}
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {type(e).__name__}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Server error: {type(e).__name__}: {str(e)}"
        )


@router.post("")
async def create_futures_watchlist(
    req: CreateFuturesWatchlistRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new futures watchlist — unlimited per user."""
    name = req.name.strip() or "My Futures Watchlist"
    
    try:
        new_watchlist = FuturesWatchlist(
            user_id=user.id,
            name=name
        )
        db.add(new_watchlist)
        await db.commit()
        await db.refresh(new_watchlist)
        
        return {
            "id": str(new_watchlist.id),
            "name": new_watchlist.name,
            "items": [],
            "created_at": new_watchlist.created_at.isoformat() if new_watchlist.created_at else None,
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create watchlist: {type(e).__name__}"
        )


@router.patch("/{watchlist_id}")
async def rename_futures_watchlist(
    watchlist_id: str,
    req: RenameFuturesWatchlistRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename a futures watchlist."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    try:
        # Validate UUID format
        wl_uuid = uuid.UUID(watchlist_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid watchlist_id format")

    try:
        query = select(FuturesWatchlist).where(
            (FuturesWatchlist.id == wl_uuid) &
            (FuturesWatchlist.user_id == user.id)
        )
        result = await db.execute(query)
        watchlist = result.scalar_one_or_none()

        if not watchlist:
            raise HTTPException(status_code=404, detail="Watchlist not found")

        watchlist.name = name
        await db.commit()
        await db.refresh(watchlist)

        return {
            "id": str(watchlist.id),
            "name": watchlist.name,
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to rename watchlist: {type(e).__name__}"
        )


@router.post("/{watchlist_id}/items")
async def add_futures_item(
    watchlist_id: str,
    req: AddFuturesItemRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a futures contract to a watchlist."""
    contract_symbol = (req.contract_symbol or "").strip().upper()

    if not contract_symbol:
        raise HTTPException(status_code=400, detail="contract_symbol is required")

    try:
        wl_uuid = uuid.UUID(watchlist_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid watchlist_id format")

    try:
        # Verify watchlist ownership
        query = select(FuturesWatchlist).where(
            (FuturesWatchlist.id == wl_uuid) &
            (FuturesWatchlist.user_id == user.id)
        )
        result = await db.execute(query)
        watchlist = result.scalar_one_or_none()

        if not watchlist:
            raise HTTPException(status_code=404, detail="Watchlist not found")

        # Check if contract already exists
        existing_query = select(FuturesWatchlistItem).where(
            (FuturesWatchlistItem.watchlist_id == wl_uuid) &
            (FuturesWatchlistItem.contract_symbol == contract_symbol)
        )
        existing_result = await db.execute(existing_query)
        existing_item = existing_result.scalar_one_or_none()

        if existing_item:
            raise HTTPException(status_code=400, detail="Contract already in watchlist")

        # Add item
        new_item = FuturesWatchlistItem(
            watchlist_id=wl_uuid,
            contract_symbol=contract_symbol
        )
        db.add(new_item)
        await db.commit()
        await db.refresh(new_item)

        return {
            "id": str(new_item.id),
            "contract_symbol": new_item.contract_symbol,
            "added_at": new_item.added_at.isoformat() if new_item.added_at else None,
        }
    except HTTPException:
        raise
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Contract already in watchlist")
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add contract: {type(e).__name__}"
        )


@router.delete("/{watchlist_id}")
async def delete_futures_watchlist(
    watchlist_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a futures watchlist."""
    try:
        wl_uuid = uuid.UUID(watchlist_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid watchlist_id format")

    try:
        query = select(FuturesWatchlist).where(
            (FuturesWatchlist.id == wl_uuid) &
            (FuturesWatchlist.user_id == user.id)
        )
        result = await db.execute(query)
        watchlist = result.scalar_one_or_none()

        if not watchlist:
            raise HTTPException(status_code=404, detail="Watchlist not found")

        await db.delete(watchlist)
        await db.commit()

        return {"message": "Watchlist deleted"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete watchlist: {type(e).__name__}"
        )


@router.delete("/{watchlist_id}/items/{item_id}")
async def remove_futures_item(
    watchlist_id: str,
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a contract from a futures watchlist."""
    try:
        wl_uuid = uuid.UUID(watchlist_id)
        item_uuid = uuid.UUID(item_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid ID format")

    try:
        # Verify watchlist ownership
        query = select(FuturesWatchlist).where(
            (FuturesWatchlist.id == wl_uuid) &
            (FuturesWatchlist.user_id == user.id)
        )
        result = await db.execute(query)
        watchlist = result.scalar_one_or_none()

        if not watchlist:
            raise HTTPException(status_code=404, detail="Watchlist not found")

        # Find and delete item
        item_query = select(FuturesWatchlistItem).where(
            (FuturesWatchlistItem.id == item_uuid) &
            (FuturesWatchlistItem.watchlist_id == wl_uuid)
        )
        item_result = await db.execute(item_query)
        item = item_result.scalar_one_or_none()

        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        await db.delete(item)
        await db.commit()

        return {"message": "Item removed"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to remove item: {type(e).__name__}"
        )
