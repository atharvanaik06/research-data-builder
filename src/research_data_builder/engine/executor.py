"""Execute a resolved build plan into one deterministic research table."""

from collections.abc import Awaitable, Callable, Mapping
from datetime import date
from typing import cast

import polars as pl

from research_data_builder.db.models import RecipeVersion
from research_data_builder.engine.frequency import AggregationMethod, convert_frequency
from research_data_builder.engine.harmonize import ENTITY_MAPPING_VERSION, observations_to_long
from research_data_builder.engine.join import join_variables
from research_data_builder.engine.result import ExecutionResult
from research_data_builder.engine.transform import apply_transformations
from research_data_builder.providers.domain import (
    DataProvider,
    Frequency,
    Observation,
    ObservationQuery,
)
from research_data_builder.providers.protocol import ProviderConnector
from research_data_builder.providers.registry import ProviderRegistry
from research_data_builder.recipes.planner import BuildPlan, ResolvedBuildInput
from research_data_builder.recipes.schemas import (
    RecipeDefinition,
    TransformationOperation,
)

ObservationLoader = Callable[
    [str, ProviderConnector, ObservationQuery], Awaitable[list[Observation]]
]


class BuildExecutor:
    """Retrieve normalized inputs and execute recipe-declared table operations."""

    def __init__(
        self,
        providers: ProviderRegistry,
        observation_loader: ObservationLoader | None = None,
    ) -> None:
        self.providers = providers
        self.observation_loader = observation_loader

    async def execute(
        self,
        version: RecipeVersion,
        plan: BuildPlan,
        *,
        saved_inputs: Mapping[str, list[Observation]] | None = None,
    ) -> ExecutionResult:
        if str(version.id) != plan.recipe_version_id:
            raise ValueError("build plan does not belong to recipe version")
        if version.content_hash != plan.recipe_content_hash:
            raise ValueError("build plan recipe hash does not match frozen version")

        definition = RecipeDefinition.model_validate(version.content)
        if saved_inputs is not None and saved_inputs.keys() != {
            item.output_name for item in plan.inputs
        }:
            raise ValueError("Replay requires a saved snapshot for every planned input")
        frames: dict[str, pl.DataFrame] = {}
        for item in plan.inputs:
            saved = saved_inputs[item.output_name] if saved_inputs is not None else None
            frames[item.output_name] = await self._execute_input(definition, item, saved)

        joined, reports = join_variables(
            frames,
            keys=definition.join.keys,
            join_type=definition.join.type,
        )
        return ExecutionResult(
            frame=joined,
            join_reports=reports,
            entity_mapping_version=ENTITY_MAPPING_VERSION,
        )

    async def _execute_input(
        self,
        definition: RecipeDefinition,
        item: ResolvedBuildInput,
        saved: list[Observation] | None,
    ) -> pl.DataFrame:
        request = item.request
        query = ObservationQuery(
            indicator_id=item.indicator_id,
            entity_ids=tuple(str(value) for value in request.get("entity_ids", [])),
            start_date=date.fromisoformat(str(request["start_date"])),
            end_date=date.fromisoformat(str(request["end_date"])),
        )
        if saved is not None:
            observations = saved
            geographic = bool(query.entity_ids)
        else:
            connector = self.providers.get(DataProvider(item.provider))
            geographic = connector.capabilities.geographic_filtering
            if self.observation_loader is None:
                observations = await connector.get_observations(query)
            else:
                observations = await self.observation_loader(item.output_name, connector, query)
        frame = observations_to_long(observations, output_name=item.output_name)
        frame = self._bound_frame(frame, definition, geographic)

        source_frequency = Frequency(str(item.indicator_metadata["frequency"]))
        method = self._aggregation_method(definition, item.output_name)
        frame = convert_frequency(
            frame,
            source=source_frequency,
            target=definition.output_frequency,
            method=method,
        )
        return apply_transformations(
            frame,
            definition.transformations,
            variable=item.output_name,
        )

    @staticmethod
    def _bound_frame(
        frame: pl.DataFrame,
        definition: RecipeDefinition,
        geographic: bool,
    ) -> pl.DataFrame:
        bounded = frame.filter(
            pl.col("period").is_between(definition.start_date, definition.end_date, closed="both")
        )
        if geographic:
            bounded = bounded.filter(pl.col("entity").is_in(list(definition.entities)))
        return bounded

    @staticmethod
    def _aggregation_method(
        definition: RecipeDefinition,
        variable: str,
    ) -> AggregationMethod | None:
        for step in definition.transformations:
            if step.variable == variable and step.operation is TransformationOperation.AGGREGATE:
                return cast(AggregationMethod, step.parameters["method"])
        return None
