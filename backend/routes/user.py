import os
import uuid
import shutil
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from database.connection import get_db
from models.user import User, UserSession
from routes.auth import get_current_user

router = APIRouter(prefix="/api/user", tags=["User"])

# ── Avatar storage config ─────────────────────────────────────────────────────
UPLOAD_DIR = "uploads/avatars"
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_SIZE_BYTES = 2 * 1024 * 1024  # 2MB


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None


@router.get("/profile")
async def get_profile(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "phone": user.phone,
        "avatar_url": user.avatar_url,
        "role": user.role,
        "virtual_capital": (
            float(user.virtual_capital) if user.virtual_capital is not None else None
        ),
        "is_verified": user.is_verified,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.put("/profile")
async def update_profile(
    req: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if req.full_name is not None:
        user.full_name = req.full_name
    if req.phone is not None:
        user.phone = req.phone
    if req.avatar_url is not None:
        user.avatar_url = req.avatar_url
    await db.commit()
    await db.refresh(user)
    return {
        "message": "Profile updated successfully",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "phone": user.phone,
            "avatar_url": user.avatar_url,
            "role": user.role,
            "virtual_capital": float(user.virtual_capital) if user.virtual_capital is not None else None,
            "is_verified": user.is_verified,
            "auth_provider": user.auth_provider,
        },
    }


# ── Avatar upload ─────────────────────────────────────────────────────────────


@router.post("/avatar")
async def upload_avatar(
    avatar: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validate content type
    if avatar.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only JPG, PNG, GIF, and WebP are allowed.",
        )

    # Read and validate size
    contents = await avatar.read()
    if len(contents) > MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=400, detail="File too large. Maximum size is 2MB."
        )

    # Delete old avatar file from disk if it exists
    if user.avatar_url:
        old_path = _url_to_path(user.avatar_url)
        if old_path and os.path.exists(old_path):
            os.remove(old_path)

    # Save new file with a unique name
    ext = _get_extension(avatar.content_type)
    filename = f"{user.id}_{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    # Build the public URL (served by FastAPI StaticFiles)
    avatar_url = f"/uploads/avatars/{filename}"

    # Persist to DB
    user.avatar_url = avatar_url
    await db.commit()

    return {"avatar_url": avatar_url}


@router.delete("/avatar")
async def delete_avatar(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.avatar_url:
        raise HTTPException(status_code=404, detail="No profile photo to remove")

    # Delete file from disk
    old_path = _url_to_path(user.avatar_url)
    if old_path and os.path.exists(old_path):
        os.remove(old_path)

    user.avatar_url = None
    await db.commit()

    return {"message": "Profile photo removed"}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_extension(content_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }.get(content_type, ".jpg")


def _url_to_path(url: str) -> Optional[str]:
    """Convert a public URL like /uploads/avatars/x.jpg to a local file path."""
    if url and url.startswith("/uploads/"):
        return url.lstrip("/")  # → uploads/avatars/x.jpg
    return None


@router.get("/sessions")
async def get_active_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return recent sessions for the current user (device/security view)."""
    now = datetime.now(timezone.utc)
    active_cutoff = now - timedelta(minutes=30)
    recent_cutoff = now - timedelta(days=30)

    result = await db.execute(
        select(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.last_seen_at >= recent_cutoff,
        )
        .order_by(UserSession.last_seen_at.desc())
    )
    sessions = result.scalars().all()

    payload = []
    active_count = 0
    for s in sessions:
        last_seen = s.last_seen_at
        is_active = bool(s.is_active and last_seen and last_seen >= active_cutoff)
        if is_active:
            active_count += 1
        payload.append(
            {
                "id": str(s.id),
                "ip_address": s.ip_address,
                "user_agent": s.user_agent,
                "first_seen_at": s.first_seen_at.isoformat() if s.first_seen_at else None,
                "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
                "is_active": is_active,
            }
        )

    return {
        "active_devices": active_count,
        "total_sessions": len(payload),
        "sessions": payload,
    }
