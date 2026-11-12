"""Show a simulated source revision and an offline replay, without a database."""

import asyncio
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import uuid4

from research_data_builder.db.models import RecipeVersion
from research_data_builder.engine.executor import BuildExecutor
from research_data_builder.provenance import dataset_checksum
from research_data_builder.providers import (
    DataProvider,
    Frequency,
    Indicator,
    Observation,
    ObservationQuery,
    ProviderCapabilities,
    ProviderConnector,
    ProviderRegistry,
)
from research_data_builder.providers.cache import observation_from_dict, observation_to_dict
from research_data_builder.recipes.codec import canonical_recipe_hash
from research_data_builder.recipes.planner import BuildPlanner
from research_data_builder.recipes.schemas import RecipeDefinition


class RevisionFixture:
    """Provide annual observations for a single country."""

    def __init__(self, provider: DataProvider, value: str) -> None:
        self.provider = provider
        self.value = Decimal(value)
        self.capabilities = ProviderCapabilities(
            True, provider is DataProvider.WORLD_BANK, True, True
        )

    async def get_indicator(self, indicator_id: str) -> Indicator:
        return Indicator(
            provider=self.provider,
            provider_indicator_id=indicator_id,
            title=indicator_id,
            description="Simulated observation",
            unit="percent",
            frequency=Frequency.ANNUAL,
            source_url="https://example.test",
        )

    async def get_observations(self, query: ObservationQuery) -> list[Observation]:
        return [
            Observation(
                provider=self.provider,
                indicator_id=query.indicator_id,
                entity_id="USA" if self.capabilities.geographic_filtering else None,
                period=date(2023, 1, 1),
                value=self.value,
                is_missing=False,
                frequency=Frequency.ANNUAL,
            )
        ]


def fixture_recipe() -> RecipeDefinition:
    return RecipeDefinition.model_validate(
        {
            "name": "US source revision demo",
            "entities": ["USA"],
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
            "output_frequency": "annual",
            "variables": [
                {
                    "provider": "world_bank",
                    "indicator_id": "NY.GDP.MKTP.KD.ZG",
                    "output_name": "gdp_growth",
                },
                {"provider": "fred", "indicator_id": "UNRATE", "output_name": "unemployment"},
            ],
            "join": {"type": "inner", "keys": ["period"]},
            "missing_values": "preserve",
            "formats": ["csv"],
        }
    )


async def main() -> None:
    definition = fixture_recipe()
    version = RecipeVersion(
        id=uuid4(),
        content=definition.model_dump(mode="json"),
        content_hash=canonical_recipe_hash(definition),
    )
    world_bank = RevisionFixture(DataProvider.WORLD_BANK, "2.5")
    fred = RevisionFixture(DataProvider.FRED, "3.6")
    registry = ProviderRegistry([cast(ProviderConnector, item) for item in (world_bank, fred)])
    plan = await BuildPlanner(registry).plan(version)
    snapshots: dict[str, list[Observation]] = {}

    async def capture(
        name: str,
        connector: ProviderConnector,
        query: ObservationQuery,
    ) -> list[Observation]:
        observations = await connector.get_observations(query)
        snapshots[name] = [observation_from_dict(observation_to_dict(row)) for row in observations]
        return observations

    original = await BuildExecutor(registry, capture).execute(version, plan)
    world_bank.value = Decimal("2.7")
    refreshed = await BuildExecutor(registry).execute(version, plan)
    replayed = await BuildExecutor(ProviderRegistry([])).execute(
        version, plan, saved_inputs=snapshots
    )
    original_hash = dataset_checksum(original.frame)
    refreshed_hash = dataset_checksum(refreshed.frame)
    replay_hash = dataset_checksum(replayed.frame)
    assert original_hash == replay_hash and original_hash != refreshed_hash
    for label, result, checksum in (
        ("Original", original, original_hash),
        ("Refreshed", refreshed, refreshed_hash),
        ("Replay", replayed, replay_hash),
    ):
        print(f"{label:9} USA 2023 GDP growth {result.frame['gdp_growth'][0]:.1f}%  {checksum}")


if __name__ == "__main__":
    asyncio.run(main())
