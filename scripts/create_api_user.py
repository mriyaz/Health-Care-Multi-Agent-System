"""
Create or update a HealthOS API user (stores bcrypt hash in Postgres).

Usage (from repo root, with DATABASE_URL / JWT_SECRET_KEY / SESSION_SECRET_KEY in ``.env``):

    python scripts/create_api_user.py --username admin --password '...' \\
        --tenant-id 00000000-0000-4000-8000-000000000001 --role ADMIN

Then obtain tokens::

    curl -s -X POST http://127.0.0.1:8000/auth/token \\
      -H 'Content-Type: application/x-www-form-urlencoded' \\
      -d 'username=admin&password=...'
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from api.auth.passwords import hash_password
from api.settings import Settings
from db.enums import UserRole
from db.models.user import User
from db.session import create_engine, create_session_factory


async def run(username: str, password: str, role: UserRole, tenant_id: UUID) -> None:
    settings = Settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        result = await session.execute(select(User).where(User.username == username))
        row = result.scalar_one_or_none()
        pw_hash = hash_password(password)
        if row is None:
            session.add(
                User(
                    username=username,
                    password_hash=pw_hash,
                    role=role,
                    tenant_id=tenant_id,
                )
            )
        else:
            row.password_hash = pw_hash
            row.role = role
            row.tenant_id = tenant_id
            row.is_active = True
        await session.commit()
    await engine.dispose()
    print(f"OK: user {username!r} ({role.value}) tenant {tenant_id}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or update a JWT/OAuth2 API user."
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--tenant-id",
        required=True,
        help="UUID for multi-tenant isolation (must match token tid checks).",
    )
    parser.add_argument(
        "--role",
        required=True,
        choices=[r.value for r in UserRole],
    )
    args = parser.parse_args()
    asyncio.run(
        run(
            args.username,
            args.password,
            UserRole(args.role),
            UUID(args.tenant_id),
        )
    )


if __name__ == "__main__":
    main()
