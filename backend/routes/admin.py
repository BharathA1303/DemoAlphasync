"""
Admin Panel API — Complete user account management + admin hierarchy.

Security layers:
  1. Firebase token (Bearer header) → identity verification
  2. role='admin' check → restricts to admins
  3. TOTP 2FA → X-Admin-Session header with short-lived token
  4. Admin level → root / manage / view_only permission checks
  5. Audit logging → every action recorded

Admin levels:
  - root:      Full access. Can create/manage/revoke other admins.
  - manage:    Can approve/deactivate/reactivate users.
  - view_only: Read-only dashboard access.

All endpoints under /api/admin/*
"""

import logging
from io import BytesIO
from datetime import datetime
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional
from fastapi.responses import StreamingResponse
from openpyxl import Workbook

from database.connection import get_db
from models.user import User
from dependencies.admin import (
    get_admin_user,
    require_2fa_session,
    require_root_admin,
    require_manage_level,
    get_effective_admin_level,
)
from services import admin_service, admin_2fa_service
from services import admin_group_service
from core.admin_runtime_flags import admin_runtime_flags

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


def _normalize_user_id(user_id: str) -> UUID:
    """Validate and return UUID object for DB-safe comparisons."""
    try:
        return UUID(str(user_id).strip())
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid user ID format")


def _safe_excel_value(value):
    return "" if value is None else str(value)


def _build_users_excel(rows: list[dict], sheet_name: str = "Users") -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name[:31] or "Users"

    headers = [
        "Email",
        "Full Name",
        "Username",
        "Mobile",
        "Status",
        "Group",
        "Provider",
        "Registered At",
        "Approved At",
        "Access Expires",
    ]
    worksheet.append(headers)

    for row in rows:
        worksheet.append(
            [
                _safe_excel_value(row.get("email")),
                _safe_excel_value(row.get("full_name")),
                _safe_excel_value(row.get("username")),
                _safe_excel_value(row.get("phone")),
                _safe_excel_value(row.get("account_status")),
                _safe_excel_value(row.get("group_name") or "Normal"),
                _safe_excel_value(row.get("auth_provider")),
                _safe_excel_value(row.get("created_at")),
                _safe_excel_value(row.get("approved_at")),
                _safe_excel_value(row.get("access_expires_at")),
            ]
        )

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


# ── Schemas ──────────────────────────────────────────────────────────


class Setup2FAResponse(BaseModel):
    secret: str
    uri: str


class Verify2FARequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8, pattern=r"^\d{6,8}$")


class ApproveUserRequest(BaseModel):
    duration_days: int = Field(default=30, ge=1, le=365)


class DeactivateUserRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)
    totp_code: str = Field(..., min_length=6, max_length=8, pattern=r"^\d{6,8}$")


class ReactivateUserRequest(BaseModel):
    duration_days: int = Field(default=30, ge=1, le=365)


class DeleteUserRequest(BaseModel):
    totp_code: str = Field(..., min_length=6, max_length=8, pattern=r"^\d{6,8}$")


class SetDurationRequest(BaseModel):
    duration_days: int = Field(..., ge=1, le=365)


class UpdateFinancialsRequest(BaseModel):
    available_capital: Optional[float] = Field(default=None, ge=0)
    virtual_capital: Optional[float] = Field(default=None, ge=0)
    total_pnl: Optional[float] = None
    total_pnl_percent: Optional[float] = None
    note: Optional[str] = Field(default=None, max_length=500)


class PromoteAdminRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    admin_level: str = Field(default="manage", pattern=r"^(max|manage|view_only)$")


class UpdateAdminLevelRequest(BaseModel):
    admin_level: str = Field(..., pattern=r"^(max|manage|view_only)$")


class CreateGroupRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)


class RenameGroupRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)


class GroupAutoApprovalUpdateRequest(BaseModel):
    enabled: bool


class SetUserGroupRequest(BaseModel):
    group_id: Optional[str] = Field(default=None, max_length=64)


class AutoApprovalUpdateRequest(BaseModel):
    enabled: bool


# ── 2FA Auth Endpoints (require admin role, NOT 2FA session) ─────────


