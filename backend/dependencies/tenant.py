# dependencies/tenant.py - Tenant resolution and RLS context dependency
import uuid
import logging
from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from database.connection import get_db, set_tenant_context

logger = logging.getLogger(__name__)


async def get_current_tenant_id(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
) -> Optional[uuid.UUID]:
    """Resolves the tenant ID from request context (Header / Token)."""
    if not x_tenant_id:
        return None
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Tenant-ID UUID format: {x_tenant_id}",
        )


async def get_tenant_db(
    tenant_id: Optional[uuid.UUID] = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> AsyncSession:
    """FastAPI DB Session dependency that automatically sets PostgreSQL app.current_tenant_id
    and session.info['tenant_id'] for strict multi-tenant RLS isolation.
    """
    if tenant_id:
        await set_tenant_context(db, tenant_id)
    return db
