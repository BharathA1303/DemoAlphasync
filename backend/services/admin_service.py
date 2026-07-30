"""
Admin Service — Business logic for user account management.

All state-change actions write to the audit log within the same transaction.
Email notifications are sent as fire-and-forget background tasks.
"""

import logging
import math
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, case
from sqlalchemy.exc import SQLAlchemyError

from models.user import User, AdminAuditLog, UserSession
from models.feedback import UserFeedback
from models.portfolio import Portfolio, Holding, Transaction
from models.order import Order
from services import admin_group_service
from services.email_service import (
    send_account_approved_email,
    send_account_deactivated_email,
    send_access_duration_updated_email,
)
from services.account_deletion_service import (
    purge_user_account_data,
    try_delete_firebase_account,
)
from config.settings import settings
from dependencies.admin import (
    get_effective_admin_level,
    LEVEL_ROOT,
    LEVEL_MAX,
    LEVEL_MANAGE,
    LEVEL_VIEW_ONLY,
    is_main_root_admin,
)
from core.event_bus import event_bus, Event, EventType
from firebase_admin import auth as firebase_auth

logger = logging.getLogger(__name__)

_MIN_ACCESS_DAYS = 1
_MAX_ACCESS_DAYS = 365


def _is_valid_duration_days(duration_days: int) -> bool:
    return _MIN_ACCESS_DAYS <= duration_days <= _MAX_ACCESS_DAYS


def _safe_float(value, default=0.0) -> float:
    """Best-effort numeric conversion for legacy/dirty rows."""
    if value is None:
        return default
    try:
        converted = float(value)
        if not math.isfinite(converted):
            return default
        return converted
    except (TypeError, ValueError):
        return default


def _safe_iso(value) -> Optional[str]:
    """Return ISO datetime if available; pass through strings."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return value.isoformat()
    except Exception:
        return None


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))


def _coerce_uuid(value) -> Optional[UUID]:
    """Parse user IDs robustly across UUID string formats."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value

    text = str(value).strip()
    if not text:
        return None

    try:
        return UUID(text)
    except (ValueError, TypeError, AttributeError):
        # Handle compact UUID strings without dashes.
        compact = text.replace("-", "")
        if len(compact) == 32:
            try:
                return UUID(compact)
            except (ValueError, TypeError, AttributeError):
                return None
        return None


async def _write_audit(
    db: AsyncSession,
    admin_user: User,
    action: str,
    target_user_id=None,
    details: dict = None,
    ip: str = None,
):
    """Write an audit log entry (same transaction as the action)."""
    log = AdminAuditLog(
        admin_user_id=admin_user.id,
        action=action,
        target_user_id=target_user_id,
        details=details or {},
        ip_address=ip,
    )
    db.add(log)


async def _portfolio_holdings_snapshot(db: AsyncSession, portfolio_id) -> dict:
    """Return current holdings-derived portfolio totals without mutating capital."""
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = result.scalars().all()

    total_invested = Decimal("0")
    current_value = Decimal("0")
    for holding in holdings:
        quantity = _to_decimal(holding.quantity or 0)
        avg_price = _to_decimal(holding.avg_price or 0)
        current_price = _to_decimal(holding.current_price or avg_price)
        total_invested += avg_price * quantity
        current_value += current_price * quantity

    unrealized_pnl = current_value - total_invested
    return {
        "holdings": holdings,
        "total_invested": total_invested,
        "current_value": current_value,
        "unrealized_pnl": unrealized_pnl,
        "holdings_count": len(holdings),
    }


async def get_dashboard_stats(db: AsyncSession) -> dict:
    """Get aggregate stats for the admin dashboard."""
    result = await db.execute(
        select(
            func.count(User.id).label("total"),
            func.count(case((User.account_status == "pending_approval", 1))).label(
                "pending"
            ),
            func.count(case((User.account_status == "active", 1))).label("active"),
            func.count(case((User.account_status == "expired", 1))).label("expired"),
            func.count(case((User.account_status == "deactivated", 1))).label(
                "deactivated"
            ),
        ).where(User.role != "admin")
    )
    row = result.one()
    return {
        "total_users": row.total,
        "pending_approval": row.pending,
        "active": row.active,
        "expired": row.expired,
        "deactivated": row.deactivated,
    }


