"""Versioned recipe and deterministic build-plan HTTP API."""

import mimetypes
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel

from research_data_builder.artifacts import (
    ArtifactIntegrityError,
    ArtifactLimitError,
    ArtifactNotFoundError,
    ArtifactStorage,
    ArtifactStorageError,
)
from research_data_builder.audit import AuditRepository
from research_data_builder.auth.dependencies import require_user
from research_data_builder.core.config import Settings
from research_data_builder.db.build_repositories import BuildRepository, BuildTransitionError
from research_data_builder.db.models import BuildJob, BuildRun, DatasetRecipe, RecipeVersion, User
from research_data_builder.db.output_repositories import BuildOutputRepository
from research_data_builder.db.recipe_repositories import RecipeRepository, RecipeVersionRepository
from research_data_builder.db.session import Database
from research_data_builder.jobs.repository import (
    BuildJobRepository,
    JobTransitionError,
    UserBuildLimitError,
)
from research_data_builder.provenance import compare_builds
from research_data_builder.providers.errors import ProviderConfigurationError, ProviderError
from research_data_builder.providers.registry import ProviderRegistry
from research_data_builder.recipes.codec import RecipeCodec
from research_data_builder.recipes.planner import BuildPlanner
from research_data_builder.recipes.schemas import RecipeDefinition
from research_data_builder.recipes.service import RecipeNotFoundError, RecipeService

router = APIRouter(prefix="/api/v1", tags=["recipes"])
AuthenticatedUser = Annotated[User, Depends(require_user)]


class RecipeResource(BaseModel):
    id: UUID
    name: str
    description: str | None
    draft: RecipeDefinition
    draft_hash: str


class RecipeVersionResource(BaseModel):
    id: UUID
    recipe_id: UUID
    version_number: int
    content: RecipeDefinition
    content_hash: str


class BuildResource(BaseModel):
    id: UUID
    recipe_version_id: UUID
    status: str
    build_identity: str
    attempt_number: int
    plan: dict[str, object]
    row_count: int | None = None
    execution_summary: dict[str, object] | None = None
    dataset_checksum: str | None = None
    bundle_path: str | None = None
    can_replay: bool = False
    replay_of_id: UUID | None = None
    original_dataset_checksum: str | None = None
    replay_matches: bool | None = None
    transformer_version: str | None = None
    original_transformer_version: str | None = None
    replay_version_warning: str | None = None


class BuildPreviewResource(BaseModel):
    columns: list[str]
    rows: list[dict[str, object]]
    preview_row_count: int
    total_row_count: int
    truncated: bool


class BuildJobResource(BaseModel):
    id: UUID
    build_id: UUID
    status: str
    progress: str
    attempt_count: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    force_refresh: bool = False
    error_code: str | None = None
    error_message: str | None = None


class ValidationIssueResource(BaseModel):
    code: str
    severity: str
    variable: str | None
    message: str
    details: dict[str, Any] | None


class ExportResource(BaseModel):
    id: UUID
    name: str
    kind: str
    relative_path: str
    size_bytes: int
    sha256: str


def recipe_resource(recipe: DatasetRecipe) -> RecipeResource:
    return RecipeResource(
        id=recipe.id,
        name=recipe.name,
        description=recipe.description,
        draft=RecipeDefinition.model_validate(recipe.draft_content),
        draft_hash=recipe.draft_hash,
    )


def version_resource(version: RecipeVersion) -> RecipeVersionResource:
    return RecipeVersionResource(
        id=version.id,
        recipe_id=version.recipe_id,
        version_number=version.version_number,
        content=RecipeDefinition.model_validate(version.content),
        content_hash=version.content_hash,
    )


def build_resource(build: BuildRun) -> BuildResource:
    return BuildResource(
        id=build.id,
        recipe_version_id=build.recipe_version_id,
        status=build.status.value,
        build_identity=build.build_identity,
        attempt_number=build.attempt_number,
        plan=build.plan,
        row_count=build.row_count,
        execution_summary=build.execution_summary,
        dataset_checksum=build.dataset_checksum,
        bundle_path=build.bundle_path,
        replay_of_id=build.replay_of_id,
        transformer_version=build.transformer_version,
    )


