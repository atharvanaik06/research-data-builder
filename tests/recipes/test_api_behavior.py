"""Behavioral tests for recipe and deterministic build API operations."""

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from research_data_builder.api.recipes import (
    cancel_build,
    compare_build_resources,
    create_recipe,
    download_export,
    enforce_recipe_size,
    execute_build,
    export_recipe_version,
    freeze_recipe,
    get_build,
    get_build_exports,
    get_build_job,
    get_build_lineage,
    get_build_validation,
    get_recipe,
    get_recipe_version,
    import_recipe,
    list_recipe_versions,
    list_recipes,
    plan_build,
    retry_build,
    update_recipe,
)
from research_data_builder.artifacts import ArtifactStorage, create_artifact_storage
from research_data_builder.core.config import Settings
from research_data_builder.db.models import (
    BuildInput,
    BuildJob,
    BuildLineage,
    BuildRun,
    BuildStatus,
    DatasetRecipe,
    DatasetValidationResult,
    ExportArtifact,
    JobStatus,
    RecipeVersion,
    User,
)
from research_data_builder.providers import (
    DataProvider,
    Frequency,
    Indicator,
    ProviderCapabilities,
    ProviderConnector,
    ProviderRegistry,
)
from research_data_builder.recipes.codec import canonical_recipe_hash
from research_data_builder.recipes.schemas import RecipeDefinition
from tests.engine.test_executor import version_and_plan
from tests.recipes.test_schemas import valid_recipe

TEST_USER = User(
    id=uuid4(),
    email="owner@example.com",
    password_hash="test-only",
    is_active=True,
)


class TransactionContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


def session_with(*scalar_values: object) -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.scalar = AsyncMock(side_effect=list(scalar_values))
    session.scalars = AsyncMock()
    session.execute = AsyncMock()
    session.begin.return_value = TransactionContext()

    def assign_id(model: Any) -> None:
        if hasattr(model, "id") and model.id is None:
            model.id = uuid4()
        if isinstance(model, BuildJob) and model.created_at is None:
            model.created_at = datetime.now(UTC)

    session.add.side_effect = assign_id
    return session


class FakeApiDatabase:
    def __init__(self, *sessions: MagicMock) -> None:
        self.sessions = iter(sessions)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[MagicMock]:
        yield next(self.sessions)


class ApiConnector:
    provider = DataProvider.WORLD_BANK
    capabilities = ProviderCapabilities(True, True, True, True)

    async def get_indicator(self, indicator_id: str) -> Indicator:
        return Indicator(
            provider=self.provider,
            provider_indicator_id=indicator_id,
            title=f"Indicator {indicator_id}",
            description="Fixture",
            unit="percent",
            frequency=Frequency.ANNUAL,
            source_url="https://example.test",
        )


def api_request(
    database: FakeApiDatabase,
    *,
    registry: ProviderRegistry | None = None,
    settings: Settings | None = None,
    artifact_storage: ArtifactStorage | None = None,
) -> Request:
    resolved_settings = settings or Settings(_env_file=None)  # type: ignore[call-arg]
    state = SimpleNamespace(
        database=database,
        provider_registry=registry or ProviderRegistry([]),
        settings=resolved_settings,
        artifact_storage=artifact_storage or create_artifact_storage(resolved_settings),
    )
    return cast(Request, SimpleNamespace(app=SimpleNamespace(state=state)))


def stored_recipe(definition: RecipeDefinition) -> DatasetRecipe:
    return DatasetRecipe(
        id=uuid4(),
        owner_id=TEST_USER.id,
        name=definition.name,
        description=definition.description,
        draft_content=definition.model_dump(mode="json"),
        draft_hash=canonical_recipe_hash(definition),
    )


def stored_version(recipe: DatasetRecipe, definition: RecipeDefinition) -> RecipeVersion:
    return RecipeVersion(
        id=uuid4(),
        recipe_id=recipe.id,
        version_number=1,
        content=definition.model_dump(mode="json"),
        content_hash=canonical_recipe_hash(definition),
    )


