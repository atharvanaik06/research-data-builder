"""Versioned recipe and deterministic build-plan HTTP API."""

import hashlib
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from research_data_builder.artifacts import export_research_bundle
from research_data_builder.auth.dependencies import require_user
from research_data_builder.core.config import Settings
from research_data_builder.db.build_repositories import BuildRepository
from research_data_builder.db.models import BuildRun, DatasetRecipe, RecipeVersion, User
from research_data_builder.db.output_repositories import BuildOutputRepository
from research_data_builder.db.recipe_repositories import RecipeRepository, RecipeVersionRepository
from research_data_builder.db.session import Database
from research_data_builder.engine.executor import BuildExecutor
from research_data_builder.engine.harmonize import HarmonizationError
from research_data_builder.provenance import compare_builds
from research_data_builder.providers.errors import ProviderConfigurationError, ProviderError
from research_data_builder.providers.registry import ProviderRegistry
from research_data_builder.recipes.codec import RecipeCodec
from research_data_builder.recipes.planner import BuildPlan, BuildPlanner
from research_data_builder.recipes.schemas import RecipeDefinition
from research_data_builder.recipes.service import RecipeNotFoundError, RecipeService
from research_data_builder.validation import validate_dataset

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
    plan: dict[str, object]
    row_count: int | None = None
    execution_summary: dict[str, object] | None = None
    dataset_checksum: str | None = None
    bundle_path: str | None = None


class BuildPreviewResource(BaseModel):
    columns: list[str]
    rows: list[dict[str, object]]
    preview_row_count: int
    total_row_count: int
    truncated: bool


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
        plan=build.plan,
        row_count=build.row_count,
        execution_summary=build.execution_summary,
        dataset_checksum=build.dataset_checksum,
        bundle_path=build.bundle_path,
    )


@router.post("/recipes", response_model=RecipeResource, status_code=status.HTTP_201_CREATED)
async def create_recipe(
    definition: RecipeDefinition,
    request: Request,
    user: AuthenticatedUser,
) -> RecipeResource:
    database: Database = request.app.state.database
    async with database.session() as session, session.begin():
        recipe = await RecipeRepository(session).create(user.id, definition)
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
    async with database.session() as session, session.begin():
        service = RecipeService(
            RecipeRepository(session), RecipeVersionRepository(session), user.id
        )
        try:
            recipe = await service.update(recipe_id, definition)
        except RecipeNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
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
        return build_resource(result.build)


@router.get("/builds/{build_id}", response_model=BuildResource)
async def get_build(build_id: UUID, request: Request, user: AuthenticatedUser) -> BuildResource:
    database: Database = request.app.state.database
    async with database.session() as session:
        build = await BuildRepository(session).get(build_id, user.id)
        if build is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
        return build_resource(build)


@router.post("/builds/{build_id}/execute", response_model=BuildResource)
async def execute_build(
    build_id: UUID,
    request: Request,
    user: AuthenticatedUser,
    preview_limit: Annotated[int, Query(ge=1, le=1_000)] = 100,
) -> BuildResource:
    database: Database = request.app.state.database
    registry: ProviderRegistry = request.app.state.provider_registry
    async with database.session() as session:
        build = await BuildRepository(session).get(build_id, user.id)
        if build is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
        version = await RecipeVersionRepository(session).get(build.recipe_version_id, user.id)
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="version is unavailable"
            )

    async with database.session() as session, session.begin():
        active_build = await BuildRepository(session).get(build_id, user.id)
        if active_build is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
        await BuildRepository(session).mark_retrieving(active_build)

    try:
        plan = BuildPlan.from_dict(build.plan)
        result = await BuildExecutor(registry).execute(version, plan)
    except (ProviderError, HarmonizationError, ValueError) as error:
        async with database.session() as session, session.begin():
            failed_build = await BuildRepository(session).get(build_id, user.id)
            if failed_build is not None:
                await BuildRepository(session).fail(
                    failed_build,
                    error_code="execution_failed",
                    error_message=str(error),
                )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "execution_failed", "message": str(error)},
        ) from error

    recipe = RecipeDefinition.model_validate(version.content)
    validation = validate_dataset(result, recipe)
    if not validation.passed:
        async with database.session() as session, session.begin():
            invalid_build = await BuildRepository(session).get(build_id, user.id)
            if invalid_build is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
            await BuildRepository(session).record_execution(
                invalid_build,
                result,
                preview_limit=preview_limit,
            )
            await BuildOutputRepository(session).record_validation_failure(
                invalid_build, validation
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "validation_failed", "validation": validation.as_dict()},
        )

    settings: Settings = request.app.state.settings
    try:
        bundle = export_research_bundle(
            artifact_root=settings.artifact_root,
            build_id=build_id,
            build_identity=build.build_identity,
            frame=result.frame,
            recipe=recipe,
            plan=plan,
            validation=validation,
            entity_mapping_version=result.entity_mapping_version,
            application_version=settings.app_version,
        )
    except (OSError, ValueError) as error:
        async with database.session() as session, session.begin():
            failed_build = await BuildRepository(session).get(build_id, user.id)
            if failed_build is not None:
                await BuildRepository(session).fail(
                    failed_build,
                    error_code="export_failed",
                    error_message=str(error),
                )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "export_failed"},
        ) from error

    async with database.session() as session, session.begin():
        completed_build = await BuildRepository(session).get(build_id, user.id)
        if completed_build is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="build not found")
        await BuildRepository(session).record_execution(
            completed_build,
            result,
            preview_limit=preview_limit,
        )
        await BuildOutputRepository(session).record_success(
            completed_build,
            bundle,
            validation,
        )
        return build_resource(completed_build)


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


@router.get("/exports/{export_id}/download", response_class=FileResponse)
async def download_export(
    export_id: UUID, request: Request, user: AuthenticatedUser
) -> FileResponse:
    database: Database = request.app.state.database
    settings: Settings = request.app.state.settings
    async with database.session() as session:
        export = await BuildOutputRepository(session).get_export(export_id, user.id)
        if export is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="export not found")
    root = settings.artifact_root.expanduser().resolve()
    path = (root / export.relative_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact file not found")
    if hashlib.sha256(path.read_bytes()).hexdigest() != export.sha256:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="artifact checksum mismatch"
        )
    return FileResponse(path, filename=export.name)


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