def job_resource(job: BuildJob) -> BuildJobResource:
    return BuildJobResource(
        id=job.id,
        build_id=job.build_run_id,
        status=job.status.value,
        progress=job.progress,
        attempt_count=job.attempt_count,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        cancel_requested_at=job.cancel_requested_at,
        force_refresh=bool(job.force_refresh),
        error_code=job.error_code,
        error_message=job.error_message,
    )


def enforce_recipe_size(definition: RecipeDefinition, settings: Settings) -> None:
    size = len(RecipeCodec.to_json(definition).encode("utf-8"))
    if size > settings.max_recipe_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "recipe_size_limit",
                "message": f"recipe uses {size} bytes; limit is {settings.max_recipe_bytes}",
            },
        )


@router.post("/recipes", response_model=RecipeResource, status_code=status.HTTP_201_CREATED)
async def create_recipe(
    definition: RecipeDefinition,
    request: Request,
    user: AuthenticatedUser,
) -> RecipeResource:
    database: Database = request.app.state.database
    enforce_recipe_size(definition, request.app.state.settings)
    async with database.session() as session, session.begin():
        recipe = await RecipeRepository(session).create(user.id, definition)
        await AuditRepository(session).record(user.id, "recipe.created", "recipe", recipe.id)
        return recipe_resource(recipe)


@router.post(
    "/recipes/import",
    response_model=RecipeResource,
    status_code=status.HTTP_201_CREATED,
)
async def import_recipe(
    request: Request,
    user: AuthenticatedUser,
    document: Annotated[str, Body(media_type="text/plain")],
    format: Annotated[Literal["json", "yaml"], Query()] = "yaml",
) -> RecipeResource:
    try:
        definition = (
            RecipeCodec.from_yaml(document) if format == "yaml" else RecipeCodec.from_json(document)
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    return await create_recipe(definition, request, user)


@router.get("/recipes", response_model=list[RecipeResource])
async def list_recipes(request: Request, user: AuthenticatedUser) -> list[RecipeResource]:
    database: Database = request.app.state.database
    async with database.session() as session:
        recipes = await RecipeRepository(session).list(user.id)
        return [recipe_resource(recipe) for recipe in recipes]


@router.get("/recipes/{recipe_id}", response_model=RecipeResource)
async def get_recipe(recipe_id: UUID, request: Request, user: AuthenticatedUser) -> RecipeResource:
    database: Database = request.app.state.database
    async with database.session() as session:
        recipe = await RecipeRepository(session).get(recipe_id, user.id)
        if recipe is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recipe not found")
        return recipe_resource(recipe)


@router.put("/recipes/{recipe_id}/draft", response_model=RecipeResource)
async def update_recipe(
    recipe_id: UUID,
    definition: RecipeDefinition,
    request: Request,
    user: AuthenticatedUser,
) -> RecipeResource:
    database: Database = request.app.state.database
    enforce_recipe_size(definition, request.app.state.settings)
    async with database.session() as session, session.begin():
        service = RecipeService(
            RecipeRepository(session), RecipeVersionRepository(session), user.id
        )
        try:
            recipe = await service.update(recipe_id, definition)
        except RecipeNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        await AuditRepository(session).record(user.id, "recipe.updated", "recipe", recipe.id)
        return recipe_resource(recipe)


@router.post(
    "/recipes/{recipe_id}/versions",
    response_model=RecipeVersionResource,
    status_code=status.HTTP_201_CREATED,
)
async def freeze_recipe(
    recipe_id: UUID,
    request: Request,
    response: Response,
    user: AuthenticatedUser,
) -> RecipeVersionResource:
    database: Database = request.app.state.database
    async with database.session() as session, session.begin():
        service = RecipeService(
            RecipeRepository(session), RecipeVersionRepository(session), user.id
        )
        try:
            result = await service.freeze(recipe_id)
        except RecipeNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
        if not result.created:
            response.status_code = status.HTTP_200_OK
        else:
            await AuditRepository(session).record(
                user.id,
                "recipe.version_created",
                "recipe_version",
                result.version.id,
                details={"version_number": result.version.version_number},
            )
        return version_resource(result.version)


@router.get("/recipe-versions/{version_id}", response_model=RecipeVersionResource)
async def get_recipe_version(
    version_id: UUID, request: Request, user: AuthenticatedUser
) -> RecipeVersionResource:
    database: Database = request.app.state.database
    async with database.session() as session:
        version = await RecipeVersionRepository(session).get(version_id, user.id)
        if version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version not found")
        return version_resource(version)


@router.get("/recipes/{recipe_id}/versions", response_model=list[RecipeVersionResource])
async def list_recipe_versions(
    recipe_id: UUID,
    request: Request,
    user: AuthenticatedUser,
) -> list[RecipeVersionResource]:
    database: Database = request.app.state.database
    async with database.session() as session:
        recipe = await RecipeRepository(session).get(recipe_id, user.id)
        if recipe is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="recipe not found")
        versions = await RecipeVersionRepository(session).list_for_recipe(recipe_id, user.id)
        return [version_resource(version) for version in versions]