async def get_users_paginated(
    db: AsyncSession,
    status_filter: str = None,
    search: str = None,
    page: int = 1,
    per_page: int = 25,
    group_id: Optional[str] = None,
) -> dict:
    """Get paginated user list with optional filtering (includes admin accounts)."""
    query = select(User)

    if status_filter:
        query = query.where(User.account_status == status_filter)
    if search:
        like = f"%{search}%"
        query = query.where(
            (User.email.ilike(like))
            | (User.username.ilike(like))
            | (User.full_name.ilike(like))
        )

    normalized_group_id = str(group_id or "").strip()

    if normalized_group_id:
        # Group filtering is Redis-backed; fetch DB set first, then filter in-memory.
        result = await db.execute(query.order_by(User.created_at.desc()))
        all_users = result.scalars().all()
        user_ids = [str(u.id) for u in all_users]
        assignments = await admin_group_service.get_users_group_assignments(user_ids)

        if normalized_group_id.lower() == "normal":
            filtered_users = [u for u in all_users if str(u.id) not in assignments]
        else:
            filtered_users = [
                u
                for u in all_users
                if assignments.get(str(u.id), {}).get("group_id") == normalized_group_id
            ]

        total = len(filtered_users)
        offset = (page - 1) * per_page
        users = filtered_users[offset: offset + per_page]
    else:
        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_query)).scalar() or 0

        # Paginate
        offset = (page - 1) * per_page
        query = query.order_by(User.created_at.desc()).limit(per_page).offset(offset)
        result = await db.execute(query)
        users = result.scalars().all()

    assignment_map = await admin_group_service.get_users_group_assignments(
        [str(u.id) for u in users]
    )

    feedback_map = {}
    user_ids = [u.id for u in users]
    session_presence_map = {}
    if user_ids:
        try:
            feedback_result = await db.execute(
                select(
                    UserFeedback.user_id,
                    UserFeedback.rating,
                    UserFeedback.comment,
                ).where(UserFeedback.user_id.in_(user_ids))
            )
            for user_id, rating, comment in feedback_result.all():
                feedback_map[str(user_id)] = {"rating": rating, "comment": comment}
        except SQLAlchemyError as exc:
            logger.warning("Admin users list: feedback lookup skipped due to DB error: %s", exc)

        try:
            active_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
            session_result = await db.execute(
                select(
                    UserSession.user_id,
                    func.max(UserSession.last_seen_at).label("last_seen_at"),
                    func.max(
                        case(
                            (
                                and_(
                                    UserSession.is_active.is_(True),
                                    UserSession.last_seen_at >= active_cutoff,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ).label("is_online"),
                )
                .where(UserSession.user_id.in_(user_ids))
                .group_by(UserSession.user_id)
            )
            for user_id, last_seen_at, is_online in session_result.all():
                session_presence_map[str(user_id)] = {
                    "last_online_at": _safe_iso(last_seen_at),
                    "is_online": bool(is_online),
                }
        except SQLAlchemyError as exc:
            logger.warning("Admin users list: session lookup skipped due to DB error: %s", exc)

    serialized_users = []
    for u in users:
        serialized = _serialize_user(u)
        assignment = assignment_map.get(str(u.id), {})
        serialized["group_id"] = assignment.get("group_id")
        serialized["group_name"] = assignment.get("group_name")
        feedback = feedback_map.get(str(u.id), {})
        serialized["feedback_rating"] = feedback.get("rating")
        serialized["feedback_comment"] = feedback.get("comment")
        presence = session_presence_map.get(str(u.id), {})
        serialized["last_online_at"] = presence.get("last_online_at")
        serialized["is_online"] = bool(presence.get("is_online", False))
        serialized_users.append(serialized)

    return {
        "users": serialized_users,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


async def get_users_for_export(
    db: AsyncSession,
    status_filter: str = None,
    search: str = None,
    group_id: Optional[str] = None,
) -> list[dict]:
    """Return non-admin users for export with group metadata.

    When group_id is provided:
      - "normal" => only users not assigned to any custom group
      - custom id => only users assigned to that group

    Includes admin accounts so exports reflect the full Users table.
    """
    query = select(User)

    if status_filter:
        query = query.where(User.account_status == status_filter)
    if search:
        like = f"%{search}%"
        query = query.where(
            (User.email.ilike(like))
            | (User.username.ilike(like))
            | (User.full_name.ilike(like))
        )

    result = await db.execute(query.order_by(User.created_at.desc()))
    users = result.scalars().all()

    user_ids = [str(u.id) for u in users]
    assignments = await admin_group_service.get_users_group_assignments(user_ids)

    normalized_group_id = str(group_id or "").strip()
    if normalized_group_id:
        if normalized_group_id.lower() == "normal":
            users = [u for u in users if str(u.id) not in assignments]
        else:
            users = [
                u
                for u in users
                if assignments.get(str(u.id), {}).get("group_id") == normalized_group_id
            ]

    rows = []
    for user in users:
        serialized = _serialize_user(user)
        assignment = assignments.get(str(user.id), {})
        serialized["group_id"] = assignment.get("group_id")
        serialized["group_name"] = assignment.get("group_name")
        rows.append(serialized)

    return rows


async def get_user_detail(db: AsyncSession, user_id: str) -> Optional[dict]:
    """Get detailed info about a user including portfolio and recent orders."""
    target_uuid = _coerce_uuid(user_id)
    if not target_uuid:
        logger.warning("Admin get_user_detail received invalid user_id=%s", user_id)
        return None

    try:
        result = await db.execute(select(User).where(User.id == target_uuid))
        user = result.scalar_one_or_none()
        if not user:
            return None

        if user.role == "admin":
            return None

        data = _serialize_user(user)
        data["portfolio"] = None
        data["holdings"] = []
        data["recent_orders"] = []
        data["transactions"] = []
        data["sessions"] = []
        data["monitoring"] = {
            "active_devices": 0,
            "recent_sessions": 0,
            "last_seen_at": None,
        }
        data["performance"] = {
            "order_count": 0,
            "filled_orders": 0,
            "open_orders": 0,
            "cancelled_orders": 0,
            "rejected_orders": 0,
            "transaction_count": 0,
        }

        # Portfolio / holdings should never crash the admin panel for one bad row.
        try:
            port_result = await db.execute(
                select(Portfolio).where(Portfolio.user_id == user.id)
            )
            portfolio = port_result.scalar_one_or_none()
            if portfolio:
                snapshot = await _portfolio_holdings_snapshot(db, portfolio.id)
                total_pnl = _to_decimal(portfolio.total_pnl or 0)
                portfolio.total_invested = snapshot["total_invested"]
                portfolio.current_value = snapshot["current_value"]
                portfolio.total_pnl_percent = (
                    (
                        (total_pnl + snapshot["unrealized_pnl"])
                        / abs(_to_decimal(user.virtual_capital or 0))
                        * 100
                    )
                    if _to_decimal(user.virtual_capital or 0)
                    else 0
                )
                data["portfolio"] = {
                    "total_invested": _safe_float(snapshot["total_invested"]),
                    "current_value": _safe_float(snapshot["current_value"]),
                    "available_capital": _safe_float(portfolio.available_capital),
                    "total_pnl": _safe_float(total_pnl),
                    "total_pnl_percent": _safe_float(portfolio.total_pnl_percent),
                    "unrealized_pnl": _safe_float(snapshot["unrealized_pnl"]),
                }

                holdings = snapshot["holdings"]
                data["holdings"] = [
                    {
                        "id": str(h.id),
                        "symbol": h.symbol,
                        "company_name": h.company_name,
                        "exchange": h.exchange,
                        "quantity": h.quantity,
                        "avg_price": _safe_float(h.avg_price),
                        "current_price": _safe_float(h.current_price),
                        "invested_value": _safe_float(h.invested_value),
                        "current_value": _safe_float(h.current_value),
                        "pnl": _safe_float(h.pnl),
                        "pnl_percent": _safe_float(h.pnl_percent),
                    }
                    for h in holdings
                ]
        except Exception:
            logger.exception(
                "Admin get_user_detail portfolio enrichment failed for user_id=%s",
                user_id,
            )

        # Recent orders (last 20)
        try:
            orders_result = await db.execute(
                select(Order)
                .where(Order.user_id == user.id)
                .order_by(Order.created_at.desc())
                .limit(50)
            )
            orders = orders_result.scalars().all()
            data["recent_orders"] = [
                {
                    "id": str(o.id),
                    "symbol": o.symbol,
                    "side": o.side,
                    "order_type": o.order_type,
                    "quantity": o.quantity,
                    "price": _safe_float(o.price, None),
                    "filled_price": _safe_float(o.filled_price, None),
                    "status": o.status,
                    "created_at": _safe_iso(o.created_at),
                }
                for o in orders
            ]
        except Exception:
            logger.exception(
                "Admin get_user_detail recent_orders enrichment failed for user_id=%s",
                user_id,
            )

        try:
            tx_result = await db.execute(
                select(Transaction)
                .where(Transaction.user_id == user.id)
                .order_by(Transaction.created_at.desc())
                .limit(50)
            )
            txns = tx_result.scalars().all()
            data["transactions"] = [
                {
                    "id": str(t.id),
                    "order_id": str(t.order_id) if t.order_id else None,
                    "symbol": t.symbol,
                    "transaction_type": t.transaction_type,
                    "quantity": t.quantity,
                    "price": _safe_float(t.price),
                    "total_value": _safe_float(t.total_value),
                    "created_at": _safe_iso(t.created_at),
                }
                for t in txns
            ]
        except Exception:
            logger.exception(
                "Admin get_user_detail transactions enrichment failed for user_id=%s",
                user_id,
            )

        try:
            performance_result = await db.execute(
                select(
                    func.count(Order.id).label("order_count"),
                    func.count(case((Order.status == "FILLED", 1))).label(
                        "filled_orders"
                    ),
                    func.count(
                        case(
                            (
                                Order.status.in_(
                                    ["OPEN", "PENDING", "PARTIALLY_FILLED"]
                                ),
                                1,
                            )
                        )
                    ).label("open_orders"),
                    func.count(case((Order.status == "CANCELLED", 1))).label(
                        "cancelled_orders"
                    ),
                    func.count(case((Order.status == "REJECTED", 1))).label(
                        "rejected_orders"
                    ),
                ).where(Order.user_id == user.id)
            )
            perf_row = performance_result.one()

            transaction_count = (
                await db.execute(
                    select(func.count(Transaction.id)).where(
                        Transaction.user_id == user.id
                    )
                )
            ).scalar() or 0

            data["performance"] = {
                "order_count": perf_row.order_count,
                "filled_orders": perf_row.filled_orders,
                "open_orders": perf_row.open_orders,
                "cancelled_orders": perf_row.cancelled_orders,
                "rejected_orders": perf_row.rejected_orders,
                "transaction_count": transaction_count,
            }
        except Exception:
            logger.exception(
                "Admin get_user_detail performance enrichment failed for user_id=%s",
                user_id,
            )

        # Active/recent sessions for security monitoring (last 30 days)
        try:
            now = datetime.now(timezone.utc)
            active_cutoff = now - timedelta(minutes=30)
            recent_cutoff = now - timedelta(days=30)
            sessions_result = await db.execute(
                select(UserSession)
                .where(
                    UserSession.user_id == user.id,
                    UserSession.last_seen_at >= recent_cutoff,
                )
                .order_by(UserSession.last_seen_at.desc())
                .limit(25)
            )
            sessions = sessions_result.scalars().all()
            active_devices = 0
            for s in sessions:
                is_active = bool(
                    s.is_active and s.last_seen_at and s.last_seen_at >= active_cutoff
                )
                if is_active:
                    active_devices += 1
                data["sessions"].append(
                    {
                        "id": str(s.id),
                        "ip_address": s.ip_address,
                        "user_agent": s.user_agent,
                        "first_seen_at": _safe_iso(s.first_seen_at),
                        "last_seen_at": _safe_iso(s.last_seen_at),
                        "is_active": is_active,
                    }
                )

            data["monitoring"] = {
                "active_devices": active_devices,
                "recent_sessions": len(data["sessions"]),
                "last_seen_at": (
                    data["sessions"][0]["last_seen_at"] if data["sessions"] else None
                ),
            }
        except Exception:
            logger.exception(
                "Admin get_user_detail session enrichment failed for user_id=%s",
                user_id,
            )

        return data
    except Exception:
        logger.exception(
            "Admin get_user_detail failed for user_id=%s",
            user_id,
        )
        # Fallback to a minimal response to keep admin panel functional.
        try:
            result = await db.execute(select(User).where(User.id == target_uuid))
            user = result.scalar_one_or_none()
            if not user or user.role == "admin":
                return None
            data = _serialize_user(user)
            data["portfolio"] = None
            data["holdings"] = []
            data["recent_orders"] = []
            data["transactions"] = []
            data["sessions"] = []
            data["monitoring"] = {
                "active_devices": 0,
                "recent_sessions": 0,
                "last_seen_at": None,
            }
            data["performance"] = {
                "order_count": 0,
                "filled_orders": 0,
                "open_orders": 0,
                "cancelled_orders": 0,
                "rejected_orders": 0,
                "transaction_count": 0,
            }
            return data
        except Exception:
            logger.exception(
                "Admin get_user_detail fallback failed for user_id=%s",
                user_id,
            )
            return None


async def approve_user(
    db: AsyncSession,
    admin_user: User,
    target_user_id: str,
    duration_days: int = 30,
    ip: str = None,
) -> dict:
    """Approve a user account with a specified access duration."""
    target_uuid = _coerce_uuid(target_user_id)
    if not target_uuid:
        return {"success": False, "error": "Invalid user ID"}

    if not _is_valid_duration_days(duration_days):
        return {
            "success": False,
            "error": f"Duration must be between {_MIN_ACCESS_DAYS} and {_MAX_ACCESS_DAYS} days",
        }

    result = await db.execute(select(User).where(User.id == target_uuid))
    user = result.scalar_one_or_none()
    if not user:
        return {"success": False, "error": "User not found"}

    if user.role == "admin":
        return {
            "success": False,
            "error": "Cannot manage admin accounts from this panel",
        }

    if user.account_status == "active":
        return {
            "success": False,
            "error": "User is already active",
        }

    now = datetime.now(timezone.utc)
    user.account_status = "active"
    user.is_active = True
    user.access_duration_days = duration_days
    user.access_expires_at = now + timedelta(days=duration_days)
    user.approved_at = now
    user.approved_by = admin_user.id
    user.deactivation_reason = None

    await _write_audit(
        db,
        admin_user,
        "approve_user",
        target_user_id=user.id,
        details={"duration_days": duration_days},
        ip=ip,
    )

    # Send email notification (best-effort, non-blocking)
    try:
        send_account_approved_email(user, duration_days)
    except Exception:
        logger.exception("Failed to enqueue approval email for user_id=%s", user.id)

    # Emit event (best-effort)
    try:
        event_bus.emit_nowait(
            Event(
                type=EventType.USER_APPROVED,
                data={"user_id": str(user.id), "duration_days": duration_days},
                user_id=str(admin_user.id),
                source="admin",
            )
        )
    except Exception:
        logger.exception("Failed to emit USER_APPROVED event for user_id=%s", user.id)

    logger.info(
        f"Admin {admin_user.email} approved user {user.email} for {duration_days} days"
    )
    return {"success": True, "user": _serialize_user(user)}


async def deactivate_user(
    db: AsyncSession,
    admin_user: User,
    target_user_id: str,
    reason: str = None,
    ip: str = None,
) -> dict:
    """Deactivate a user account."""
    target_uuid = _coerce_uuid(target_user_id)
    if not target_uuid:
        return {"success": False, "error": "Invalid user ID"}

    result = await db.execute(select(User).where(User.id == target_uuid))
    user = result.scalar_one_or_none()
    if not user:
        return {"success": False, "error": "User not found"}

    if user.role == "admin":
        return {
            "success": False,
            "error": "Cannot manage admin accounts from this panel",
        }

    # Prevent admin from deactivating themselves
    if str(user.id) == str(admin_user.id):
        return {"success": False, "error": "Cannot deactivate your own account"}

    if user.account_status == "deactivated":
        return {
            "success": False,
            "error": "User is already deactivated",
        }

    user.account_status = "deactivated"
    user.is_active = False
    user.deactivation_reason = reason

    await _write_audit(
        db,
        admin_user,
        "deactivate_user",
        target_user_id=user.id,
        details={"reason": reason},
        ip=ip,
    )

    try:
        send_account_deactivated_email(user, reason)
    except Exception:
        logger.exception("Failed to enqueue deactivation email for user_id=%s", user.id)

    try:
        event_bus.emit_nowait(
            Event(
                type=EventType.USER_DEACTIVATED,
                data={"user_id": str(user.id), "reason": reason},
                user_id=str(admin_user.id),
                source="admin",
            )
        )
    except Exception:
        logger.exception(
            "Failed to emit USER_DEACTIVATED event for user_id=%s", user.id
        )

    logger.info(f"Admin {admin_user.email} deactivated user {user.email}: {reason}")
    return {"success": True, "user": _serialize_user(user)}


async def reactivate_user(
    db: AsyncSession,
    admin_user: User,
    target_user_id: str,
    duration_days: int = 30,
    ip: str = None,
) -> dict:
    """Reactivate a deactivated or expired user."""
    target_uuid = _coerce_uuid(target_user_id)
    if not target_uuid:
        return {"success": False, "error": "Invalid user ID"}

    if not _is_valid_duration_days(duration_days):
        return {
            "success": False,
            "error": f"Duration must be between {_MIN_ACCESS_DAYS} and {_MAX_ACCESS_DAYS} days",
        }

    result = await db.execute(select(User).where(User.id == target_uuid))
    user = result.scalar_one_or_none()
    if not user:
        return {"success": False, "error": "User not found"}

    if user.role == "admin":
        return {
            "success": False,
            "error": "Cannot manage admin accounts from this panel",
        }

    if user.account_status == "active":
        return {
            "success": False,
            "error": "User is already active",
        }

    now = datetime.now(timezone.utc)
    user.account_status = "active"
    user.is_active = True
    user.access_duration_days = duration_days
    user.access_expires_at = now + timedelta(days=duration_days)
    user.approved_at = now
    user.approved_by = admin_user.id
    user.deactivation_reason = None

    await _write_audit(
        db,
        admin_user,
        "reactivate_user",
        target_user_id=user.id,
        details={"duration_days": duration_days},
        ip=ip,
    )

    try:
        send_account_approved_email(user, duration_days)
    except Exception:
        logger.exception("Failed to enqueue reactivation email for user_id=%s", user.id)

    logger.info(
        f"Admin {admin_user.email} reactivated user {user.email} for {duration_days} days"
    )
    return {"success": True, "user": _serialize_user(user)}


async def set_access_duration(
    db: AsyncSession,
    admin_user: User,
    target_user_id: str,
    duration_days: int,
    ip: str = None,
) -> dict:
    """Update the access duration for a user."""
    target_uuid = _coerce_uuid(target_user_id)
    if not target_uuid:
        return {"success": False, "error": "Invalid user ID"}

    if not _is_valid_duration_days(duration_days):
        return {
            "success": False,
            "error": f"Duration must be between {_MIN_ACCESS_DAYS} and {_MAX_ACCESS_DAYS} days",
        }

    result = await db.execute(select(User).where(User.id == target_uuid))
    user = result.scalar_one_or_none()
    if not user:
        return {"success": False, "error": "User not found"}

    if user.role == "admin":
        return {
            "success": False,
            "error": "Cannot manage admin accounts from this panel",
        }

    now = datetime.now(timezone.utc)
    old_status = user.account_status
    old_expires = user.access_expires_at
    user.access_duration_days = duration_days
    user.access_expires_at = now + timedelta(days=duration_days)

    if user.account_status == "expired":
        user.account_status = "active"
        user.is_active = True

    await _write_audit(
        db,
        admin_user,
        "set_duration",
        target_user_id=user.id,
        details={
            "duration_days": duration_days,
            "old_status": old_status,
            "old_expires": _safe_iso(old_expires),
        },
        ip=ip,
    )

    try:
        send_access_duration_updated_email(
            user,
            duration_days=duration_days,
            access_expires_at=user.access_expires_at,
            reactivated=(old_status != "active"),
        )
    except Exception:
        logger.exception(
            "Failed to enqueue access duration update email for user_id=%s", user.id
        )

    logger.info(
        f"Admin {admin_user.email} set duration {duration_days}d for {user.email}"
    )
    return {"success": True, "user": _serialize_user(user)}


async def force_logout_user(
    db: AsyncSession,
    admin_user: User,
    target_user_id: str,
    ip: str = None,
) -> dict:
    """Force logout all active sessions for a target user.

    Marks local UserSession rows inactive and revokes Firebase refresh tokens
    when possible so existing JWT sessions are invalidated.
    """
    target_uuid = _coerce_uuid(target_user_id)
    if not target_uuid:
        return {"success": False, "error": "Invalid user ID"}

    result = await db.execute(select(User).where(User.id == target_uuid))
    user = result.scalar_one_or_none()
    if not user:
        return {"success": False, "error": "User not found"}

    if user.role == "admin":
        return {
            "success": False,
            "error": "Cannot force-logout admin accounts from this panel",
        }

    now = datetime.now(timezone.utc)
    sessions_result = await db.execute(
        select(UserSession).where(
            UserSession.user_id == user.id, UserSession.is_active.is_(True)
        )
    )
    sessions = sessions_result.scalars().all()
    deactivated = 0
    for s in sessions:
        s.is_active = False
        s.last_seen_at = now
        deactivated += 1

    firebase_revoked = False
    firebase_error = None
    if user.firebase_uid:
        try:
            firebase_auth.revoke_refresh_tokens(user.firebase_uid)
            firebase_revoked = True
        except Exception as e:
            firebase_error = str(e)
            logger.warning(
                "Failed to revoke Firebase tokens for user_id=%s: %s",
                user.id,
                e,
            )

    await _write_audit(
        db,
        admin_user,
        "force_logout_user",
        target_user_id=user.id,
        details={
            "deactivated_sessions": deactivated,
            "firebase_revoked": firebase_revoked,
            "firebase_error": firebase_error,
        },
        ip=ip,
    )

    try:
        event_bus.emit_nowait(
            Event(
                type=EventType.USER_LOGOUT,
                data={"user_id": str(user.id), "forced": True},
                user_id=str(admin_user.id),
                source="admin",
            )
        )
    except Exception:
        logger.exception("Failed to emit USER_LOGOUT for user_id=%s", user.id)

    return {
        "success": True,
        "user_id": str(user.id),
        "deactivated_sessions": deactivated,
        "firebase_revoked": firebase_revoked,
        "firebase_error": firebase_error,
    }


async def delete_user_account(
    db: AsyncSession,
    admin_user: User,
    target_user_id: str,
    ip: str = None,
) -> dict:
    """Permanently delete a non-admin user's account and all linked data."""
    target_uuid = _coerce_uuid(target_user_id)
    if not target_uuid:
        return {"success": False, "error": "Invalid user ID"}

    result = await db.execute(select(User).where(User.id == target_uuid))
    user = result.scalar_one_or_none()
    if not user:
        return {"success": False, "error": "User not found"}

    if user.role == "admin":
        return {"success": False, "error": "Cannot delete admin accounts from this panel"}

    if str(user.id) == str(admin_user.id):
        return {"success": False, "error": "Cannot delete your own admin account"}

    snapshot = {
        "email": user.email,
        "full_name": user.full_name,
        "auth_provider": user.auth_provider,
    }

    firebase_delete = try_delete_firebase_account(user.firebase_uid)
    purge_summary = await purge_user_account_data(db, user.id)

    await _write_audit(
        db,
        admin_user,
        "admin_delete_user",
        target_user_id=None,
        details={
            **snapshot,
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "firebase_delete": firebase_delete,
            "purge_summary": purge_summary,
        },
        ip=ip,
    )

    logger.info("Admin %s permanently deleted user %s", admin_user.email, snapshot["email"])
    return {
        "success": True,
        "message": "User account permanently deleted",
        "deleted_email": snapshot["email"],
        "firebase_deleted": firebase_delete.get("deleted", False),
    }


async def update_user_financials(
    db: AsyncSession,
    admin_user: User,
    target_user_id: str,
    available_capital: float = None,
    virtual_capital: float = None,
    total_pnl: float = None,
    total_pnl_percent: float = None,
    note: str = None,
    ip: str = None,
) -> dict:
    """Allow root admin to directly adjust a user's financial snapshot."""
    target_uuid = _coerce_uuid(target_user_id)
    if not target_uuid:
        return {"success": False, "error": "Invalid user ID"}

    result = await db.execute(select(User).where(User.id == target_uuid))
    user = result.scalar_one_or_none()
    if not user:
        return {"success": False, "error": "User not found"}
    if user.role == "admin":
        return {"success": False, "error": "Cannot edit admin financials"}

    port_result = await db.execute(
        select(Portfolio).where(Portfolio.user_id == user.id)
    )
    portfolio = port_result.scalar_one_or_none()
    if not portfolio:
        return {"success": False, "error": "Portfolio not found"}

    changes = {}

    if available_capital is not None:
        portfolio.available_capital = _to_decimal(available_capital)
        changes["available_capital"] = _safe_float(portfolio.available_capital)
        if virtual_capital is None:
            user.virtual_capital = _to_decimal(available_capital)
            changes["virtual_capital"] = _safe_float(user.virtual_capital)

    if virtual_capital is not None:
        user.virtual_capital = _to_decimal(virtual_capital)
        changes["virtual_capital"] = _safe_float(user.virtual_capital)
        if available_capital is None:
            portfolio.available_capital = _to_decimal(virtual_capital)
            changes["available_capital"] = _safe_float(portfolio.available_capital)

    if total_pnl is not None:
        portfolio.total_pnl = _to_decimal(total_pnl)
        changes["total_pnl"] = _safe_float(portfolio.total_pnl)

    if total_pnl_percent is not None:
        portfolio.total_pnl_percent = _to_decimal(total_pnl_percent)
        changes["total_pnl_percent"] = _safe_float(portfolio.total_pnl_percent)

    if not changes:
        return {"success": False, "error": "No financial fields provided"}

    snapshot = await _portfolio_holdings_snapshot(db, portfolio.id)
    if total_pnl is not None and total_pnl_percent is None:
        base_capital = abs(_to_decimal(user.virtual_capital or 0))
        portfolio.total_pnl_percent = (
            ((portfolio.total_pnl + snapshot["unrealized_pnl"]) / base_capital * 100)
            if base_capital
            else Decimal("0")
        )
        changes["total_pnl_percent"] = _safe_float(portfolio.total_pnl_percent)

    await _write_audit(
        db,
        admin_user,
        "update_user_financials",
        target_user_id=user.id,
        details={**changes, "note": note},
        ip=ip,
    )

    logger.info(
        "Root admin %s updated financials for %s: %s",
        admin_user.email,
        user.email,
        changes,
    )

    return {
        "success": True,
        "changes": changes,
        "user": _serialize_user(user),
        "portfolio": {
            "available_capital": _safe_float(portfolio.available_capital),
            "total_pnl": _safe_float(portfolio.total_pnl),
            "total_pnl_percent": _safe_float(portfolio.total_pnl_percent),
            "total_invested": _safe_float(snapshot["total_invested"]),
            "current_value": _safe_float(snapshot["current_value"]),
            "unrealized_pnl": _safe_float(snapshot["unrealized_pnl"]),
        },
    }


async def get_audit_log(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Get paginated audit log."""
    query = select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc())

    count_query = select(func.count()).select_from(AdminAuditLog)
    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * per_page
    result = await db.execute(query.limit(per_page).offset(offset))
    logs = result.scalars().all()

    # Fetch admin usernames for display
    admin_ids = {l.admin_user_id for l in logs if l.admin_user_id}
    admin_names = {}
    if admin_ids:
        users_result = await db.execute(
            select(User.id, User.email, User.full_name).where(User.id.in_(admin_ids))
        )
        for uid, email, name in users_result:
            admin_names[str(uid)] = name or email

    # Fetch target usernames
    target_ids = {l.target_user_id for l in logs if l.target_user_id}
    target_names = {}
    if target_ids:
        users_result = await db.execute(
            select(User.id, User.email, User.full_name).where(User.id.in_(target_ids))
        )
        for uid, email, name in users_result:
            target_names[str(uid)] = name or email

    return {
        "logs": [
            {
                "id": str(l.id),
                "admin_name": admin_names.get(str(l.admin_user_id), "Unknown"),
                "action": l.action,
                "target_user_name": target_names.get(str(l.target_user_id), "—"),
                "target_user_id": str(l.target_user_id) if l.target_user_id else None,
                "details": l.details,
                "ip_address": l.ip_address,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


def _serialize_user(user: User) -> dict:
    """Serialize a User object for API responses."""
    return {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "phone": user.phone,
        "role": user.role,
        "avatar_url": user.avatar_url,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "account_status": user.account_status,
        "access_expires_at": _safe_iso(user.access_expires_at),
        "access_duration_days": user.access_duration_days,
        "approved_at": _safe_iso(user.approved_at),
        "deactivation_reason": user.deactivation_reason,
        "virtual_capital": _safe_float(user.virtual_capital),
        "auth_provider": user.auth_provider,
        "admin_level": user.admin_level,
        "admin_assigned_by": (
            str(user.admin_assigned_by) if user.admin_assigned_by else None
        ),
        "admin_assigned_at": _safe_iso(user.admin_assigned_at),
        "created_at": _safe_iso(user.created_at),
        "updated_at": _safe_iso(user.updated_at),
    }


# ── Admin Management (root only) ──────────────────────────────────────


async def list_admins(db: AsyncSession) -> list[dict]:
    """List all admin users with their levels."""
    result = await db.execute(
        select(User).where(User.role == "admin").order_by(User.created_at.asc())
    )
    admins = result.scalars().all()

    admin_list = []
    for a in admins:
        level = get_effective_admin_level(a)
        admin_list.append(
            {
                **_serialize_user(a),
                "effective_level": level,
                "is_root": level in (LEVEL_ROOT, LEVEL_MAX),
                "is_main_root": is_main_root_admin(a),
            }
        )
    return admin_list


async def promote_to_admin(
    db: AsyncSession,
    root_admin: User,
    target_email: str,
    admin_level: str = LEVEL_MANAGE,
    ip: str = None,
) -> dict:
    """Promote an existing user to admin with a given permission level."""
    actor_level = get_effective_admin_level(root_admin)
    if actor_level not in (LEVEL_ROOT, LEVEL_MAX):
        return {"success": False, "error": "Root or Max access required"}

    if admin_level not in (LEVEL_MAX, LEVEL_MANAGE, LEVEL_VIEW_ONLY):
        return {
            "success": False,
            "error": f"Invalid admin level: {admin_level}. Use 'max', 'manage' or 'view_only'.",
        }

    target_email = target_email.strip().lower()

    # Cannot promote the root email (already root)
    if target_email == settings.ROOT_ADMIN_EMAIL.lower():
        return {"success": False, "error": "This account is already the root admin."}

    result = await db.execute(
        select(User).where(func.lower(User.email) == target_email)
    )
    user = result.scalar_one_or_none()
    if not user:
        return {"success": False, "error": f"No user found with email: {target_email}"}

    if user.role == "admin":
        return {
            "success": False,
            "error": "This user is already an admin. Use 'Update Permissions' to change their level.",
        }

    now = datetime.now(timezone.utc)
    user.role = "admin"
    user.admin_level = admin_level
    user.admin_assigned_by = root_admin.id
    user.admin_assigned_at = now
    # Admins should be active
    user.account_status = "active"
    user.is_active = True

    await _write_audit(
        db,
        root_admin,
        "promote_to_admin",
        target_user_id=user.id,
        details={"admin_level": admin_level, "target_email": user.email},
        ip=ip,
    )

    logger.info(
        f"Root admin {root_admin.email} promoted {user.email} to admin ({admin_level})"
    )
    return {
        "success": True,
        "user": {**_serialize_user(user), "effective_level": admin_level},
    }


async def update_admin_level(
    db: AsyncSession,
    root_admin: User,
    target_admin_id: str,
    new_level: str,
    ip: str = None,
) -> dict:
    """Update the permission level of an existing admin."""
    actor_level = get_effective_admin_level(root_admin)
    if actor_level not in (LEVEL_ROOT, LEVEL_MAX):
        return {"success": False, "error": "Root or Max access required"}

    if new_level not in (LEVEL_MAX, LEVEL_MANAGE, LEVEL_VIEW_ONLY):
        return {"success": False, "error": f"Invalid admin level: {new_level}"}

    target_uuid = _coerce_uuid(target_admin_id)
    if not target_uuid:
        return {"success": False, "error": "Invalid admin ID"}

    result = await db.execute(select(User).where(User.id == target_uuid))
    user = result.scalar_one_or_none()
    if not user:
        return {"success": False, "error": "Admin not found"}

    if user.role != "admin":
        return {"success": False, "error": "User is not an admin"}

    # Main root account is always protected.
    if is_main_root_admin(user):
        return {"success": False, "error": "Cannot modify root admin permissions"}

    old_level = user.admin_level
    user.admin_level = new_level

    await _write_audit(
        db,
        root_admin,
        "update_admin_level",
        target_user_id=user.id,
        details={"old_level": old_level, "new_level": new_level},
        ip=ip,
    )

    logger.info(
        f"Root admin {root_admin.email} changed {user.email} level: {old_level} → {new_level}"
    )
    return {
        "success": True,
        "user": {**_serialize_user(user), "effective_level": new_level},
    }


async def revoke_admin(
    db: AsyncSession,
    root_admin: User,
    target_admin_id: str,
    ip: str = None,
) -> dict:
    """Revoke admin access — demote back to regular user."""
    actor_level = get_effective_admin_level(root_admin)
    if actor_level not in (LEVEL_ROOT, LEVEL_MAX):
        return {"success": False, "error": "Root or Max access required"}

    target_uuid = _coerce_uuid(target_admin_id)
    if not target_uuid:
        return {"success": False, "error": "Invalid admin ID"}

    result = await db.execute(select(User).where(User.id == target_uuid))
    user = result.scalar_one_or_none()
    if not user:
        return {"success": False, "error": "Admin not found"}

    if user.role != "admin":
        return {"success": False, "error": "User is not an admin"}

    # Main root account is always protected.
    if is_main_root_admin(user):
        return {"success": False, "error": "Cannot revoke root admin access"}

    # Cannot revoke yourself
    if str(user.id) == str(root_admin.id):
        return {"success": False, "error": "Cannot revoke your own admin access"}

    old_level = user.admin_level
    user.role = "user"
    user.admin_level = None
    user.admin_assigned_by = None
    user.admin_assigned_at = None

    await _write_audit(
        db,
        root_admin,
        "revoke_admin",
        target_user_id=user.id,
        details={"old_level": old_level, "target_email": user.email},
        ip=ip,
    )

    logger.info(f"Root admin {root_admin.email} revoked admin access for {user.email}")
    return {"success": True, "user": _serialize_user(user)}
