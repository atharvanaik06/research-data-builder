"""Authenticated audit-history API."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from research_data_builder.audit import AuditRepository
from research_data_builder.auth.dependencies import require_user
from research_data_builder.db.models import User
from research_data_builder.db.session import Database

router = APIRouter(prefix="/api/v1", tags=["audit"])
AuthenticatedUser = Annotated[User, Depends(require_user)]


class AuditEventResource(BaseModel):
    id: UUID
    actor: str
    action: str
    resource_type: str
    resource_id: UUID | None
    details: dict[str, Any]
    created_at: datetime


@router.get("/audit-events", response_model=list[AuditEventResource])
async def list_audit_events(
    request: Request,
    user: AuthenticatedUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEventResource]:
    database: Database = request.app.state.database
    async with database.session() as session:
        events = await AuditRepository(session).list_for_user(user.id, limit=limit)
        return [AuditEventResource.model_validate(item, from_attributes=True) for item in events]
