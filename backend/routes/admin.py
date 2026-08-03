"""
Admin Panel API — Complete user account management + admin hierarchy.

Security layers:
  1. Bearer token (local JWT) → identity verification
  2. role='admin' check → restricts to admins
  3. Admin level → root / manage / view_only permission checks
  4. Audit logging → every action recorded

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
    require_root_admin,
    require_manage_level,
    get_effective_admin_level,
)
from services import admin_service
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


class ApproveUserRequest(BaseModel):
    duration_days: int = Field(default=30, ge=1, le=365)


class DeactivateUserRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


class ReactivateUserRequest(BaseModel):
    duration_days: int = Field(default=30, ge=1, le=365)


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


class SetAcademyRoleRequest(BaseModel):
    academy_role: str = Field(
        ..., pattern=r"^(student|faculty|institution_admin|super_admin)$"
    )


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


class DataFeedSettingsUpdateRequest(BaseModel):
    """Internal simulation engine configuration. The engine runs in-process
    (no external vendor, no credentials needed) — admins just enable/disable it."""
    is_enabled: bool = False


class ZebuCredentialsRequest(BaseModel):
    """Zebu (MYNT API) credentials, used ONLY for one-off/periodic historical
    EOD import — never for a live feed, order placement, or continuous broker
    session. The internal tick simulator is unchanged; this just gives it
    real historical anchors instead of deterministic mock ones."""
    client_code: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)
    factor2: str = Field(
        ..., min_length=1,
        description=(
            "Zebu's login second factor: your account's DOB (DD-MM-YYYY) or "
            "PAN, exactly as registered with Zebu. This is NOT a TOTP/"
            "authenticator code — Zebu's API has no TOTP concept."
        ),
    )
    api_key: str = Field(..., min_length=1, description="Zebu API key (app key)")
    api_secret: str = Field(..., min_length=1, description="Zebu API secret")
    vendor_code: str = Field(..., min_length=1)
    base_url: str = Field(default="https://go.mynt.in")


class ZebuImportRequest(BaseModel):
    days: int = Field(default=90, ge=1, le=400, description="Number of trailing trading days of real EOD history to import")


# ── Dashboard ────────────────────────────────────────────────────────


@router.get("/dashboard/stats")
async def dashboard_stats(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregate dashboard statistics."""
    stats = await admin_service.get_dashboard_stats(db)
    level = get_effective_admin_level(admin)
    stats["admin_level"] = level
    return stats


