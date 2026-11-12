"""End-to-end fixture execution across retrieval, harmonization, and joins."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest

from research_data_builder.db.models import RecipeVersion
from research_data_builder.engine.executor import BuildExecutor
from research_data_builder.provenance import dataset_checksum
from research_data_builder.providers import (
    DataProvider,
    Frequency,
    Observation,
    ObservationQuery,
    ProviderCapabilities,
    ProviderConnector,
    ProviderRegistry,
)
from research_data_builder.recipes.codec import canonical_recipe_hash
from research_data_builder.recipes.planner import BuildPlan, ResolvedBuildInput
from research_data_builder.recipes.schemas import RecipeDefinition
from tests.recipes.test_schemas import valid_recipe


class ObservationConnector:
    provider = DataProvider.WORLD_BANK
    capabilities = ProviderCapabilities(True, True, True, True)

    async def get_observations(self, query: ObservationQuery) -> list[Observation]:
        values = {
            "NY.GDP.MKTP.KD.ZG": {"CZE": "2.5", "DEU": "1.5"},
            "FP.CPI.TOTL.ZG": {"DEU": "3.0"},
        }[query.indicator_id]
        return [
            Observation(
                provider=self.provider,
                indicator_id=query.indicator_id,
                entity_id=entity,
                period=date(2024, 12, 31),
                value=Decimal(value),
                is_missing=False,
                frequency=Frequency.ANNUAL,
            )
            for entity, value in values.items()
        ]


def version_and_plan() -> tuple[RecipeVersion, BuildPlan]:
    definition = RecipeDefinition.model_validate(valid_recipe()).model_copy(
        update={"transformations": ()}
    )
    version = RecipeVersion(
        id=uuid4(),
        recipe_id=uuid4(),
        version_number=1,
        content=definition.model_dump(mode="json"),
        content_hash=canonical_recipe_hash(definition),
    )
    inputs = tuple(
        ResolvedBuildInput(
            output_name=variable.output_name,
            provider=variable.provider.value,
            indicator_id=variable.indicator_id,
            request={
                "indicator_id": variable.indicator_id,
                "entity_ids": list(definition.entities),
                "start_date": definition.start_date.isoformat(),
                "end_date": definition.end_date.isoformat(),
            },
            indicator_metadata={"frequency": "annual"},
            indicator_fingerprint="a" * 64,
        )
        for variable in definition.variables
    )
    plan = BuildPlan(
        recipe_version_id=str(version.id),
        recipe_content_hash=version.content_hash,
        build_identity="b" * 64,
        planner_version="1",
        inputs=inputs,
    )
    return version, plan


@pytest.mark.anyio
async def test_executor_builds_stable_wide_table_and_explains_unmatched_rows() -> None:
    version, plan = version_and_plan()
    registry = ProviderRegistry([cast(ProviderConnector, ObservationConnector())])

    result = await BuildExecutor(registry).execute(version, plan)

    assert result.frame.columns == ["entity", "period", "gdp_growth", "inflation"]
    assert result.frame["entity"].to_list() == ["CZE", "DEU"]
    assert result.frame["inflation"].to_list() == [None, Decimal("3.0000000000")]
    assert result.join_reports[0].left_only_keys == 1
    assert result.join_reports[0].right_only_keys == 0


@pytest.mark.anyio
async def test_outer_join_hash_matches_for_omitted_and_explicit_null_cells() -> None:
    version, plan = version_and_plan()
    connector = ObservationConnector()
    snapshots = {
        item.output_name: await connector.get_observations(
            ObservationQuery(indicator_id=item.indicator_id)
        )
        for item in plan.inputs
    }
    executor = BuildExecutor(ProviderRegistry([]))
    omitted = await executor.execute(version, plan, saved_inputs=snapshots)
    snapshots["inflation"].append(
        replace(snapshots["inflation"][0], entity_id="CZE", value=None, is_missing=True)
    )
    explicit_null = await executor.execute(version, plan, saved_inputs=snapshots)

    assert omitted.join_reports != explicit_null.join_reports
    assert dataset_checksum(omitted.frame) == dataset_checksum(explicit_null.frame)
