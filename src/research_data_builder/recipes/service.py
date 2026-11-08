"""Application service for validated drafts and immutable recipe versions."""

from uuid import UUID

from research_data_builder.db.models import DatasetRecipe
from research_data_builder.db.recipe_repositories import (
    FrozenRecipeResult,
    RecipeRepository,
    RecipeVersionRepository,
)
from research_data_builder.recipes.schemas import RecipeDefinition


class RecipeNotFoundError(LookupError):
    """A requested recipe draft does not exist."""


class RecipeService:
    """Own validation boundaries while repositories own persistence details."""

    def __init__(
        self,
        recipes: RecipeRepository,
        versions: RecipeVersionRepository,
        owner_id: UUID,
    ) -> None:
        self.recipes = recipes
        self.versions = versions
        self.owner_id = owner_id

    async def create(self, definition: RecipeDefinition) -> DatasetRecipe:
        return await self.recipes.create(self.owner_id, definition)

    async def update(self, recipe_id: UUID, definition: RecipeDefinition) -> DatasetRecipe:
        recipe = await self._required_recipe(recipe_id)
        return await self.recipes.update(recipe, definition)

    async def freeze(self, recipe_id: UUID) -> FrozenRecipeResult:
        recipe = await self._required_recipe(recipe_id)
        definition = RecipeDefinition.model_validate(recipe.draft_content)
        return await self.versions.freeze(recipe, definition)

    async def _required_recipe(self, recipe_id: UUID) -> DatasetRecipe:
        recipe = await self.recipes.get(recipe_id, self.owner_id)
        if recipe is None:
            raise RecipeNotFoundError(f"recipe not found: {recipe_id}")
        return recipe
