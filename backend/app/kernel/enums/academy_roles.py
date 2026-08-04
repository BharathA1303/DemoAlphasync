# app/kernel/enums/academy_roles.py — Canonical Role Definitions for AlphaSync
from enum import Enum


class AcademyRole(str, Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    FACULTY = "faculty"
    INSTITUTION_ADMIN = "institution_admin"
    SUPER_ADMIN = "super_admin"
    TRADER = "trader"


ALL_ACADEMY_ROLES = {role.value for role in AcademyRole}

FACULTY_ACADEMY_ROLES = {
    AcademyRole.TEACHER.value,
    AcademyRole.FACULTY.value,
    AcademyRole.INSTITUTION_ADMIN.value,
    AcademyRole.SUPER_ADMIN.value,
}

FACULTY_ACADEMY_ROLES_LIST = list(FACULTY_ACADEMY_ROLES)


async def get_effective_user_tenant_role(db, user_id, tenant_id=None) -> str:
    """Retrieve tenant-scoped role from UserTenantRole table, falling back to cached user.academy_role."""
    from sqlalchemy import select
    from models.tenant import UserTenantRole
    from models.user import User

    stmt = select(UserTenantRole).where(UserTenantRole.user_id == user_id)
    if tenant_id:
        stmt = stmt.where(UserTenantRole.tenant_id == tenant_id)
    res = await db.execute(stmt)
    mapping = res.scalars().first()
    if mapping:
        return mapping.role.value if hasattr(mapping.role, "value") else str(mapping.role)

    res_user = await db.execute(select(User).where(User.id == user_id))
    user = res_user.scalar_one_or_none()
    return getattr(user, "academy_role", "student") or "student"
