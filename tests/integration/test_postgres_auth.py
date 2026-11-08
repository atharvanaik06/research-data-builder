"""PostgreSQL integration tests for account and session invariants."""

import asyncio
import os

import pytest
from sqlalchemy import delete

from research_data_builder.auth import AuthenticationError, AuthService
from research_data_builder.auth.repository import AuthRepository
from research_data_builder.db.models import User, UserSession
from research_data_builder.db.session import Database

TEST_DATABASE_URL = os.getenv("RESEARCH_DATA_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(TEST_DATABASE_URL is None, reason="PostgreSQL test URL is not configured"),
]


def test_postgres_stores_hashed_credentials_and_revokes_sessions() -> None:
    async def scenario() -> None:
        assert TEST_DATABASE_URL is not None
        database = Database(TEST_DATABASE_URL)
        try:
            async with database.session() as session, session.begin():
                existing = await AuthRepository(session).get_user_by_email("researcher@example.com")
                if existing is not None:
                    await session.execute(
                        delete(UserSession).where(UserSession.user_id == existing.id)
                    )
                    await session.execute(delete(User).where(User.id == existing.id))

            async with database.session() as session, session.begin():
                result = await AuthService(AuthRepository(session), session_ttl_hours=24).register(
                    "Researcher@Example.com", "a secure password"
                )
                user_id = result.user.id
                raw_token = result.token

            async with database.session() as session:
                user = await AuthRepository(session).get_user_by_email("researcher@example.com")
                assert user is not None
                assert user.id == user_id
                assert user.password_hash != "a secure password"
                assert raw_token not in user.password_hash

            async with database.session() as session, session.begin():
                service = AuthService(AuthRepository(session), session_ttl_hours=24)
                authenticated = await service.authenticate(raw_token)
                assert authenticated.id == user_id
                assert await service.logout(raw_token) is True

            async with database.session() as session, session.begin():
                with pytest.raises(AuthenticationError):
                    await AuthService(AuthRepository(session), session_ttl_hours=24).authenticate(
                        raw_token
                    )
        finally:
            await database.dispose()

    asyncio.run(scenario())
