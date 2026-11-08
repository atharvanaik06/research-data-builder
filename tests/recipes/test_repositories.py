"""Tests for draft persistence and content-addressed version freezing."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from research_data_builder.db.models import DatasetRecipe, RecipeVariable, TransformationStep
from research_data_builder.db.recipe_repositories import RecipeRepository, RecipeVersionRepository
from research_data_builder.recipes.schemas import RecipeDefinition
from research_data_builder.recipes.service import RecipeNotFoundError, RecipeService
from tests.recipes.test_schemas import valid_recipe


def mock_session() -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.scalar = AsyncMock()
    session.scalars = AsyncMock()
    return session


@pytest.mark.anyio
async def test_recipe_repository_creates_and_updates_validated_drafts() -> None:
    session = mock_session()
    repository = RecipeRepository(session)
    definition = RecipeDefinition.model_validate(valid_recipe())
    owner_id = uuid4()

    recipe = await repository.create(owner_id, definition)
    changed = definition.model_copy(update={"name": "Updated panel"})
    await repository.update(recipe, changed)

    assert recipe.name == "Updated panel"
    assert recipe.owner_id == owner_id
    assert recipe.draft_content["name"] == "Updated panel"
    assert len(recipe.draft_hash) == 64
    session.add.assert_called_once_with(recipe)
    assert session.flush.await_count == 2


@pytest.mark.anyio
async def test_recipe_version_freeze_creates_ordered_normalized_rows() -> None:
    session = mock_session()
    definition = RecipeDefinition.model_validate(valid_recipe())
    recipe = DatasetRecipe(
        id=uuid4(),
        owner_id=uuid4(),
        name=definition.name,
        description=definition.description,
        draft_content=definition.model_dump(mode="json"),
        draft_hash="a" * 64,
    )
    session.scalar.side_effect = [None, 2]

    result = await RecipeVersionRepository(session).freeze(recipe, definition)

    assert result.created is True
    assert result.version.version_number == 3
    added = [call.args[0] for call in session.add.call_args_list]
    variables = [item for item in added if isinstance(item, RecipeVariable)]
    steps = [item for item in added if isinstance(item, TransformationStep)]
    assert [item.output_name for item in variables] == ["gdp_growth", "inflation"]
    assert [item.position for item in variables] == [0, 1]
    assert steps[0].parameters == {"variable": "inflation", "periods": 1}


@pytest.mark.anyio
async def test_freezing_identical_content_reuses_existing_version() -> None:
    session = mock_session()
    definition = RecipeDefinition.model_validate(valid_recipe())
    recipe = DatasetRecipe(
        id=uuid4(),
        owner_id=uuid4(),
        name=definition.name,
        draft_content=definition.model_dump(mode="json"),
        draft_hash="a" * 64,
    )
    existing = MagicMock()
    session.scalar.return_value = existing

    result = await RecipeVersionRepository(session).freeze(recipe, definition)

    assert result.created is False
    assert result.version is existing
    session.add.assert_not_called()


@pytest.mark.anyio
async def test_recipe_service_reports_missing_recipe() -> None:
    session = mock_session()
    session.scalar.return_value = None
    service = RecipeService(RecipeRepository(session), RecipeVersionRepository(session), uuid4())

    with pytest.raises(RecipeNotFoundError):
        await service.freeze(uuid4())
