"""Tests for bounded local and S3-compatible artifact storage."""

import hashlib
import io
from pathlib import Path
from typing import Any

import pytest

from research_data_builder.artifacts.models import BundleResult, ExportedArtifact
from research_data_builder.artifacts.storage import (
    ArtifactIntegrityError,
    ArtifactLimitError,
    ArtifactNotFoundError,
    ArtifactStorageError,
    LocalArtifactStorage,
    S3ArtifactStorage,
    create_artifact_storage,
)
from research_data_builder.core.config import Settings


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, **kwargs: Any) -> object:
        self.objects[(str(kwargs["Bucket"]), str(kwargs["Key"]))] = bytes(kwargs["Body"])
        return {}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        content = self.objects[(str(kwargs["Bucket"]), str(kwargs["Key"]))]
        return {"ContentLength": len(content), "Body": io.BytesIO(content)}


class BrokenS3Client(FakeS3Client):
    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("storage is unavailable")


class FixedResponseS3Client(FakeS3Client):
    def __init__(self, response: dict[str, Any]) -> None:
        super().__init__()
        self.response = response

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        return self.response


class MissingS3Client(FakeS3Client):
    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        from botocore.exceptions import ClientError  # type: ignore[import-untyped]

        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")


def bundle(root: Path, content: bytes = b"research-data") -> BundleResult:
    relative_path = "builds/build-id/data.csv"
    path = root / relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    artifact = ExportedArtifact(
        name="data.csv",
        kind="csv",
        relative_path=relative_path,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    return BundleResult(
        directory=path.parent,
        dataset_checksum="a" * 64,
        artifacts=(artifact,),
        manifest={},
        lineage={},
    )


@pytest.mark.anyio
async def test_local_storage_verifies_paths_limits_and_checksums(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    storage = LocalArtifactStorage(tmp_path, 100, 100)

    await storage.publish(result)
    content = await storage.load(result.artifacts[0].relative_path, result.artifacts[0].sha256)

    assert content == b"research-data"
    with pytest.raises(ArtifactNotFoundError):
        await storage.load("../private.txt", result.artifacts[0].sha256)
    with pytest.raises(ArtifactIntegrityError):
        await storage.load(result.artifacts[0].relative_path, "b" * 64)


@pytest.mark.anyio
async def test_storage_rejects_oversized_bundle_and_download(tmp_path: Path) -> None:
    result = bundle(tmp_path)

    with pytest.raises(ArtifactLimitError, match="bundle uses"):
        await LocalArtifactStorage(tmp_path, 1, 100).publish(result)
    with pytest.raises(ArtifactLimitError, match="download byte limit"):
        await LocalArtifactStorage(tmp_path, 100, 1).load(
            result.artifacts[0].relative_path,
            result.artifacts[0].sha256,
        )


@pytest.mark.anyio
async def test_s3_storage_publishes_loads_and_cleans_temporary_bundle(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    client = FakeS3Client()
    storage = S3ArtifactStorage(tmp_path, "artifacts", client, 100, 100)

    await storage.publish(result)
    content = await storage.load(result.artifacts[0].relative_path, result.artifacts[0].sha256)

    assert content == b"research-data"
    assert not result.directory.exists()

    with pytest.raises(ArtifactNotFoundError):
        await storage.load("builds/missing/data.csv", result.artifacts[0].sha256)

    broken = S3ArtifactStorage(tmp_path, "artifacts", BrokenS3Client(), 100, 100)
    with pytest.raises(ArtifactStorageError, match="storage request failed"):
        await broken.load(result.artifacts[0].relative_path, result.artifacts[0].sha256)


@pytest.mark.anyio
async def test_s3_storage_rejects_invalid_uploads_and_responses(tmp_path: Path) -> None:
    result = bundle(tmp_path)
    artifact = result.artifacts[0]

    with pytest.raises(ArtifactLimitError, match="bundle uses"):
        await S3ArtifactStorage(tmp_path, "artifacts", FakeS3Client(), 1, 100).publish(result)

    (tmp_path / artifact.relative_path).unlink()
    with pytest.raises(ArtifactNotFoundError, match="generated artifact is missing"):
        await S3ArtifactStorage(tmp_path, "artifacts", FakeS3Client(), 100, 100).publish(result)

    missing = S3ArtifactStorage(tmp_path, "artifacts", MissingS3Client(), 100, 100)
    with pytest.raises(ArtifactNotFoundError, match="object does not exist"):
        await missing.load(artifact.relative_path, artifact.sha256)

    oversized = FixedResponseS3Client({"ContentLength": 101, "Body": io.BytesIO()})
    with pytest.raises(ArtifactLimitError, match="download byte limit"):
        await S3ArtifactStorage(tmp_path, "artifacts", oversized, 100, 100).load(
            artifact.relative_path, artifact.sha256
        )

    unreadable = FixedResponseS3Client({"ContentLength": 1, "Body": object()})
    with pytest.raises(ArtifactStorageError, match="no readable body"):
        await S3ArtifactStorage(tmp_path, "artifacts", unreadable, 100, 100).load(
            artifact.relative_path, artifact.sha256
        )

    streamed_oversized = FixedResponseS3Client(
        {"ContentLength": 0, "Body": io.BytesIO(b"too large")}
    )
    with pytest.raises(ArtifactLimitError, match="download byte limit"):
        await S3ArtifactStorage(tmp_path, "artifacts", streamed_oversized, 100, 1).load(
            artifact.relative_path, artifact.sha256
        )


def test_storage_factory_creates_s3_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import boto3  # type: ignore[import-untyped]

    fake_client = FakeS3Client()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: fake_client)
    settings = Settings(
        artifact_root=tmp_path,
        artifact_storage_backend="s3",
        artifact_s3_bucket="research-artifacts",
        artifact_s3_endpoint_url="https://storage.example.test",
        artifact_s3_access_key_id="access-key",  # type: ignore[arg-type]
        artifact_s3_secret_access_key="secret-key",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )

    storage = create_artifact_storage(settings)

    assert isinstance(storage, S3ArtifactStorage)
    assert storage.client is fake_client
