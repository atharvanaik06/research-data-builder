"""Deterministic analytical execution engine."""

from research_data_builder.engine.result import DatasetPreview, ExecutionResult, JoinReport

# Bump when execution or logical serialization can change output for frozen inputs.
TRANSFORMER_VERSION = "1.0.0"

__all__ = ["DatasetPreview", "ExecutionResult", "JoinReport"]
