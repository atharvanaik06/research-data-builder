"""Immutable PostgreSQL cache for normalized provider observations."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from research_data_builder.db.models import BuildInput, ProviderInputCache
from research_data_builder.db.session import Database
from research_data_builder.providers.domain import (
    DataProvider,
    Frequency,
    Observation,
    ObservationQuery,
)
from research_data_builder.providers.protocol import ProviderConnector


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def observation_to_dict(observation: Observation) -> dict[str, Any]:
    return {
        "provider": observation.provider.value,
        "indicator_id": observation.indicator_id,
        "entity_id": observation.entity_id,
        "period": observation.period.isoformat(),
        "value": str(observation.value) if observation.value is not None else None,
        "is_missing": observation.is_missing,
        "unit": observation.unit,
        "frequency": observation.frequency.value,
        "provider_metadata": observation.provider_metadata,
    }


def observation_from_dict(value: dict[str, Any]) -> Observation:
    raw_value = value.get("value")
    return Observation(
        provider=DataProvider(str(value["provider"])),
        indicator_id=str(value["indicator_id"]),
        entity_id=str(value["entity_id"]) if value.get("entity_id") is not None else None,
        period=date.fromisoformat(str(value["period"])),
        value=Decimal(str(raw_value)) if raw_value is not None else None,
        is_missing=bool(value["is_missing"]),
        unit=str(value["unit"]) if value.get("unit") is not None else None,
        frequency=Frequency(str(value["frequency"])),
        provider_metadata=dict(value.get("provider_metadata", {})),
    )


class ProviderObservationCache:
    """Load observations from a valid cache entry or retrieve a new response."""

    def __init__(self, database: Database, *, ttl_hours: int) -> None:
        self.database = database
        self.ttl = timedelta(hours=ttl_hours)

    async def load(
        self,
        build_id: UUID,
        output_name: str,
        connector: ProviderConnector,
        query: ObservationQuery,
        *,
        force_refresh: bool = False,
    ) -> list[Observation]:
        request = {
            "provider": connector.provider.value,
            "indicator_id": query.indicator_id,
            "entity_ids": list(query.entity_ids),
            "start_date": query.start_date.isoformat() if query.start_date else None,
            "end_date": query.end_date.isoformat() if query.end_date else None,
        }
        request_key = hashlib.sha256(_canonical_json(request).encode()).hexdigest()
        now = datetime.now(UTC)
        if not force_refresh:
            async with self.database.session() as session, session.begin():
                cached = await session.scalar(
                    select(ProviderInputCache)
                    .where(
                        ProviderInputCache.request_key == request_key,
                        ProviderInputCache.expires_at > now,
                    )
                    .order_by(ProviderInputCache.retrieved_at.desc())
                    .limit(1)
                )
                if cached is not None:
                    cached.hit_count += 1
                    cached.last_used_at = now
                    await self._record_use(
                        session, build_id, output_name, cached, cache_status="hit"
                    )
                    return [observation_from_dict(item) for item in cached.observations]

        observations = await connector.get_observations(query)
        serialized = [observation_to_dict(item) for item in observations]
        fingerprint = hashlib.sha256(_canonical_json(serialized).encode()).hexdigest()
        entry = ProviderInputCache(
            request_key=request_key,
            provider=connector.provider.value,
            indicator_id=query.indicator_id,
            request=request,
            observations=serialized,
            response_fingerprint=fingerprint,
            observation_count=len(serialized),
            retrieved_at=now,
            expires_at=now + self.ttl,
            last_used_at=now,
            hit_count=0,
        )
        async with self.database.session() as session, session.begin():
            session.add(entry)
            await session.flush()
            await self._record_use(
                session,
                build_id,
                output_name,
                entry,
                cache_status="refresh" if force_refresh else "miss",
            )
        return observations

    @staticmethod
    async def _record_use(
        session: Any,
        build_id: UUID,
        output_name: str,
        entry: ProviderInputCache,
        *,
        cache_status: str,
    ) -> None:
        await session.execute(
            update(BuildInput)
            .where(BuildInput.build_run_id == build_id, BuildInput.output_name == output_name)
            .values(
                cache_entry_id=entry.id,
                cache_status=cache_status,
                retrieved_at=entry.retrieved_at,
            )
        )