@pytest.mark.anyio
async def test_recipe_api_creates_imports_reads_lists_and_updates_drafts() -> None:
    definition = RecipeDefinition.model_validate(valid_recipe())

    created = await create_recipe(
        definition, api_request(FakeApiDatabase(session_with())), TEST_USER
    )
    assert created.name == "European macro panel"

    imported = await import_recipe(
        api_request(FakeApiDatabase(session_with())),
        TEST_USER,
        document="""
name: Imported
entities: [CZE]
start_date: 2020-01-01
end_date: 2021-12-31
variables:
  - provider: world_bank
    indicator_id: SP.POP.TOTL
    output_name: population
output_frequency: annual
""",
        format="yaml",
    )
    assert imported.name == "Imported"

    recipe = stored_recipe(definition)
    fetched = await get_recipe(
        recipe.id, api_request(FakeApiDatabase(session_with(recipe))), TEST_USER
    )
    assert fetched.id == recipe.id

    scalar_result = MagicMock()
    scalar_result.__iter__.return_value = iter([recipe])
    list_session = session_with()
    list_session.scalars.return_value = scalar_result
    listed = await list_recipes(api_request(FakeApiDatabase(list_session)), TEST_USER)
    assert [item.id for item in listed] == [recipe.id]

    updated_definition = definition.model_copy(update={"name": "Updated"})
    updated = await update_recipe(
        recipe.id,
        updated_definition,
        api_request(FakeApiDatabase(session_with(recipe))),
        TEST_USER,
    )
    assert updated.name == "Updated"

    with pytest.raises(HTTPException) as invalid_import:
        await import_recipe(
            api_request(FakeApiDatabase()),
            TEST_USER,
            document="not: [valid",
            format="yaml",
        )
    assert invalid_import.value.status_code == 422


@pytest.mark.anyio
async def test_recipe_api_freezes_lists_and_exports_versions() -> None:
    definition = RecipeDefinition.model_validate(valid_recipe())
    recipe = stored_recipe(definition)
    freeze_session = session_with(recipe, None, 0)

    frozen = await freeze_recipe(
        recipe.id,
        api_request(FakeApiDatabase(freeze_session)),
        Response(),
        TEST_USER,
    )
    assert frozen.version_number == 1

    version = stored_version(recipe, definition)
    fetched = await get_recipe_version(
        version.id, api_request(FakeApiDatabase(session_with(version))), TEST_USER
    )
    assert fetched.content_hash == version.content_hash

    scalar_result = MagicMock()
    scalar_result.__iter__.return_value = iter([version])
    list_session = session_with(recipe)
    list_session.scalars.return_value = scalar_result
    versions = await list_recipe_versions(
        recipe.id, api_request(FakeApiDatabase(list_session)), TEST_USER
    )
    assert [item.id for item in versions] == [version.id]

    exported = await export_recipe_version(
        version.id,
        api_request(FakeApiDatabase(session_with(version))),
        TEST_USER,
        format="json",
    )
    assert exported.media_type == "application/json"
    assert b'"name": "European macro panel"' in exported.body


@pytest.mark.anyio
async def test_build_api_resolves_persists_reuses_and_reads_plans() -> None:
    definition = RecipeDefinition.model_validate(valid_recipe())
    recipe = stored_recipe(definition)
    version = stored_version(recipe, definition)
    registry = ProviderRegistry([cast(ProviderConnector, ApiConnector())])

    planned = await plan_build(
        version.id,
        api_request(FakeApiDatabase(session_with(version), session_with(None)), registry=registry),
        Response(),
        TEST_USER,
    )
    assert planned.status == "planned"
    assert len(planned.build_identity) == 64

    build = BuildRun(
        id=uuid4(),
        owner_id=TEST_USER.id,
        recipe_version_id=version.id,
        status=BuildStatus.PLANNED,
        build_identity="a" * 64,
        attempt_number=1,
        plan={"inputs": []},
    )
    fetched = await get_build(
        build.id, api_request(FakeApiDatabase(session_with(build))), TEST_USER
    )
    assert fetched.id == build.id


