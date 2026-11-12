"""Tests for output lineage and stable logical checksums."""

from datetime import date
from decimal import Decimal

import polars as pl

from research_data_builder.provenance import build_lineage, dataset_checksum
from research_data_builder.provenance.serialization import _canonical_value
from research_data_builder.recipes.schemas import RecipeDefinition
from tests.engine.test_executor import version_and_plan


def test_dataset_checksum_is_stable_and_changes_with_logical_content() -> None:
    frame = pl.DataFrame(
        {
            "entity": ["CZE"],
            "period": [date(2024, 1, 1)],
            "value": [Decimal("1.2500000000")],
        },
        schema_overrides={"value": pl.Decimal(30, 10)},
    )
    identical = frame.clone()
    changed = frame.with_columns(pl.lit(Decimal("1.26")).alias("value"))

    assert dataset_checksum(frame) == dataset_checksum(identical)
    assert len(dataset_checksum(frame)) == 64
    assert dataset_checksum(frame) != dataset_checksum(changed)


def test_lineage_explains_every_recipe_variable() -> None:
    version, plan = version_and_plan()
    recipe = RecipeDefinition.model_validate(version.content)

    lineage = build_lineage(recipe, plan)

    assert [column["output_column"] for column in lineage["columns"]] == [
        "gdp_growth",
        "inflation",
    ]
    assert lineage["columns"][0]["provider"] == "world_bank"
    assert lineage["columns"][0]["indicator_fingerprint"] == "a" * 64


def test_canonical_value_erases_decimal_zero_sign_and_preserves_scale() -> None:
    assert _canonical_value(Decimal("-0.0000000000")) == "0E-10"