@router.get("/auth/status")
async def get_2fa_status(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if the admin has 2FA set up."""
    has_2fa = await admin_2fa_service.has_2fa_enabled(db, admin.id)
    return {"has_2fa": has_2fa, "admin_email": admin.email}


@router.post("/auth/setup-2fa")
async def setup_2fa(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new TOTP secret. Returns QR code URI for scanning."""
    result = await admin_2fa_service.generate_totp_secret(db, admin)
    logger.info(f"2FA setup initiated for admin {admin.email}")
    return result


@router.post("/auth/enable-2fa")
async def enable_2fa(
    req: Verify2FARequest,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify a TOTP code to enable 2FA. Must be called after setup."""
    try:
        success = await admin_2fa_service.enable_2fa(db, admin, req.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not success:
        raise HTTPException(
            status_code=400, detail="Invalid TOTP code. Please try again."
        )
    logger.info(f"2FA enabled for admin {admin.email}")
    return {"success": True, "message": "2FA is now enabled"}


@router.post("/auth/verify-2fa")
async def verify_2fa(
    req: Verify2FARequest,
    request: Request,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify TOTP code and create an admin session token."""
    try:
        has_2fa = await admin_2fa_service.has_2fa_enabled(db, admin.id)
        if not has_2fa:
            raise HTTPException(
                status_code=400, detail="2FA is not set up. Please set up 2FA first."
            )

        success = await admin_2fa_service.verify_totp(db, admin, req.code)
        if not success:
            raise HTTPException(status_code=401, detail="Invalid TOTP code")

        ip = request.client.host if request.client else None
        ua = request.headers.get("User-Agent", "")[:500]
        token = await admin_2fa_service.create_admin_session(db, admin, ip, ua)

        logger.info(f"Admin 2FA verified: {admin.email} from {ip}")
        return {"session_token": token}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Admin 2FA verification failed for %s: %s", admin.email, exc)
        raise HTTPException(
            status_code=500,
            detail="Admin 2FA verification failed. Please try again or re-setup 2FA.",
        )


@router.post("/auth/validate-session")
async def validate_session(
    admin: User = Depends(require_2fa_session),
):
    """Validate the current admin session is still active."""
    level = get_effective_admin_level(admin)
    return {"valid": True, "admin_email": admin.email, "admin_level": level}


# ── Dashboard ────────────────────────────────────────────────────────


@router.get("/dashboard/stats")
async def dashboard_stats(
    admin: User = Depends(require_2fa_session),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregate dashboard statistics."""
    stats = await admin_service.get_dashboard_stats(db)
    level = get_effective_admin_level(admin)
    stats["admin_level"] = level
    return stats


@router.get("/settings/auto-approval")
async def get_auto_approval_setting(
    admin: User = Depends(require_2fa_session),
):
    """Read current new-user auto-approval setting."""
    return {"enabled": admin_runtime_flags.is_auto_approval_enabled()}


@router.post("/settings/auto-approval")
async def update_auto_approval_setting(
    req: AutoApprovalUpdateRequest,
    request: Request,
    admin: User = Depends(require_root_admin),
):
    """Root-only toggle for new-user auto-approval behavior."""
    enabled = admin_runtime_flags.set_auto_approval_enabled(req.enabled)
    ip = request.client.host if request.client else None
    logger.info(
        "Admin auto-approval toggled by %s to %s (ip=%s)",
        admin.email,
        enabled,
        ip,
    )
    return {"enabled": enabled}


# ── User Management (require at least 'manage' for writes) ──────────


@router.get("/users")
async def list_users(
    status: Optional[str] = None,
    group_id: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 25,
    admin: User = Depends(require_2fa_session),
    db: AsyncSession = Depends(get_db),
):
    """List all users with pagination and filtering."""
    per_page = min(per_page, 100)  # Cap page size
    return await admin_service.get_users_paginated(
        db,
        status,
        search,
        page,
        per_page,
        group_id,
    )


@router.get("/exports/users/overall")
async def export_users_overall_excel(
    admin: User = Depends(require_root_admin),
    db: AsyncSession = Depends(get_db),
):
    """Export all non-admin users across normal + custom groups as Excel."""
    rows = await admin_service.get_users_for_export(db)
    file_bytes = _build_users_excel(rows, "All Users")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"alphasync_users_overall_{timestamp}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        BytesIO(file_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/exports/users/applied")
async def export_users_applied_excel(
    status: Optional[str] = None,
    group_id: Optional[str] = None,
    search: Optional[str] = None,
    admin: User = Depends(require_root_admin),
    db: AsyncSession = Depends(get_db),
):
    """Export currently applied user filters/group as Excel."""
    rows = await admin_service.get_users_for_export(
        db,
        status_filter=status,
        search=search,
        group_id=group_id,
    )
    file_bytes = _build_users_excel(rows, "Applied Users")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    suffix = str(group_id or "all").replace(" ", "_")
    filename = f"alphasync_users_applied_{suffix}_{timestamp}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        BytesIO(file_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/groups")
async def list_groups(
    admin: User = Depends(require_root_admin),
):
    """List custom onboarding groups. Root/Max only."""
    groups = await admin_group_service.list_groups()
    return {"groups": groups}


@router.post("/groups")
async def create_group(
    req: CreateGroupRequest,
    admin: User = Depends(require_root_admin),
):
    """Create a custom group and token for onboarding links. Root/Max only."""
    result = await admin_group_service.create_group(req.name, str(admin.id))
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to create group")
    return result


@router.post("/groups/{group_id}/generate-link")
async def generate_group_link(
    group_id: str,
    request: Request,
    admin: User = Depends(require_root_admin),
):
    """Regenerate and return a sharable onboarding link for a group. Root/Max only."""
    result = await admin_group_service.generate_group_link(group_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error") or "Group not found")

    group = result["group"]
    origin = request.headers.get("origin")
    base_url = origin or f"{request.url.scheme}://{request.url.netloc}"
    invite_url = f"{base_url}/login?grp={group['token']}"
    return {"success": True, "group": group, "invite_url": invite_url}


@router.patch("/groups/{group_id}")
async def rename_group(
    group_id: str,
    req: RenameGroupRequest,
    admin: User = Depends(require_root_admin),
):
    """Rename a custom group. Root/Max only."""
    result = await admin_group_service.rename_group(group_id, req.name)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to rename group")
    return result


@router.delete("/groups/{group_id}")
async def delete_group(
    group_id: str,
    admin: User = Depends(require_root_admin),
):
    """Delete a custom group and move its users back to normal. Root/Max only."""
    result = await admin_group_service.delete_group(group_id)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error") or "Group not found")
    return result


@router.post("/groups/{group_id}/auto-approval")
async def set_group_auto_approval(
    group_id: str,
    req: GroupAutoApprovalUpdateRequest,
    admin: User = Depends(require_root_admin),
):
    """Toggle auto-approval for one group only. Root/Max only."""
    result = await admin_group_service.set_group_auto_approval(group_id, req.enabled)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error") or "Group not found")
    return result


@router.post("/users/{user_id}/group")
async def set_user_group(
    user_id: str,
    req: SetUserGroupRequest,
    admin: User = Depends(require_root_admin),
    db: AsyncSession = Depends(get_db),
):
    """Assign user to a custom group or move back to normal. Root/Max only."""
    normalized_user_id = _normalize_user_id(user_id)
    target = await admin_service.get_user_detail(db, normalized_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    normalized_group_id = str(req.group_id or "").strip()
    if not normalized_group_id or normalized_group_id.lower() == "normal":
        result = await admin_group_service.remove_user_from_group(str(normalized_user_id))
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error") or "Failed to update group")
        return {"success": True, "group_id": None, "group_name": None}

    result = await admin_group_service.assign_user_to_group(
        str(normalized_user_id),
        normalized_group_id,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error") or "Failed to update group")

    group = result.get("group") or {}
    return {
        "success": True,
        "group_id": group.get("id"),
        "group_name": group.get("name"),
    }


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: str,
    admin: User = Depends(require_2fa_session),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed user info including portfolio and orders."""
    normalized_user_id = _normalize_user_id(user_id)
    data = await admin_service.get_user_detail(db, normalized_user_id)
    if not data:
        raise HTTPException(status_code=404, detail="User not found")
    return data


@router.post("/users/{user_id}/financials")
async def update_user_financials(
    user_id: str,
    req: UpdateFinancialsRequest,
    request: Request,
    admin: User = Depends(require_root_admin),
    db: AsyncSession = Depends(get_db),
):
    """Root-only user financial control for capital and P&L overrides."""
    normalized_user_id = _normalize_user_id(user_id)
    ip = request.client.host if request.client else None
    result = await admin_service.update_user_financials(
        db=db,
        admin_user=admin,
        target_user_id=normalized_user_id,
        available_capital=req.available_capital,
        virtual_capital=req.virtual_capital,
        total_pnl=req.total_pnl,
        total_pnl_percent=req.total_pnl_percent,
        note=req.note,
        ip=ip,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/users/{user_id}/approve")
async def approve_user(
    user_id: str,
    req: ApproveUserRequest,
    request: Request,
    admin: User = Depends(require_manage_level),
    db: AsyncSession = Depends(get_db),
):
    """Approve a pending user account with access duration."""
    normalized_user_id = _normalize_user_id(user_id)
    ip = request.client.host if request.client else None
    result = await admin_service.approve_user(
        db, admin, normalized_user_id, req.duration_days, ip
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    req: DeactivateUserRequest,
    request: Request,
    admin: User = Depends(require_manage_level),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a user account. Requires TOTP code for confirmation."""
    normalized_user_id = _normalize_user_id(user_id)
    # Require fresh TOTP for destructive actions.
    valid = await admin_2fa_service.verify_totp(db, admin, req.totp_code)
    if not valid:
        raise HTTPException(
            status_code=401, detail="Invalid TOTP code for action confirmation"
        )

    ip = request.client.host if request.client else None
    result = await admin_service.deactivate_user(
        db, admin, normalized_user_id, req.reason, ip
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/users/{user_id}/reactivate")
async def reactivate_user(
    user_id: str,
    req: ReactivateUserRequest,
    request: Request,
    admin: User = Depends(require_manage_level),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate a deactivated or expired user."""
    normalized_user_id = _normalize_user_id(user_id)
    ip = request.client.host if request.client else None
    result = await admin_service.reactivate_user(
        db, admin, normalized_user_id, req.duration_days, ip
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/users/{user_id}/set-duration")
async def set_duration(
    user_id: str,
    req: SetDurationRequest,
    request: Request,
    admin: User = Depends(require_manage_level),
    db: AsyncSession = Depends(get_db),
):
    """Set or update access duration for a user."""
    normalized_user_id = _normalize_user_id(user_id)
    ip = request.client.host if request.client else None
    result = await admin_service.set_access_duration(
        db, admin, normalized_user_id, req.duration_days, ip
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/users/{user_id}/force-logout")
async def force_logout_user(
    user_id: str,
    request: Request,
    admin: User = Depends(require_manage_level),
    db: AsyncSession = Depends(get_db),
):
    """Force logout all active sessions for a user."""
    normalized_user_id = _normalize_user_id(user_id)
    ip = request.client.host if request.client else None
    result = await admin_service.force_logout_user(db, admin, normalized_user_id, ip)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/users/{user_id}/delete")
async def delete_user_account(
    user_id: str,
    req: DeleteUserRequest,
    request: Request,
    admin: User = Depends(require_manage_level),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a user account and all linked data."""
    normalized_user_id = _normalize_user_id(user_id)
    valid = await admin_2fa_service.verify_totp(db, admin, req.totp_code)
    if not valid:
        raise HTTPException(
            status_code=401, detail="Invalid TOTP code for action confirmation"
        )
    ip = request.client.host if request.client else None
    result = await admin_service.delete_user_account(db, admin, normalized_user_id, ip)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── Admin Management (root only) ────────────────────────────────────


@router.get("/admins")
async def list_admins(
    admin: User = Depends(require_root_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all admin users. Root only."""
    admins = await admin_service.list_admins(db)
    return {"admins": admins}


@router.post("/admins/promote")
async def promote_to_admin(
    req: PromoteAdminRequest,
    request: Request,
    admin: User = Depends(require_root_admin),
    db: AsyncSession = Depends(get_db),
):
    """Promote an existing user to admin. Root only."""
    ip = request.client.host if request.client else None
    result = await admin_service.promote_to_admin(
        db, admin, req.email, req.admin_level, ip
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.patch("/admins/{admin_id}/level")
async def update_admin_level(
    admin_id: str,
    req: UpdateAdminLevelRequest,
    request: Request,
    admin: User = Depends(require_root_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update an admin's permission level. Root only."""
    ip = request.client.host if request.client else None
    result = await admin_service.update_admin_level(
        db, admin, admin_id, req.admin_level, ip
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.delete("/admins/{admin_id}")
async def revoke_admin(
    admin_id: str,
    request: Request,
    admin: User = Depends(require_root_admin),
    db: AsyncSession = Depends(get_db),
):
    """Revoke admin access — demote back to user. Root only."""
    ip = request.client.host if request.client else None
    result = await admin_service.revoke_admin(db, admin, admin_id, ip)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── Audit Log ────────────────────────────────────────────────────────


@router.get("/audit-log")
async def get_audit_log(
    page: int = 1,
    per_page: int = 50,
    admin: User = Depends(require_2fa_session),
    db: AsyncSession = Depends(get_db),
):
    """View the admin audit trail."""
    per_page = min(per_page, 200)
    return await admin_service.get_audit_log(db, page, per_page)


# ── Simulation / Data Management ──────────────────────────────────────────────

@router.post("/simulation/seed")
async def seed_simulation_ticks(
    days_ago: int = 1,
    admin: User = Depends(require_2fa_session),
):
    """
    Trigger background seeding of the historical_ticks table.
    Seeds a full trading day (9:15–15:30 IST) for 55+ symbols.
    Returns immediately; seeding runs as a background task.
    """
    import asyncio

    async def _run_seed():
        try:
            import sys, os
            sys.path.append(os.path.join(os.path.dirname(__file__), "..", "tools"))
            from tools.seed_ticks import seed_historical_ticks
            await seed_historical_ticks(days_ago=days_ago)
            logger.info(f"Admin {admin.email}: background seed completed (days_ago={days_ago})")
        except Exception as e:
            logger.error(f"Admin seed task failed: {e}", exc_info=True)

    asyncio.create_task(_run_seed())
    logger.info(f"Admin {admin.email}: initiated tick seeding (days_ago={days_ago})")
    return {
        "status": "started",
        "message": f"Seeding {days_ago} day(s) ago in background. Check server logs for progress.",
        "days_ago": days_ago,
    }


@router.get("/simulation/status")
async def simulation_status(
    admin: User = Depends(require_2fa_session),
):
    """Return current simulation engine status and DB tick counts."""
    from market_data.storage.candle_repository import candle_repository
    from market_data.replay.replay_engine import replay_engine
    from market_data.replay.tick_queue import tick_queue
    from market_data.replay.simulation_clock import simulation_clock

    symbols = await candle_repository.list_symbols()
    queue_size = await tick_queue.size()

    return {
        "engine_running": replay_engine._running,
        "subscribed_symbols": len(replay_engine._subscribed_symbols),
        "queue_size": queue_size,
        "simulation_time": simulation_clock.now().isoformat(),
        "db_symbols_with_ticks": len(symbols),
        "db_symbol_list": symbols[:50],  # cap at 50 for display
    }


@router.post("/simulation/csv-import")
async def csv_import(
    folder: str = "eq",
    date_str: Optional[str] = None,
    admin: User = Depends(require_2fa_session),
):
    """
    Import CSV files from the server's data/ directory into the tick database.
    folder: eq | fno | mcx | bfo | combined
    date_str: YYYY-MM-DD (optional filter)
    """
    from market_data.downloader.csv_loader import csv_loader
    from datetime import datetime

    date = None
    if date_str:
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="date_str must be YYYY-MM-DD")

    import asyncio

    async def _run_import():
        try:
            if date:
                count = await csv_loader.load_date(date)
            else:
                files = csv_loader.discover_files()
                count = 0
                for meta in files:
                    if folder and meta["folder"] != folder:
                        continue
                    count += await csv_loader.load_file(
                        meta["path"], meta["symbol"], meta["exchange"]
                    )
            logger.info(f"Admin {admin.email}: CSV import complete → {count} ticks")
        except Exception as e:
            logger.error(f"CSV import task failed: {e}", exc_info=True)

    asyncio.create_task(_run_import())
    return {
        "status": "started",
        "message": "CSV import running in background. Check server logs.",
        "folder": folder,
        "date_filter": date_str,
    }