@pytest.mark.anyio
async def test_build_api_queues_and_returns_background_job() -> None:
    version, plan = version_and_plan()
    build = BuildRun(
        id=uuid4(),
        owner_id=TEST_USER.id,
        recipe_version_id=version.id,
        status=BuildStatus.PLANNED,
        build_identity=plan.build_identity,
        attempt_number=1,
        plan=plan.as_dict(),
    )
    queue_session = session_with(build, build, None, 0)

    queued = await execute_build(
        build.id,
        api_request(FakeApiDatabase(queue_session)),
        TEST_USER,
    )

    assert queued.status == "queued"
    assert queued.progress == "queued"
    assert queued.attempt_count == 0
    assert build.status is BuildStatus.QUEUED

    stored_job = next(
        call.args[0]
        for call in queue_session.add.call_args_list
        if isinstance(call.args[0], BuildJob)
    )
    fetched = await get_build_job(
        build.id,
        api_request(FakeApiDatabase(session_with(stored_job))),
        TEST_USER,
    )
    assert fetched.id == queued.id

    duplicate = await execute_build(
        build.id,
        api_request(FakeApiDatabase(session_with(build, build, stored_job))),
        TEST_USER,
    )
    assert duplicate.id == queued.id

    completed = BuildRun(
        id=uuid4(),
        owner_id=TEST_USER.id,
        recipe_version_id=version.id,
        status=BuildStatus.SUCCEEDED,
        build_identity=plan.build_identity,
        attempt_number=2,
        plan=plan.as_dict(),
    )
    with pytest.raises(HTTPException) as immutable:
        await execute_build(
            completed.id,
            api_request(FakeApiDatabase(session_with(completed, completed, None))),
            TEST_USER,
        )
    assert immutable.value.status_code == 409
    detail = cast(dict[str, object], immutable.value.detail)
    assert detail["code"] == "build_not_executable"
    assert detail["status"] == "succeeded"


@pytest.mark.anyio
async def test_build_api_cancels_owned_queued_job() -> None:
    build = BuildRun(
        id=uuid4(),
        owner_id=TEST_USER.id,
        recipe_version_id=uuid4(),
        status=BuildStatus.QUEUED,
        build_identity="a" * 64,
        attempt_number=1,
        plan={"inputs": []},
    )
    job = BuildJob(
        id=uuid4(),
        build_run_id=build.id,
        status=JobStatus.QUEUED,
        progress="queued",
        attempt_count=0,
        max_attempts=3,
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )

    response = await cancel_build(
        build.id,
        api_request(FakeApiDatabase(session_with(job, build))),
        TEST_USER,
    )

    assert response.status == "cancelled"
    assert response.progress == "cancelled"
    assert build.status is BuildStatus.CANCELLED


@pytest.mark.anyio
async def test_build_api_enforces_user_outstanding_job_limit() -> None:
    version, plan = version_and_plan()
    build = BuildRun(
        id=uuid4(),
        owner_id=TEST_USER.id,
        recipe_version_id=version.id,
        status=BuildStatus.PLANNED,
        build_identity=plan.build_identity,
        attempt_number=1,
        plan=plan.as_dict(),
    )
    session = session_with(build, build, None, 5)

    with pytest.raises(HTTPException) as limited:
        await execute_build(
            build.id,
            api_request(FakeApiDatabase(session)),
            TEST_USER,
        )

    assert limited.value.status_code == 429
    assert cast(dict[str, str], limited.value.detail)["code"] == "user_build_limit"


def test_recipe_size_limit_rejects_large_valid_definition() -> None:
    payload = valid_recipe()
    payload["description"] = "x" * 1000
    definition = RecipeDefinition.model_validate(payload)

    with pytest.raises(HTTPException) as limited:
        enforce_recipe_size(
            definition,
            Settings(max_recipe_bytes=1024, _env_file=None),  # type: ignore[call-arg]
        )

    assert limited.value.status_code == 413


