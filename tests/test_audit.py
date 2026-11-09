"""Tests for private audit history."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from research_data_builder.audit import AuditRepository
from research_data_builder.db.models import AuditEvent


@pytest.mark.anyio
async def test_audit_repository_records_and_lists_user_events() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    owner_id = uuid4()
    resource_id = uuid4()
    repository = AuditRepository(session)

    event = await repository.record(
        owner_id,
        "build.queued",
        "build",
        resource_id,
        details={"refresh": False},
    )

    event.id = uuid4()
    event.created_at = datetime.now(UTC)
    rows = MagicMock()
    rows.__iter__.return_value = iter([event])
    session.scalars = AsyncMock(return_value=rows)
    listed = await repository.list_for_user(owner_id)

    assert listed == [event]
    assert event.user_id == owner_id
    assert event.details == {"refresh": False}
    assert isinstance(session.add.call_args.args[0], AuditEvent)
