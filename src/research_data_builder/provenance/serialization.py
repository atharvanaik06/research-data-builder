"""Stable logical dataset serialization and SHA-256 identity."""

import hashlib
import json
from decimal import Decimal
from typing import Any

import polars as pl

from research_data_builder.engine.result import json_value


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Decimal) and value.is_zero():
        value = value.copy_abs()
    return json_value(value)


def canonical_dataset_bytes(frame: pl.DataFrame) -> bytes:
    """Serialize schema and rows without presentation-only or timestamp fields."""
    payload = {
        "columns": frame.columns,
        "schema": {name: str(dtype) for name, dtype in frame.schema.items()},
        "rows": [
            [_canonical_value(row[column]) for column in frame.columns] for row in frame.to_dicts()
        ],
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def dataset_checksum(frame: pl.DataFrame) -> str:
    """Hash canonical logical content independently from CSV or Parquet encoding."""
    return hashlib.sha256(canonical_dataset_bytes(frame)).hexdigest()
