"""
Grant or revoke admin role for a user account.

Usage:
  python tools/set_admin_role.py --email admin@example.com --role admin
  python tools/set_admin_role.py --email user@example.com --role user
"""

import argparse
import asyncio

from sqlalchemy import select

from database.connection import async_session_factory
from models.user import User


async def set_role(email: str, role: str) -> int:
    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            print(f"User not found: {email}")
            return 1

        user.role = role
        await db.commit()

        print(f"Updated role for {email} to {role}")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Set AlphaSync user role")
    parser.add_argument("--email", required=True, help="User email to update")
    parser.add_argument(
        "--role",
        required=True,
        choices=["admin", "user"],
        help="Target role",
    )

    args = parser.parse_args()
    return asyncio.run(set_role(args.email.strip().lower(), args.role))


if __name__ == "__main__":
    raise SystemExit(main())