@router.get("/recipe-versions/{version_id}/export")
async def export_recipe_version(
    version_id: UUID,
    request: Request,
    user: AuthenticatedUser,
    format: Annotated[Literal["json", "yaml"], Query()] = "yaml",
) -> Response:
    database: Database = request.app.state.database
    async with database.session() as session:
        version = await RecipeVersionRepository(session).get(version_id, user.id)
        if version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version not found")
        definition = RecipeDefinition.model_validate(version.content)
        if format == "json":
            return Response(RecipeCodec.to_json(definition), media_type="application/json")
        return Response(RecipeCodec.to_yaml(definition), media_type="application/yaml")


@router.post(
    "/recipe-versions/{version_id}/builds",
    response_model=BuildResource,
    status_code=status.HTTP_201_CREATED,
)
async def plan_build(
    version_id: UUID,
    request: Request,
    response: Response,
    user: AuthenticatedUser,
) -> BuildResource:
    database: Database = request.app.state.database
    registry: ProviderRegistry = request.app.state.provider_registry

    async with database.session() as session:
        version = await RecipeVersionRepository(session).get(version_id, user.id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version not found")

    try:
        plan = await BuildPlanner(registry).plan(version)
    except ProviderConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "provider_not_configured", "message": str(error)},
        ) from error
    except ProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "provider_resolution_failed", "message": str(error)},
        ) from error

    async with database.session() as session, session.begin():
        result = await BuildRepository(session).create_or_get(user.id, version.id, plan)
        if not result.created:
            response.status_code = status.HTTP_200_OK
        else:
            await AuditRepository(session).record(
                user.id, "build.planned", "build", result.build.id
            )
        return build_resource(result.build)


@router.get("/builds/{build_id}", response_model=BuildResource)
async def get_build(build_id: UUID, request: Request, user: AuthenticatedUser) -> BuildResource:
    database: Database = request.app.state.database
    async with database.session() as session:
        builds = BuildRepository(session)
        build = await builds.get(build_id, user.id)
        if build is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
        resource = build_resource(build)
        resource.can_replay = await builds.can_replay(build)
        if build.replay_of_id is not None:
            source = await builds.get(build.replay_of_id, user.id)
            if source is not None:
                resource.original_dataset_checksum = source.dataset_checksum
                resource.original_transformer_version = source.transformer_version
                current_version = (
                    build.transformer_version or request.app.state.settings.transformer_version
                )
                if source.transformer_version is None:
                    resource.replay_version_warning = "Original transformer version is unknown."
                elif source.transformer_version != current_version:
                    resource.replay_version_warning = (
                        f"Transformer version changed from {source.transformer_version} "
                        f"to {current_version}. Replay may produce a different dataset."
                    )
                if source.dataset_checksum and build.dataset_checksum:
                    resource.replay_matches = source.dataset_checksum == build.dataset_checksum
        return resource


