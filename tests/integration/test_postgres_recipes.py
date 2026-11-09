"""PostgreSQL integration tests for immutable recipes and build identity."""

import asyncio
import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import delete

from research_data_builder.artifacts import export_research_bundle
from research_data_builder.db.build_repositories import BuildRepository, BuildTransitionError
from research_data_builder.db.models import (
    BuildInput,
    BuildLineage,
    BuildRun,
    BuildStatus,
    DatasetRecipe,
    DatasetValidationResult,
    ExportArtifact,
    RecipeVariable,
    RecipeVersion,
    TransformationStep,
    User,
    UserSession,
)
from research_data_builder.db.output_repositories import BuildOutputRepository
from research_data_builder.db.recipe_repositories import RecipeRepository, RecipeVersionRepository
from research_data_builder.db.session import Database
from research_data_builder.engine.executor import BuildExecutor
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
from research_data_builder.recipes.planner import BuildPlanner
from research_data_builder.recipes.schemas import RecipeDefinition
from research_data_builder.validation import validate_dataset
from tests.recipes.test_schemas import valid_recipe

TEST_DATABASE_URL = os.getenv("RESEARCH_DATA_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(TEST_DATABASE_URL is None, reason="PostgreSQL test URL is not configured"),
]


class FixtureConnector:
    provider = DataProvider.WORLD_BANK
    capabilities = ProviderCapabilities(True, True, True, True)

    async def get_indicator(self, indicator_id: str) -> Indicator:
        return Indicator(
            provider=self.provider,
            provider_indicator_id=indicator_id,
            title=f"Fixture {indicator_id}",
            description="Stable fixture metadata",
            unit="percent",
            frequency=Frequency.ANNUAL,
            source_url=f"https://example.test/{indicator_id}",
        )

    async def get_observations(self, query: ObservationQuery) -> list[Observation]:
        return [
            Observation(
                provider=self.provider,
                indicator_id=query.indicator_id,
                entity_id=entity,
                period=date(2024, 12, 31),
                value=Decimal("1.25"),
                is_missing=False,
                frequency=Frequency.ANNUAL,
            )
            for entity in query.entity_ids
        ]


async def clear_recipes(database: Database) -> None:
    async with database.session() as session, session.begin():
        for model in (
            ExportArtifact,
            BuildLineage,
            DatasetValidationResult,
            BuildInput,
            BuildRun,
            TransformationStep,
            RecipeVariable,
            RecipeVersion,
            DatasetRecipe,
            UserSession,
            User,
        ):
            await session.execute(delete(model))


def test_postgres_freezes_versions_and_reuses_deterministic_builds() -> None:
    async def scenario() -> None:
        assert TEST_DATABASE_URL is not None
        database = Database(TEST_DATABASE_URL)
        await clear_recipes(database)
        payload = valid_recipe()
        payload.update(
            {
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "transformations": [],
            }
        )
        definition = RecipeDefinition.model_validate(payload)
        registry = ProviderRegistry([cast(ProviderConnector, FixtureConnector())])
        planner = BuildPlanner(registry)

        try:
            async with database.session() as session, session.begin():
                owner = User(
                    email="recipe-owner@example.com",
                    password_hash="test-only",
                    is_active=True,
                )
                session.add(owner)
                await session.flush()
                owner_id = owner.id
                recipes = RecipeRepository(session)
                versions = RecipeVersionRepository(session)
                recipe = await recipes.create(owner_id, definition)
                frozen = await versions.freeze(recipe, definition)
                duplicate = await versions.freeze(recipe, definition)
                assert frozen.created is True
                assert duplicate.created is False
                assert duplicate.version.id == frozen.version.id
                version_id = frozen.version.id
                recipe_id = recipe.id

            async with database.session() as session:
                version = await RecipeVersionRepository(session).get(version_id, owner_id)
                assert version is not None

            plan = await planner.plan(version)
            async with database.session() as session, session.begin():
                builds = BuildRepository(session)
                first = await builds.create_or_get(owner_id, version_id, plan)
                second = await builds.create_or_get(owner_id, version_id, plan)
                assert first.created is True
                assert second.created is False
                assert second.build.id == first.build.id
                build_id = first.build.id

            async with database.session() as session, session.begin():
                claimed = await BuildRepository(session).claim_execution(build_id, owner_id)
                assert claimed.status is BuildStatus.RETRIEVING

            execution = await BuildExecutor(registry).execute(version, plan)
            validation = validate_dataset(execution, definition)
            assert validation.passed is True
            with tempfile.TemporaryDirectory() as temporary_directory:
                bundle = export_research_bundle(
                    artifact_root=Path(temporary_directory),
                    build_id=build_id,
                    build_identity=plan.build_identity,
                    frame=execution.frame,
                    recipe=definition,
                    plan=plan,
                    validation=validation,
                    entity_mapping_version=execution.entity_mapping_version,
                    application_version="0.1.0",
                )
                async with database.session() as session, session.begin():
                    stored_build = await BuildRepository(session).get(build_id, owner_id)
                    assert stored_build is not None
                    await BuildRepository(session).record_execution(
                        stored_build,
                        execution,
                        preview_limit=2,
                    )
                    await BuildOutputRepository(session).record_success(
                        stored_build,
                        bundle,
                        validation,
                    )

            async with database.session() as session:
                stored_build = await BuildRepository(session).get(build_id, owner_id)
                assert stored_build is not None
                assert stored_build.row_count == 2
                assert stored_build.status.value == "succeeded"
                assert stored_build.dataset_checksum is not None
                assert stored_build.preview is not None
                assert stored_build.preview["preview_row_count"] == 2
                exports = await BuildOutputRepository(session).list_exports(build_id, owner_id)
                assert {export.name for export in exports} >= {
                    "data.csv",
                    "data.parquet",
                    "manifest.json",
                }

            async with database.session() as session, session.begin():
                with pytest.raises(BuildTransitionError, match="succeeded to retrieving"):
                    await BuildRepository(session).claim_execution(build_id, owner_id)

            changed = definition.model_copy(update={"name": "Changed draft"})
            async with database.session() as session, session.begin():
                stored_recipe = await RecipeRepository(session).get(recipe_id, owner_id)
                assert stored_recipe is not None
                await RecipeRepository(session).update(stored_recipe, changed)

            async with database.session() as session:
                version = await RecipeVersionRepository(session).get(version_id, owner_id)
                assert version is not None
                assert version.content["name"] == "European macro panel"
        finally:
            await clear_recipes(database)
            await database.dispose()

    asyncio.run(scenario())