@pytest.mark.anyio
async def test_build_api_retries_failure_as_new_numbered_attempt() -> None:
    version, plan = version_and_plan()
    failed = BuildRun(
        id=uuid4(),
        owner_id=TEST_USER.id,
        recipe_version_id=version.id,
        status=BuildStatus.FAILED,
        build_identity=plan.build_identity,
        attempt_number=1,
        plan=plan.as_dict(),
    )
    source_input = BuildInput(
        build_run_id=failed.id,
        output_name="gdp_growth",
        provider="world_bank",
        indicator_id="NY.GDP.MKTP.KD.ZG",
        request={"entity_ids": ["CZE"]},
        indicator_metadata={"title": "GDP growth"},
        indicator_fingerprint="a" * 64,
    )
    session = session_with(failed, 1)
    input_rows = MagicMock()
    input_rows.__iter__.return_value = iter([source_input])
    session.scalars.return_value = input_rows

    retried = await retry_build(
        failed.id,
        api_request(FakeApiDatabase(session)),
        TEST_USER,
    )

    assert retried.id != failed.id
    assert retried.status == "planned"
    assert retried.attempt_number == 2
    assert failed.status is BuildStatus.FAILED


@pytest.mark.anyio
async def test_recipe_api_returns_not_found_errors() -> None:
    missing_id = uuid4()
    with pytest.raises(HTTPException) as missing_recipe:
        await get_recipe(missing_id, api_request(FakeApiDatabase(session_with(None))), TEST_USER)
    assert missing_recipe.value.status_code == 404

    with pytest.raises(HTTPException) as missing_version:
        await get_recipe_version(
            missing_id, api_request(FakeApiDatabase(session_with(None))), TEST_USER
        )
    assert missing_version.value.status_code == 404

    with pytest.raises(HTTPException) as missing_build:
        await get_build(missing_id, api_request(FakeApiDatabase(session_with(None))), TEST_USER)
    assert missing_build.value.status_code == 404


@pytest.mark.anyio
async def test_output_apis_return_validation_lineage_exports_and_comparison(
    tmp_path: Path,
) -> None:
    left = BuildRun(
        id=uuid4(),
        owner_id=TEST_USER.id,
        recipe_version_id=uuid4(),
        status=BuildStatus.SUCCEEDED,
        build_identity="a" * 64,
        plan={"recipe_content_hash": "b" * 64, "inputs": []},
        dataset_checksum="c" * 64,
    )
    right = BuildRun(
        id=uuid4(),
        owner_id=TEST_USER.id,
        recipe_version_id=uuid4(),
        status=BuildStatus.SUCCEEDED,
        build_identity="d" * 64,
        plan={"recipe_content_hash": "b" * 64, "inputs": []},
        dataset_checksum="c" * 64,
    )
    validation = DatasetValidationResult(
        id=uuid4(),
        build_run_id=left.id,
        code="validation_passed",
        severity="info",
        message="passed",
    )
    lineage = BuildLineage(id=uuid4(), build_run_id=left.id, content={"columns": []})
    content = b"entity,period\nCZE,2024-01-01\n"
    relative_path = f"builds/{left.id}/data.csv"
    file_path = tmp_path / relative_path
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(content)
    export = ExportArtifact(
        id=uuid4(),
        build_run_id=left.id,
        name="data.csv",
        kind="csv",
        relative_path=relative_path,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )

    validation_session = session_with(left)
    validation_rows = MagicMock()
    validation_rows.__iter__.return_value = iter([validation])
    validation_session.scalars.return_value = validation_rows
    issues = await get_build_validation(
        left.id, api_request(FakeApiDatabase(validation_session)), TEST_USER
    )
    assert issues[0].code == "validation_passed"

    lineage_response = await get_build_lineage(
        left.id,
        api_request(FakeApiDatabase(session_with(left, lineage))),
        TEST_USER,
    )
    assert lineage_response == {"columns": []}

    export_session = session_with(left)
    export_rows = MagicMock()
    export_rows.__iter__.return_value = iter([export])
    export_session.scalars.return_value = export_rows
    exports = await get_build_exports(
        left.id, api_request(FakeApiDatabase(export_session)), TEST_USER
    )
    assert exports[0].sha256 == export.sha256

    response = await download_export(
        export.id,
        api_request(
            FakeApiDatabase(session_with(export), session_with()),
            settings=Settings(artifact_root=tmp_path, _env_file=None),  # type: ignore[call-arg]
        ),
        TEST_USER,
    )
    assert response.headers["content-disposition"] == 'attachment; filename="data.csv"'
    assert response.body == content

    comparison = await compare_build_resources(
        left.id,
        right.id,
        api_request(FakeApiDatabase(session_with(left, right))),
        TEST_USER,
    )
    assert comparison["same_dataset"] is True