@router.post(
    "/builds/{build_id}/rerun",
    response_model=BuildJobResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rerun_build(
    build_id: UUID,
    request: Request,
    user: AuthenticatedUser,
    mode: Literal["replay", "refresh"] = Query(),
) -> BuildJobResource:
    """Queue a replay or a fresh retrieval against a completed build's frozen plan."""
    database: Database = request.app.state.database
    async with database.session() as session, session.begin():
        builds = BuildRepository(session)
        source = await builds.get(build_id, user.id)
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
        try:
            build = await builds.create_rerun(source, replay=mode == "replay")
            queued = await BuildJobRepository(session).enqueue(
                build,
                force_refresh=mode == "refresh",
                max_outstanding=request.app.state.settings.max_outstanding_builds_per_user,
            )
        except UserBuildLimitError as error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "user_build_limit", "message": str(error)},
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        await AuditRepository(session).record(
            user.id,
            f"build.{mode}_queued",
            "build",
            build.id,
            details={"source_build_id": str(source.id)},
        )
        return job_resource(queued.job)


@router.post(
    "/builds/{build_id}/retry",
    response_model=BuildResource,
    status_code=status.HTTP_201_CREATED,
)
async def retry_build(
    build_id: UUID,
    request: Request,
    user: AuthenticatedUser,
) -> BuildResource:
    """Create a new immutable attempt for one failed or cancelled build."""
    database: Database = request.app.state.database
    async with database.session() as session, session.begin():
        repository = BuildRepository(session)
        build = await repository.get(build_id, user.id)
        if build is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
        try:
            retry = await repository.create_retry(build)
        except BuildTransitionError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "build_not_retryable",
                    "message": str(error),
                    "status": error.current.value,
                },
            ) from error
        await AuditRepository(session).record(
            user.id,
            "build.retry_created",
            "build",
            retry.id,
            details={"source_build_id": str(build.id), "attempt": retry.attempt_number},
        )
        return build_resource(retry)


@router.post(
    "/builds/{build_id}/execute",
    response_model=BuildJobResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_build(
    build_id: UUID,
    request: Request,
    user: AuthenticatedUser,
    refresh_provider_inputs: bool = Query(default=False),
) -> BuildJobResource:
    database: Database = request.app.state.database
    async with database.session() as session, session.begin():
        build = await BuildRepository(session).get(build_id, user.id)
        if build is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
        try:
            result = await BuildJobRepository(session).enqueue(
                build,
                force_refresh=refresh_provider_inputs,
                max_outstanding=request.app.state.settings.max_outstanding_builds_per_user,
            )
        except LookupError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="build not found"
            ) from error
        except JobTransitionError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "build_not_executable",
                    "message": str(error),
                    "status": build.status.value,
                },
            ) from error
        except UserBuildLimitError as error:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "user_build_limit", "message": str(error)},
            ) from error
        if result.created:
            await AuditRepository(session).record(
                user.id,
                "build.queued",
                "build",
                build.id,
                details={"refresh_provider_inputs": refresh_provider_inputs},
            )
        return job_resource(result.job)


@router.get("/builds/{build_id}/job", response_model=BuildJobResource)
async def get_build_job(
    build_id: UUID,
    request: Request,
    user: AuthenticatedUser,
) -> BuildJobResource:
    database: Database = request.app.state.database
    async with database.session() as session:
        job = await BuildJobRepository(session).get_for_build(build_id, user.id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
        return job_resource(job)


@router.post(
    "/builds/{build_id}/cancel",
    response_model=BuildJobResource,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_build(
    build_id: UUID,
    request: Request,
    user: AuthenticatedUser,
) -> BuildJobResource:
    """Cancel a queued build or request cancellation of a running build."""
    database: Database = request.app.state.database
    async with database.session() as session, session.begin():
        try:
            job = await BuildJobRepository(session).request_cancel(build_id, user.id)
        except LookupError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="job not found"
            ) from error
        except JobTransitionError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "build_not_cancellable", "message": str(error)},
            ) from error
        await AuditRepository(session).record(
            user.id,
            "build.cancellation_requested",
            "build",
            build_id,
            details={"job_status": job.status.value},
        )
        return job_resource(job)


