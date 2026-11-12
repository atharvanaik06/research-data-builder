"""Deterministic CSV, Parquet, documentation, and checksum bundle export."""

import hashlib
import io
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import polars as pl

from research_data_builder.artifacts.models import BundleResult, ExportedArtifact
from research_data_builder.engine.result import json_value
from research_data_builder.provenance import build_lineage, dataset_checksum
from research_data_builder.recipes.codec import RecipeCodec
from research_data_builder.recipes.planner import BuildPlan
from research_data_builder.recipes.schemas import OutputFormat, RecipeDefinition
from research_data_builder.validation.models import ValidationReport


def export_research_bundle(
    *,
    artifact_root: Path,
    build_id: UUID,
    build_identity: str,
    frame: pl.DataFrame,
    recipe: RecipeDefinition,
    plan: BuildPlan,
    validation: ValidationReport,
    entity_mapping_version: str,
    application_version: str,
    transformer_version: str | None = None,
    deployment_commit: str | None = None,
) -> BundleResult:
    """Write a complete local bundle under a controlled build-specific directory."""
    if not validation.passed:
        raise ValueError("cannot export a dataset with blocking validation errors")
    root = artifact_root.expanduser().resolve()
    directory = (root / "builds" / str(build_id)).resolve()
    if not directory.is_relative_to(root):  # defensive even though build_id is a UUID
        raise ValueError("artifact directory escapes configured root")
    directory.mkdir(parents=True, exist_ok=True)

    logical_checksum = dataset_checksum(frame)
    lineage = build_lineage(recipe, plan)
    codebook = _codebook(frame, recipe, plan, validation)
    citations = _citations(recipe, plan)
    validation_payload = validation.as_dict()

    payloads: list[tuple[str, str, bytes]] = []
    if OutputFormat.CSV in recipe.formats:
        payloads.append(("data.csv", "csv", frame.write_csv().encode()))
    if OutputFormat.PARQUET in recipe.formats:
        buffer = io.BytesIO()
        frame.write_parquet(buffer, compression="zstd", statistics=True)
        payloads.append(("data.parquet", "parquet", buffer.getvalue()))
    payloads.extend(
        [
            ("recipe.yaml", "recipe", RecipeCodec.to_yaml(recipe).encode()),
            ("validation.json", "validation", _json_bytes(validation_payload)),
            ("validation.md", "validation_report", _validation_markdown(validation).encode()),
            ("codebook.json", "codebook", _json_bytes(codebook)),
            ("citations.md", "citations", citations.encode()),
            ("lineage.json", "lineage", _json_bytes(lineage)),
        ]
    )

    artifacts = [
        _write_artifact(directory, name, kind, content) for name, kind, content in payloads
    ]
    manifest = {
        "schema_version": "1",
        "build_id": str(build_id),
        "build_identity": build_identity,
        "dataset_checksum": logical_checksum,
        "recipe_content_hash": plan.recipe_content_hash,
        "planner_version": plan.planner_version,
        "application_version": application_version,
        "entity_mapping_version": entity_mapping_version,
        "row_count": frame.height,
        "columns": frame.columns,
        "input_fingerprints": [item.indicator_fingerprint for item in plan.inputs],
        "validation": validation_payload["summary"],
        "artifacts": [_artifact_dict(artifact) for artifact in artifacts],
        "checksum_policy": (
            "manifest lists pre-manifest artifacts; checksums.sha256 lists all files except itself"
        ),
    }
    if transformer_version is not None:
        manifest["transformer_version"] = transformer_version
    if deployment_commit is not None:
        manifest["deployment_commit"] = deployment_commit
    manifest_artifact = _write_artifact(
        directory, "manifest.json", "manifest", _json_bytes(manifest)
    )
    artifacts.append(manifest_artifact)
    checksums = "".join(f"{artifact.sha256}  {artifact.name}\n" for artifact in artifacts)
    artifacts.append(
        _write_artifact(directory, "checksums.sha256", "checksums", checksums.encode())
    )
    return BundleResult(
        directory=directory,
        dataset_checksum=logical_checksum,
        artifacts=tuple(artifacts),
        manifest=manifest,
        lineage=lineage,
    )


def _write_artifact(directory: Path, name: str, kind: str, content: bytes) -> ExportedArtifact:
    path = directory / name
    temporary = directory / f".{name}.tmp"
    temporary.write_bytes(content)
    temporary.replace(path)
    return ExportedArtifact(
        name=name,
        kind=kind,
        relative_path=f"builds/{directory.name}/{name}",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _artifact_dict(artifact: ExportedArtifact) -> dict[str, Any]:
    return {
        "name": artifact.name,
        "kind": artifact.kind,
        "relative_path": artifact.relative_path,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
    }


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            default=json_value,
        )
        + "\n"
    ).encode()


def _codebook(
    frame: pl.DataFrame,
    recipe: RecipeDefinition,
    plan: BuildPlan,
    validation: ValidationReport,
) -> dict[str, Any]:
    inputs = {item.output_name: item for item in plan.inputs}
    columns: list[dict[str, Any]] = []
    for name in frame.columns:
        if name in recipe.join.keys:
            columns.append({"column": name, "type": str(frame.schema[name]), "role": "key"})
            continue
        item = inputs[name]
        metadata = item.indicator_metadata
        columns.append(
            {
                "column": name,
                "type": str(frame.schema[name]),
                "role": "variable",
                "provider": item.provider,
                "indicator_id": item.indicator_id,
                "title": metadata.get("title"),
                "unit": metadata.get("unit"),
                "source_frequency": metadata.get("frequency"),
                "missing_count": validation.missing_by_variable.get(name, 0),
            }
        )
    return {"columns": columns}


def _citations(recipe: RecipeDefinition, plan: BuildPlan) -> str:
    lines = [f"# Data citations for {recipe.name}", ""]
    for item in plan.inputs:
        metadata = item.indicator_metadata
        source_url = metadata.get("source_url") or "Provider metadata did not supply a URL"
        lines.extend(
            [
                f"## {metadata.get('title') or item.output_name}",
                "",
                f"- Provider: {item.provider}",
                f"- Indicator: `{item.indicator_id}`",
                f"- Source: {source_url}",
                "- Accessed through Research Data Builder.",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _validation_markdown(report: ValidationReport) -> str:
    status = "PASSED" if report.passed else "FAILED"
    lines = [f"# Dataset validation: {status}", "", f"Rows: {report.row_count}"]
    if report.expected_row_count is not None:
        lines.append(f"Expected rows: {report.expected_row_count}")
    if report.coverage_percent is not None:
        lines.append(f"Coverage: {report.coverage_percent:.4f}%")
    lines.extend(["", "## Findings", ""])
    for issue in report.issues:
        variable = f" ({issue.variable})" if issue.variable else ""
        lines.append(f"- **{issue.severity.upper()}** `{issue.code}`{variable}: {issue.message}")
    return "\n".join(lines) + "\n"
