"""Transactional persistence for editable recipes and immutable versions."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from research_data_builder.db.models import (
    DatasetRecipe,
    RecipeVariable,
    RecipeVersion,
    TransformationStep,
)
from research_data_builder.recipes.codec import canonical_recipe_hash
from research_data_builder.recipes.schemas import RecipeDefinition


@dataclass(frozen=True, slots=True)
class FrozenRecipeResult:
    """An immutable version plus whether this call created it."""

    version: RecipeVersion
    created: bool


class RecipeRepository:
    """Create, update, and retrieve mutable recipe drafts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, owner_id: UUID, definition: RecipeDefinition) -> DatasetRecipe:
        recipe = DatasetRecipe(
            owner_id=owner_id,
            name=definition.name,
            description=definition.description,
            draft_content=definition.model_dump(mode="json"),
            draft_hash=canonical_recipe_hash(definition),
        )
        self.session.add(recipe)
        await self.session.flush()
        return recipe

    async def get(self, recipe_id: UUID, owner_id: UUID) -> DatasetRecipe | None:
        return await self.session.scalar(
            select(DatasetRecipe).where(
                DatasetRecipe.id == recipe_id,
                DatasetRecipe.owner_id == owner_id,
            )
        )

    async def list(self, owner_id: UUID, *, limit: int = 100) -> list[DatasetRecipe]:
        result = await self.session.scalars(
            select(DatasetRecipe)
            .where(DatasetRecipe.owner_id == owner_id)
            .order_by(DatasetRecipe.created_at, DatasetRecipe.id)
            .limit(limit)
        )
        return list(result)

    async def update(
        self,
        recipe: DatasetRecipe,
        definition: RecipeDefinition,
    ) -> DatasetRecipe:
        recipe.name = definition.name
        recipe.description = definition.description
        recipe.draft_content = definition.model_dump(mode="json")
        recipe.draft_hash = canonical_recipe_hash(definition)
        await self.session.flush()
        return recipe


class RecipeVersionRepository:
    """Freeze and retrieve immutable, content-addressed recipe versions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def freeze(
        self,
        recipe: DatasetRecipe,
        definition: RecipeDefinition,
    ) -> FrozenRecipeResult:
        content_hash = canonical_recipe_hash(definition)
        existing = await self.session.scalar(
            select(RecipeVersion).where(
                RecipeVersion.recipe_id == recipe.id,
                RecipeVersion.content_hash == content_hash,
            )
        )
        if existing is not None:
            return FrozenRecipeResult(version=existing, created=False)

        maximum_version = await self.session.scalar(
            select(func.max(RecipeVersion.version_number)).where(
                RecipeVersion.recipe_id == recipe.id
            )
        )
        version = RecipeVersion(
            recipe_id=recipe.id,
            version_number=(maximum_version or 0) + 1,
            content=definition.model_dump(mode="json"),
            content_hash=content_hash,
        )
        self.session.add(version)
        await self.session.flush()

        for position, variable in enumerate(definition.variables):
            self.session.add(
                RecipeVariable(
                    recipe_version_id=version.id,
                    position=position,
                    provider=variable.provider.value,
                    indicator_id=variable.indicator_id,
                    output_name=variable.output_name,
                    parameters={},
                )
            )
        for position, step in enumerate(definition.transformations):
            self.session.add(
                TransformationStep(
                    recipe_version_id=version.id,
                    position=position,
                    operation=step.operation.value,
                    parameters={"variable": step.variable, **step.parameters},
                )
            )
        await self.session.flush()
        return FrozenRecipeResult(version=version, created=True)

    async def get(self, version_id: UUID, owner_id: UUID) -> RecipeVersion | None:
        return await self.session.scalar(
            select(RecipeVersion)
            .join(DatasetRecipe, DatasetRecipe.id == RecipeVersion.recipe_id)
            .where(
                RecipeVersion.id == version_id,
                DatasetRecipe.owner_id == owner_id,
            )
        )

    async def list_for_recipe(self, recipe_id: UUID, owner_id: UUID) -> list[RecipeVersion]:
        result = await self.session.scalars(
            select(RecipeVersion)
            .join(DatasetRecipe, DatasetRecipe.id == RecipeVersion.recipe_id)
            .where(
                RecipeVersion.recipe_id == recipe_id,
                DatasetRecipe.owner_id == owner_id,
            )
            .order_by(RecipeVersion.version_number)
        )
        return list(result)