@router.get("/settings/auto-approval")
async def get_auto_approval_setting(
    admin: User = Depends(get_admin_user),
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


@router.get("/settings/data-feed")
async def get_data_feed_settings(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Read current internal simulation engine settings (root / manage can view)."""
    from models.data_feed_config import DataFeedConfig
    from sqlalchemy import select

    try:
        stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
        res = await db.execute(stmt)
        config = res.scalar_one_or_none()
    except Exception as e:
        logger.warning(f"Error querying DataFeedConfig in get_data_feed_settings: {e}")
        config = None

    if not config:
        return {
            "is_enabled": True,
            "connection_status": "connected",
            "error_message": None,
        }

    return {
        "is_enabled": getattr(config, "is_enabled", True),
        "connection_status": getattr(config, "oauth_connection_status", getattr(config, "connection_status", "connected")),
        "error_message": getattr(config, "oauth_last_error", getattr(config, "error_message", None)),
    }


@router.post("/settings/data-feed")
async def update_data_feed_settings(
    req: DataFeedSettingsUpdateRequest,
    request: Request,
    admin: User = Depends(require_manage_level),
    db: AsyncSession = Depends(get_db),
):
    """Root/manage-only enable/disable of the internal simulation engine.
    Triggers a hot reload of the master data feed session.

    Enabling can involve a first-time/stale 45-day historical backfill
    (real NSE/BSE bhavcopy downloads with retries, falling back to mock
    per-exchange/day) which can legitimately take several minutes — far
    longer than any reasonable HTTP client timeout. This endpoint persists
    the enabled flag and returns immediately with status "connecting"; the
    actual reload/seed runs in the background and the admin panel polls
    GET /settings/data-feed for the real outcome, the same pattern already
    used for the Zebu historical import.
    """
    import asyncio
    from models.data_feed_config import DataFeedConfig
    from services.data_feed_session import data_feed_session_manager
    from sqlalchemy import select

    stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config:
        config = DataFeedConfig()
        db.add(config)

    config.is_enabled = req.is_enabled
    config.connection_status = "connecting" if req.is_enabled else "disconnected"
    config.error_message = None

    await db.commit()
    await db.refresh(config)

    ip = request.client.host if request.client else None
    logger.info(
        "Admin %s requested internal simulation engine enabled=%s (ip=%s); reload running in background",
        admin.email, req.is_enabled, ip,
    )

    async def _run_reload():
        from database.connection import async_session

        async with async_session() as bg_db:
            try:
                success, error_msg = await data_feed_session_manager.reload_data_feed(bg_db)
                logger.info(
                    "Admin %s: internal simulation engine reload finished (success=%s, error=%s)",
                    admin.email, success, error_msg,
                )
            except Exception as e:
                logger.error(f"Internal simulation engine reload failed: {e}", exc_info=True)
                stmt2 = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
                res2 = await bg_db.execute(stmt2)
                conf = res2.scalar_one_or_none()
                if conf:
                    conf.connection_status = "error"
                    conf.error_message = str(e)[:1000]
                    await bg_db.commit()

    asyncio.create_task(_run_reload())

    return {
        "success": True,
        "error": None,
        "config": {
            "is_enabled": config.is_enabled,
            "connection_status": config.connection_status,
            "error_message": config.error_message,
        },
        "message": (
            "Simulation engine enable requested — seeding/reload running in the "
            "background. Refresh status to see the final connected/error result."
        ) if req.is_enabled else "Simulation engine disabled.",
    }


# ── User Management (require at least 'manage' for writes) ──────────


@router.get("/users")
async def list_users(
    status: Optional[str] = None,
    group_id: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 25,
    admin: User = Depends(get_admin_user),
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
    admin: User = Depends(get_admin_user),
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
    """Deactivate a user account."""
    normalized_user_id = _normalize_user_id(user_id)

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


@router.post("/users/{user_id}/academy-role")
async def set_academy_role(
    user_id: str,
    req: SetAcademyRoleRequest,
    request: Request,
    admin: User = Depends(require_manage_level),
    db: AsyncSession = Depends(get_db),
):
    """Set a user's AlphaSync Academy role (student/faculty/institution_admin/super_admin)."""
    normalized_user_id = _normalize_user_id(user_id)
    ip = request.client.host if request.client else None
    result = await admin_service.set_academy_role(
        db, admin, normalized_user_id, req.academy_role, ip
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
    request: Request,
    admin: User = Depends(require_manage_level),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a user account and all linked data."""
    normalized_user_id = _normalize_user_id(user_id)
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
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """View the admin audit trail."""
    per_page = min(per_page, 200)
    return await admin_service.get_audit_log(db, page, per_page)


# ── Simulation / Data Management ──────────────────────────────────────────────

class SeedSimulationRequest(BaseModel):
    days: int = Field(default=40, ge=1, le=400, description="Number of trailing trading days to backfill")
    use_mock: bool = Field(
        default=False,
        description="Generate deterministic mock EOD data instead of downloading real NSE/BSE/NSE_FO bhavcopy files (index EOD data is always simulated regardless)",
    )
    try_real_first: bool = Field(
        default=True,
        description=(
            "When use_mock=False, fall back to mock data per-exchange/day if the real "
            "free NSE/BSE bhavcopy archive is unreachable or blocked for that day, "
            "instead of silently ingesting zero rows for it."
        ),
    )


@router.post("/simulation/seed")
async def seed_simulation_ticks(
    req: SeedSimulationRequest = SeedSimulationRequest(),
    admin: User = Depends(get_admin_user),
):
    """
    Trigger background backfill of the PriceData table via the internal
    data_layer ingestion pipeline (real NSE/BSE/NSE_FO bhavcopy downloads,
    or deterministic mock data when use_mock=True). Populates historical
    prices for Cash, F&O and Commodity markets — no external data vendor
    involved. Returns immediately; backfill runs as a background task.
    """
    import asyncio
    from data_layer.ingestion.run_ingestion import run_backfill

    # try_real_first only applies when attempting real data at all; if the
    # admin explicitly asked for mock-only, honor that with no fallback logic.
    effective_try_real_first = req.try_real_first and not req.use_mock

    async def _run_seed():
        try:
            logger.info(
                f"Admin {admin.email}: background EOD backfill starting "
                f"(days={req.days}, use_mock={req.use_mock}, try_real_first={effective_try_real_first})..."
            )
            await run_backfill(req.days, req.use_mock, try_real_first=effective_try_real_first)
            logger.info(f"Admin {admin.email}: background EOD backfill completed successfully.")
        except Exception as e:
            logger.error(f"Admin EOD backfill task failed: {e}", exc_info=True)

    asyncio.create_task(_run_seed())
    logger.info(f"Admin {admin.email}: initiated background EOD backfill (days={req.days}, use_mock={req.use_mock})")
    return {
        "status": "started",
        "message": f"Backfilling historical data for the last {req.days} trading days in the background. Check server logs for progress.",
    }


@router.get("/simulation/zebu-credentials")
async def get_zebu_credentials(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Read whether Zebu credentials are configured."""
    from models.data_feed_config import DataFeedConfig
    from sqlalchemy import select

    try:
        stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
        res = await db.execute(stmt)
        config = res.scalar_one_or_none()
    except Exception as e:
        logger.warning(f"Error querying DataFeedConfig in get_zebu_credentials: {e}")
        config = None

    if not config:
        return {"configured": False}

    client_code = getattr(config, "oauth_client_id", getattr(config, "broker_client_code", None))
    return {
        "configured": bool(client_code),
        "client_code": client_code,
        "base_url": getattr(config, "oauth_base_url", getattr(config, "base_url", "https://go.mynt.in")),
        "last_import_at": config.broker_last_import_at.isoformat() if getattr(config, "broker_last_import_at", None) else None,
        "last_import_status": getattr(config, "oauth_connection_status", "disconnected"),
        "last_import_error": getattr(config, "oauth_last_error", None),
        "last_import_rows": getattr(config, "broker_last_import_rows", 0),
        "last_import_symbols_found": getattr(config, "broker_last_import_symbols_found", 0),
        "last_import_symbols_total": getattr(config, "broker_last_import_symbols_total", 0),
        "import_progress_done": getattr(config, "broker_import_progress_done", 0),
        "import_progress_total": getattr(config, "broker_import_progress_total", 0),
    }


@router.post("/simulation/zebu-credentials")
async def save_zebu_credentials(
    req: ZebuCredentialsRequest,
    request: Request,
    admin: User = Depends(require_manage_level),
    db: AsyncSession = Depends(get_db),
):
    """Store Zebu (MYNT API) credentials for historical EOD import only.
    Credentials are encrypted at rest (services/crypto.py) and are never
    used for live trading, order placement, or a continuous broker session
    — only the one-off/periodic "import real historical prices" action."""
    from models.data_feed_config import DataFeedConfig
    from sqlalchemy import select

    stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config:
        config = DataFeedConfig()
        db.add(config)

    config.broker = "zebu"
    config.broker_client_code = req.client_code
    config.set_broker_password(req.password)
    config.set_broker_factor2(req.factor2)
    config.api_key = req.api_key
    config.set_api_secret(req.api_secret)
    config.broker_vendor_code = req.vendor_code
    config.base_url = req.base_url

    await db.commit()

    ip = request.client.host if request.client else None
    logger.info(f"Admin {admin.email}: saved Zebu historical-import credentials (ip={ip})")

    return {"success": True}


@router.post("/simulation/zebu-import")
async def import_zebu_history(
    req: ZebuImportRequest = ZebuImportRequest(),
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger a background import of REAL historical EOD candles from Zebu
    for the platform's seed symbol universe, upserted into price_data via
    the same versioned-upsert pipeline as the mock ingestion path. The
    internal Brownian-bridge tick simulator then generates ticks from these
    real anchors instead of deterministic mock ones — no other part of the
    pipeline changes.

    Login happens synchronously here (fast, single call) so credential
    errors (bad password/factor2/vendor code) surface immediately in the
    response instead of only showing up later as an opaque background-task
    failure. The slower bulk historical fetch then runs in the background
    with the already-authenticated session.
    """
    import asyncio
    from models.data_feed_config import DataFeedConfig
    from sqlalchemy import select
    from data_layer.ingestion.zebu_client import ZebuClient, ZebuAuthError, ZebuApiError

    stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config or config.broker != "zebu" or not config.broker_client_code:
        raise HTTPException(status_code=400, detail="Zebu credentials are not configured yet.")

    client = ZebuClient(
        client_code=config.broker_client_code,
        password=config.get_broker_password(),
        factor2=config.get_broker_factor2(),
        api_key=config.api_key,
        api_secret=config.get_api_secret(),
        vendor_code=config.broker_vendor_code,
        base_url=config.base_url,
    )
    try:
        await asyncio.to_thread(client.login)
    except ZebuAuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ZebuApiError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach Zebu: {e}")

    async def _run_import():
        from database.connection import async_session
        from data_layer.ingestion.zebu_import import run_zebu_backfill

        async def _report_progress(done: int, total: int):
            # Uses its own short-lived session — run_zebu_backfill holds its
            # own session open for the whole import for DB writes, and the
            # outer bg_db session below is only touched before/after the
            # import runs, so a shared session here would interleave badly
            # with either of those.
            async with async_session() as progress_db:
                stmt = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
                res = await progress_db.execute(stmt)
                conf = res.scalar_one_or_none()
                if conf:
                    conf.broker_import_progress_done = done
                    conf.broker_import_progress_total = total
                    await progress_db.commit()

        async with async_session() as bg_db:
            stmt2 = select(DataFeedConfig).order_by(DataFeedConfig.updated_at.desc()).limit(1)
            res2 = await bg_db.execute(stmt2)
            conf = res2.scalar_one_or_none()
            if not conf:
                return
            try:
                logger.info(f"Admin {admin.email}: Zebu historical import starting (days={req.days})...")
                result = await run_zebu_backfill(client, req.days, progress_cb=_report_progress)
                rows = result["rows_written"]
                conf.broker_last_import_rows = rows
                conf.broker_last_import_symbols_found = result["symbols_found"]
                conf.broker_last_import_symbols_total = result["symbols_total"]

                if result["symbols_found"] == 0:
                    # Login succeeded but not a single symbol resolved to a
                    # Zebu instrument token (e.g. NSE symbol master format
                    # changed, or account lacks market-data entitlement) —
                    # this is a real failure even though no exception was
                    # raised, so don't report it as "success".
                    conf.broker_last_import_status = "error"
                    conf.broker_last_import_error = (
                        "Logged in successfully, but 0 of "
                        f"{result['symbols_total']} symbols resolved to a "
                        "Zebu instrument token — no data was imported. "
                        "Check the NSE symbol master format or account "
                        "market-data entitlement."
                    )
                elif rows == 0:
                    conf.broker_last_import_status = "warning"
                    conf.broker_last_import_error = (
                        f"Resolved {result['symbols_found']}/{result['symbols_total']} "
                        "symbols but wrote 0 rows — Zebu returned no candle "
                        "data for the requested date range (check TPSeries "
                        "response / market-data entitlement)."
                    )
                else:
                    conf.broker_last_import_status = "success"
                    conf.broker_last_import_error = None
                logger.info(
                    f"Admin {admin.email}: Zebu historical import completed "
                    f"({rows} rows, {result['symbols_found']}/{result['symbols_total']} symbols)."
                )

                # Already-open simulator sessions are pinned to whatever
                # price_data version was current at subscribe-time and won't
                # pick up this import's new/corrected rows until their next
                # day-rollover — resync them now so connected users start
                # ticking the real Zebu data immediately instead of silently
                # continuing on old mock-seeded ticks.
                if rows:
                    from data_layer.simulator.simulator_manager import simulator_manager
                    resynced = await simulator_manager.resync_active_sessions_to_latest_data()
                    logger.info(f"Admin {admin.email}: resynced {resynced} active session(s) after Zebu import.")
            except Exception as e:
                conf.broker_last_import_status = "error"
                conf.broker_last_import_error = str(e)[:1000]
                logger.error(f"Zebu historical import failed: {e}", exc_info=True)
            finally:
                from datetime import datetime, timezone
                conf.broker_last_import_at = datetime.now(timezone.utc)
                # Import has reached a terminal state — clear the in-flight
                # progress counters so a stale "42/103" doesn't linger next
                # to a finished result.
                conf.broker_import_progress_done = None
                conf.broker_import_progress_total = None
                await bg_db.commit()

    config.broker_last_import_status = "importing"
    config.broker_last_import_error = None
    config.broker_import_progress_done = 0
    config.broker_import_progress_total = None
    await db.commit()

    asyncio.create_task(_run_import())
    logger.info(f"Admin {admin.email}: initiated Zebu historical import (days={req.days})")
    return {
        "status": "started",
        "message": f"Importing the last {req.days} trading days of real EOD history from Zebu in the background.",
    }


@router.post("/simulation/resync-sessions")
async def resync_simulation_sessions(
    admin: User = Depends(get_admin_user),
):
    """Force every active simulator session to re-pin to the latest
    (non-superseded) price_data version instead of waiting for its next
    day-rollover. Normally triggered automatically after a Zebu import
    completes — exposed here so an admin can retrigger it manually (e.g. a
    user subscribed mid-import, or after an import that ran outside this
    admin session)."""
    from data_layer.simulator.simulator_manager import simulator_manager

    resynced = await simulator_manager.resync_active_sessions_to_latest_data()
    logger.info(f"Admin {admin.email}: manually resynced {resynced} active session(s).")
    return {"status": "success", "resynced_sessions": resynced}


@router.get("/simulation/status")
async def simulation_status(
    admin: User = Depends(get_admin_user),
):
    """Return current simulation engine status and DB tick counts."""
    from data_layer.simulator.simulator_manager import simulator_manager as data_layer_simulator
    from market_data.replay.simulation_clock import simulation_clock
    from database.connection import async_session
    from sqlalchemy import select
    from data_layer.db.models import PriceData
    import json

    # Query active symbols from price_data
    symbols = []
    try:
        async with async_session() as db:
            stmt = select(PriceData.symbol).distinct().limit(50)
            res = await db.execute(stmt)
            symbols = list(res.scalars().all())
    except Exception as e:
        logger.warning(f"Failed to query price_data symbols: {e}")

    # Count all unique symbols
    total_symbols_count = 0
    try:
        async with async_session() as db:
            stmt = select(PriceData.symbol).distinct()
            res = await db.execute(stmt)
            total_symbols_count = len(res.scalars().all())
    except Exception as e:
        logger.warning(f"Failed to count price_data symbols: {e}")

    # Calculate active subscriptions
    active_subs = 0
    for session_id in list(data_layer_simulator.listeners.keys()):
        from data_layer.core.cache import get_cached_response
        try:
            state_raw = await get_cached_response(f"session:{session_id}")
            if state_raw:
                state = json.loads(state_raw)
                active_subs += len(state.get("subscriptions", []))
        except Exception:
            pass

    # Master provider (InternalSimProvider) health — proves ticks are
    # actually flowing right now, not just that the background loop exists.
    provider_health = None
    try:
        from services.data_feed_session import data_feed_session_manager
        master_provider = data_feed_session_manager.get_any_session()
        if master_provider is not None:
            health = await master_provider.health()
            last_tick_age_seconds = None
            if health.last_tick_at:
                from datetime import datetime as _dt, timezone as _tz
                last_tick_dt = _dt.fromisoformat(health.last_tick_at)
                last_tick_age_seconds = (_dt.now(_tz.utc) - last_tick_dt).total_seconds()
            provider_health = {
                "provider_name": health.provider_name,
                "status": health.status.value if hasattr(health.status, "value") else str(health.status),
                "subscribed_symbols": health.subscribed_symbols,
                "last_tick_at": health.last_tick_at,
                "last_tick_age_seconds": last_tick_age_seconds,
                # Ticks are expected roughly once per second; anything older
                # than a few seconds means the stream has stalled.
                "is_ticking": last_tick_age_seconds is not None and last_tick_age_seconds < 10,
                "uptime_seconds": health.uptime_seconds,
                "reconnect_count": health.reconnect_count,
                "error": health.error,
            }
    except Exception as e:
        logger.warning(f"Failed to read master provider health: {e}")

    return {
        "engine_running": data_layer_simulator.is_running,
        "subscribed_symbols": active_subs,
        "queue_size": len(data_layer_simulator.listeners),
        "simulation_time": simulation_clock.now().isoformat(),
        "simulation_clock_active": simulation_clock.is_simulated,
        "master_provider": provider_health,
        "db_symbols_with_ticks": total_symbols_count,
        "db_symbol_list": symbols,
    }


@router.post("/simulation/csv-import")
async def csv_import(
    folder: str = "eq",
    date_str: Optional[str] = None,
    admin: User = Depends(get_admin_user),
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


# ── Zebu OAuth & Time-Delayed Data Feed Routes ───────────────────────

class ZebuOAuthConfigRequest(BaseModel):
    client_id: str = Field(..., min_length=2, max_length=100)
    secret_key: str = Field(..., min_length=2, max_length=200)
    redirect_url: str = Field(..., min_length=10, max_length=500)
    base_url: str = Field(default="https://go.mynt.in", max_length=500)


class FeedDelayUpdateRequest(BaseModel):
    delay_seconds: int = Field(..., ge=0, le=86400)


class RedisPolicyUpdateRequest(BaseModel):
    active_market_hours_only: bool


@router.post("/broker/zebu/oauth/configure")
async def configure_zebu_oauth(
    body: ZebuOAuthConfigRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Save Zebu OAuth Client ID, Secret Key, and Redirect URL."""
    from models.data_feed_config import DataFeedConfig
    from sqlalchemy import select

    stmt = select(DataFeedConfig).limit(1)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config:
        config = DataFeedConfig(broker="zebu")
        db.add(config)

    config.oauth_client_id = body.client_id
    config.set_oauth_secret_key(body.secret_key)
    config.oauth_redirect_url = body.redirect_url
    config.oauth_base_url = body.base_url
    config.oauth_connection_status = "configured"
    await db.commit()

    return {"status": "success", "message": "Zebu OAuth configuration saved."}


@router.get("/broker/zebu/oauth/authorize-url")
async def get_zebu_oauth_url(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Return constructed Zebu MYNT browser authorization URL."""
    from models.data_feed_config import DataFeedConfig
    from providers.zebu_oauth_client import ZebuOAuthClient
    from sqlalchemy import select

    stmt = select(DataFeedConfig).limit(1)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config or not config.oauth_client_id:
        raise HTTPException(status_code=400, detail="Zebu OAuth client_id not configured.")

    client = ZebuOAuthClient(base_url=getattr(config, "oauth_base_url", None))
    auth_url = client.build_authorize_url(config.oauth_client_id)
    return {"authorize_url": auth_url, "client_id": config.oauth_client_id}


@router.get("/broker/zebu/oauth-callback")
async def zebu_oauth_callback(
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """Public callback route redirected to by Zebu after successful admin login."""
    from models.data_feed_config import DataFeedConfig
    from providers.zebu_oauth_client import ZebuOAuthClient
    from workers.live_feed_ingestion_worker import live_ingestion_worker
    from sqlalchemy import select
    from datetime import datetime, timezone, timedelta

    stmt = select(DataFeedConfig).limit(1)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config or not config.oauth_client_id:
        raise HTTPException(status_code=400, detail="OAuth not configured on backend.")

    secret_key = config.get_oauth_secret_key()
    client = ZebuOAuthClient(base_url=getattr(config, "oauth_base_url", None))

    try:
        token_info = await client.exchange_code_for_token(config.oauth_client_id, secret_key, code)
        config.set_oauth_access_token(token_info["access_token"])
        config.set_oauth_refresh_token(token_info["refresh_token"])
        config.oauth_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=token_info["expires_in"])
        config.oauth_connection_status = "connected"
        config.oauth_last_error = None
        await db.commit()

        # Start live ingestion worker
        asyncio.create_task(live_ingestion_worker.start())

        return {
            "status": "connected",
            "message": "Zebu OAuth authorization successful. Live ingestion started.",
        }
    except Exception as e:
        logger.error(f"Zebu OAuth callback error: {e}")
        config.oauth_connection_status = "error"
        config.oauth_last_error = str(e)
        await db.commit()
        raise HTTPException(status_code=400, detail=f"OAuth token exchange failed: {e}")


@router.post("/broker/zebu/oauth/disconnect")
async def disconnect_zebu_oauth(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Disconnect Zebu OAuth session and stop ingestion worker."""
    from models.data_feed_config import DataFeedConfig
    from workers.live_feed_ingestion_worker import live_ingestion_worker
    from sqlalchemy import select

    stmt = select(DataFeedConfig).limit(1)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if config:
        config.oauth_access_token_enc = None
        config.oauth_refresh_token_enc = None
        config.oauth_connection_status = "disconnected"
        await db.commit()

    await live_ingestion_worker.stop()
    return {"status": "disconnected", "message": "Zebu OAuth disconnected."}


@router.get("/data-feed/status")
async def get_data_feed_status(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Return data feed monitor metrics, delay configuration, and worker status."""
    from models.data_feed_config import DataFeedConfig
    from models.symbol_master import SymbolMaster
    from workers.live_feed_ingestion_worker import live_ingestion_worker
    from sqlalchemy import select, func

    config = None
    try:
        cfg_stmt = select(DataFeedConfig).limit(1)
        cfg_res = await db.execute(cfg_stmt)
        config = cfg_res.scalar_one_or_none()
    except Exception as e:
        logger.warning(f"DataFeedConfig table/column read failed in get_data_feed_status: {e}")

    active_symbols_cnt = 0
    try:
        active_symbols_cnt = await db.scalar(
            select(func.count()).select_from(SymbolMaster).where(SymbolMaster.is_active.is_(True))
        ) or 0
    except Exception as e:
        logger.warning(f"SymbolMaster table read failed in get_data_feed_status (run migration): {e}")

    worker_status = {"status": "STOPPED", "ticks_today": 0, "subscribed_symbols_count": 0}
    try:
        worker_status = live_ingestion_worker.get_status()
    except Exception as e:
        logger.warning(f"Worker status query failed: {e}")

    return {
        "connection_status": getattr(config, "oauth_connection_status", "disconnected") if config else "disconnected",
        "client_id": getattr(config, "oauth_client_id", None) if config else None,
        "feed_delay_seconds": getattr(config, "feed_delay_seconds", 300) if config else 300,
        "redis_active_market_hours_only": getattr(config, "redis_active_market_hours_only", True) if config else True,
        "active_symbols_count": active_symbols_cnt,
        "worker": worker_status,
        "token_expires_at": config.oauth_token_expires_at.isoformat() if (config and getattr(config, "oauth_token_expires_at", None)) else None,
    }


@router.put("/data-feed/delay")
async def update_feed_delay(
    body: FeedDelayUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Update feed_delay_seconds knob controlling delay across the platform."""
    from models.data_feed_config import DataFeedConfig
    from sqlalchemy import select

    stmt = select(DataFeedConfig).limit(1)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config:
        config = DataFeedConfig(broker="zebu")
        db.add(config)

    config.feed_delay_seconds = body.delay_seconds
    await db.commit()
    return {"status": "updated", "feed_delay_seconds": config.feed_delay_seconds}


@router.put("/data-feed/redis-policy")
async def update_redis_policy(
    body: RedisPolicyUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Update redis_active_market_hours_only setting."""
    from models.data_feed_config import DataFeedConfig
    from sqlalchemy import select

    stmt = select(DataFeedConfig).limit(1)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config:
        config = DataFeedConfig(broker="zebu")
        db.add(config)

    config.redis_active_market_hours_only = body.active_market_hours_only
    await db.commit()
    return {"status": "updated", "redis_active_market_hours_only": config.redis_active_market_hours_only}


@router.post("/data-feed/symbols/resync")
async def resync_symbols(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Trigger manual symbol master re-sync from local symbol files or Zebu download."""
    from pathlib import Path
    from data_layer.ingestion.zebu_symbol_master import ZebuSymbolMasterService

    symbols_dir = Path("Zebu all symbols")
    if not symbols_dir.exists():
        symbols_dir = Path("../Zebu all symbols")

    if not symbols_dir.exists():
        raise HTTPException(status_code=404, detail="Local 'Zebu all symbols' directory not found.")

    summary = await ZebuSymbolMasterService.sync_from_local_folder(db, symbols_dir)
    return {"status": "success", "synced_counts": summary}


@router.get("/data-feed/bulk-files")
async def get_bulk_files(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """List recent CSV bulk files indexed for contracts and options."""
    from models.bulk_file_index import BulkFileIndex
    from sqlalchemy import select

    try:
        stmt = select(BulkFileIndex).order_by(BulkFileIndex.created_at.desc()).limit(100)
        res = await db.execute(stmt)
        files = res.scalars().all()
        return {"files": [f.to_dict() for f in files]}
    except Exception as e:
        logger.warning(f"BulkFileIndex query failed in get_bulk_files: {e}")
        return {"files": []}