@router.get("/builds/{build_id}/preview", response_model=BuildPreviewResource)
async def get_build_preview(
    build_id: UUID, request: Request, user: AuthenticatedUser
) -> BuildPreviewResource:
    database: Database = request.app.state.database
    async with database.session() as session:
        build = await BuildRepository(session).get(build_id, user.id)
        if build is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
        if build.preview is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="build preview is not ready",
            )
        return BuildPreviewResource.model_validate(build.preview)


@router.get(
    "/builds/{build_id}/validation",
    response_model=list[ValidationIssueResource],
)
async def get_build_validation(
    build_id: UUID,
    request: Request,
    user: AuthenticatedUser,
) -> list[ValidationIssueResource]:
    database: Database = request.app.state.database
    async with database.session() as session:
        build = await BuildRepository(session).get(build_id, user.id)
        if build is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
        rows = await BuildOutputRepository(session).list_validation(build_id, user.id)
        return [
            ValidationIssueResource(
                code=row.code,
                severity=row.severity,
                variable=row.variable,
                message=row.message,
                details=row.details,
            )
            for row in rows
        ]


@router.get("/builds/{build_id}/lineage")
async def get_build_lineage(
    build_id: UUID, request: Request, user: AuthenticatedUser
) -> dict[str, Any]:
    database: Database = request.app.state.database
    async with database.session() as session:
        build = await BuildRepository(session).get(build_id, user.id)
        if build is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
        lineage = await BuildOutputRepository(session).get_lineage(build_id, user.id)
        if lineage is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="lineage is not ready")
        return lineage.content


@router.get("/builds/{build_id}/exports", response_model=list[ExportResource])
async def get_build_exports(
    build_id: UUID, request: Request, user: AuthenticatedUser
) -> list[ExportResource]:
    database: Database = request.app.state.database
    async with database.session() as session:
        build = await BuildRepository(session).get(build_id, user.id)
        if build is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
        exports = await BuildOutputRepository(session).list_exports(build_id, user.id)
        return [ExportResource.model_validate(export, from_attributes=True) for export in exports]


@router.get("/exports/{export_id}/download", response_class=Response)
async def download_export(export_id: UUID, request: Request, user: AuthenticatedUser) -> Response:
    database: Database = request.app.state.database
    artifact_storage: ArtifactStorage = request.app.state.artifact_storage
    async with database.session() as session:
        export = await BuildOutputRepository(session).get_export(export_id, user.id)
        if export is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="export not found")
    try:
        content = await artifact_storage.load(export.relative_path, export.sha256)
    except ArtifactNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="artifact file not found"
        ) from None
    except ArtifactIntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="artifact checksum mismatch"
        ) from None
    except ArtifactLimitError:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="artifact exceeds the download limit",
        ) from None
    except ArtifactStorageError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="artifact storage is unavailable",
        ) from error
    async with database.session() as session, session.begin():
        await AuditRepository(session).record(
            user.id,
            "export.downloaded",
            "export",
            export.id,
            details={"name": export.name},
        )
    media_type = mimetypes.guess_type(export.name)[0] or "application/octet-stream"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{export.name}"'},
    )


@router.get("/builds/{build_id}/comparison/{other_build_id}")
async def compare_build_resources(
    build_id: UUID,
    other_build_id: UUID,
    request: Request,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    database: Database = request.app.state.database
    async with database.session() as session:
        left = await BuildRepository(session).get(build_id, user.id)
        right = await BuildRepository(session).get(other_build_id, user.id)
        if left is None or right is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
        return compare_builds(left, right)
