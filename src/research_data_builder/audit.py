"""Private audit history for user and worker actions."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from research_data_builder.db.models import AuditEvent


class AuditRepository:
    """Record and list immutable actions for one user."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        user_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        *,
        actor: str = "user",
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            user_id=user_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_for_user(self, user_id: UUID, *, limit: int = 100) -> list[AuditEvent]:
        rows = await self.session.scalars(
            select(AuditEvent)
            .where(AuditEvent.user_id == user_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(limit)
        )
        return list(rows)