def test_postgres_isolates_research_resources_between_users() -> None:
    async def scenario() -> None:
        assert TEST_DATABASE_URL is not None
        database = Database(TEST_DATABASE_URL)
        await clear_recipes(database)
        definition = RecipeDefinition.model_validate(valid_recipe())
        registry = ProviderRegistry([cast(ProviderConnector, FixtureConnector())])
        planner = BuildPlanner(registry)

        try:
            async with database.session() as session, session.begin():
                first_user = User(
                    email="first-owner@example.com",
                    password_hash="test-only",
                    is_active=True,
                )
                second_user = User(
                    email="second-owner@example.com",
                    password_hash="test-only",
                    is_active=True,
                )
                session.add_all([first_user, second_user])
                await session.flush()
                first_user_id = first_user.id
                second_user_id = second_user.id

                recipes = RecipeRepository(session)
                versions = RecipeVersionRepository(session)
                first_recipe = await recipes.create(first_user_id, definition)
                second_recipe = await recipes.create(second_user_id, definition)
                first_version = (await versions.freeze(first_recipe, definition)).version
                second_version = (await versions.freeze(second_recipe, definition)).version
                first_recipe_id = first_recipe.id
                second_recipe_id = second_recipe.id
                first_version_id = first_version.id
                second_version_id = second_version.id

            first_plan = await planner.plan(first_version)
            second_plan = await planner.plan(second_version)
            assert first_plan.build_identity == second_plan.build_identity

            async with database.session() as session, session.begin():
                builds = BuildRepository(session)
                first_build = (
                    await builds.create_or_get(first_user_id, first_version_id, first_plan)
                ).build
                second_build = (
                    await builds.create_or_get(second_user_id, second_version_id, second_plan)
                ).build
                first_build_id = first_build.id
                second_build_id = second_build.id
                second_export = ExportArtifact(
                    build_run_id=second_build_id,
                    name="private.csv",
                    kind="csv",
                    relative_path=f"builds/{second_build_id}/private.csv",
                    size_bytes=1,
                    sha256="a" * 64,
                )
                session.add(second_export)
                await session.flush()
                second_export_id = second_export.id

            async with database.session() as session, session.begin():
                builds = BuildRepository(session)
                claimed = await builds.claim_execution(second_build_id, second_user_id)
                await builds.fail(
                    claimed,
                    error_code="provider_timeout",
                    error_message="temporary provider failure",
                )
                retry = await builds.create_retry(claimed)
                retry_build_id = retry.id
                assert retry.attempt_number == 2
                assert retry.id != second_build_id

            assert first_build_id != second_build_id
            async with database.session() as session:
                recipes = RecipeRepository(session)
                versions = RecipeVersionRepository(session)
                builds = BuildRepository(session)
                outputs = BuildOutputRepository(session)

                assert [item.id for item in await recipes.list(first_user_id)] == [first_recipe_id]
                assert await recipes.get(second_recipe_id, first_user_id) is None
                assert await versions.get(second_version_id, first_user_id) is None
                assert await builds.get(second_build_id, first_user_id) is None
                assert await builds.get(retry_build_id, first_user_id) is None
                assert await outputs.get_export(second_export_id, first_user_id) is None

                assert await recipes.get(second_recipe_id, second_user_id) is not None
                assert await versions.get(second_version_id, second_user_id) is not None
                assert await builds.get(second_build_id, second_user_id) is not None
                stored_retry = await builds.get(retry_build_id, second_user_id)
                assert stored_retry is not None
                assert stored_retry.status is BuildStatus.PLANNED
                assert stored_retry.attempt_number == 2
                assert await outputs.get_export(second_export_id, second_user_id) is not None
        finally:
            await clear_recipes(database)
            await database.dispose()

    asyncio.run(scenario())
