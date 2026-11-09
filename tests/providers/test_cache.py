"""Tests for immutable provider input caching."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from research_data_builder.db.models import ProviderInputCache
from research_data_builder.db.session import Database
from research_data_builder.providers.cache import (
    ProviderObservationCache,
    observation_from_dict,
    observation_to_dict,
)
from research_data_builder.providers.domain import (
    DataProvider,
    Frequency,
    Observation,
    ObservationQuery,
)
from research_data_builder.providers.protocol import ProviderConnector
from tests.engine.test_executor import ObservationConnector
from tests.recipes.test_api_behavior import FakeApiDatabase, session_with


def test_cached_observation_serialization_preserves_decimal_value() -> None:
    observation = Observation(
        provider=DataProvider.WORLD_BANK,
        indicator_id="TEST",
        entity_id="CZE",
        period=date(2024, 12, 31),
        value=Decimal("1.2500"),
        is_missing=False,
        unit="percent",
        frequency=Frequency.ANNUAL,
        provider_metadata={"source": "fixture"},
    )

    restored = observation_from_dict(observation_to_dict(observation))

    assert restored == observation
    assert str(restored.value) == "1.2500"


@pytest.mark.anyio
async def test_provider_cache_reuses_valid_normalized_response() -> None:
    observation = Observation(
        provider=DataProvider.WORLD_BANK,
        indicator_id="TEST",
        entity_id="CZE",
        period=date(2024, 12, 31),
        value=None,
        is_missing=True,
        frequency=Frequency.ANNUAL,
    )
    now = datetime.now(UTC)
    entry = ProviderInputCache(
        id=uuid4(),
        request_key="a" * 64,
        provider="world_bank",
        indicator_id="TEST",
        request={},
        observations=[observation_to_dict(observation)],
        response_fingerprint="b" * 64,
        observation_count=1,
        retrieved_at=now,
        expires_at=now + timedelta(hours=1),
        last_used_at=now,
        hit_count=0,
    )
    session = session_with(entry)
    connector = ObservationConnector()
    get_observations = AsyncMock()
    connector.get_observations = get_observations  # type: ignore[method-assign]
    cache = ProviderObservationCache(
        cast(Database, FakeApiDatabase(session)),
        ttl_hours=24,
    )

    result = await cache.load(
        uuid4(),
        "test_value",
        cast(ProviderConnector, connector),
        ObservationQuery(indicator_id="TEST", entity_ids=("CZE",)),
    )

    assert result == [observation]
    assert entry.hit_count == 1
    get_observations.assert_not_awaited()
    session.execute.assert_awaited_once()


@pytest.mark.anyio
async def test_provider_cache_stores_new_response_on_miss() -> None:
    lookup_session = session_with(None)
    store_session = session_with()
    connector = ObservationConnector()
    cache = ProviderObservationCache(
        cast(Database, FakeApiDatabase(lookup_session, store_session)),
        ttl_hours=24,
    )

    result = await cache.load(
        uuid4(),
        "growth",
        cast(ProviderConnector, connector),
        ObservationQuery(
            indicator_id="NY.GDP.MKTP.KD.ZG",
            entity_ids=("CZE",),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
        ),
    )

    assert len(result) == 2
    stored = next(
        call.args[0]
        for call in store_session.add.call_args_list
        if isinstance(call.args[0], ProviderInputCache)
    )
    assert stored.observation_count == 2
    assert len(stored.response_fingerprint) == 64
    store_session.execute.assert_awaited_once()
