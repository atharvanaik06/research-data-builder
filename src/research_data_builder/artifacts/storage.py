"""Bounded local and S3-compatible research artifact storage."""

import asyncio
import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from research_data_builder.artifacts.models import BundleResult
from research_data_builder.core.config import Settings


class ArtifactStorageError(RuntimeError):
    """Base error for artifact storage operations."""


class ArtifactNotFoundError(ArtifactStorageError):
    """The requested artifact does not exist."""


class ArtifactIntegrityError(ArtifactStorageError):
    """Stored artifact content does not match its recorded checksum."""


class ArtifactLimitError(ArtifactStorageError):
    """An artifact or bundle exceeds a configured byte limit."""


class ArtifactStorage(Protocol):
    """Storage behavior used by workers and download routes."""

    async def publish(self, bundle: BundleResult) -> None:
        """Publish a complete generated bundle."""

    async def load(self, relative_path: str, expected_sha256: str) -> bytes:
        """Load one bounded artifact and verify its checksum."""


@dataclass(slots=True)
class LocalArtifactStorage:
    """Store generated artifacts below one controlled local directory."""

    root: Path
    max_bundle_bytes: int
    max_download_bytes: int

    async def publish(self, bundle: BundleResult) -> None:
        self._check_bundle_size(bundle)

    async def load(self, relative_path: str, expected_sha256: str) -> bytes:
        return await asyncio.to_thread(self._load, relative_path, expected_sha256)

    def _load(self, relative_path: str, expected_sha256: str) -> bytes:
        root = self.root.expanduser().resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ArtifactNotFoundError("artifact file does not exist")
        if path.stat().st_size > self.max_download_bytes:
            raise ArtifactLimitError("artifact exceeds the download byte limit")
        content = path.read_bytes()
        _verify_checksum(content, expected_sha256)
        return content

    def _check_bundle_size(self, bundle: BundleResult) -> None:
        size = sum(item.size_bytes for item in bundle.artifacts)
        if size > self.max_bundle_bytes:
            raise ArtifactLimitError(f"bundle uses {size} bytes; limit is {self.max_bundle_bytes}")


class S3Client(Protocol):
    """Small subset of the synchronous S3 client used by this service."""

    def put_object(self, **kwargs: Any) -> object:
        """Store one object."""

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        """Return one object and its metadata."""


@dataclass(slots=True)
class S3ArtifactStorage:
    """Store artifacts in an S3-compatible private bucket."""

    root: Path
    bucket: str
    client: S3Client
    max_bundle_bytes: int
    max_download_bytes: int
    cleanup_local: bool = True

    async def publish(self, bundle: BundleResult) -> None:
        await asyncio.to_thread(self._publish, bundle)

    async def load(self, relative_path: str, expected_sha256: str) -> bytes:
        return await asyncio.to_thread(self._load, relative_path, expected_sha256)

    def _publish(self, bundle: BundleResult) -> None:
        size = sum(item.size_bytes for item in bundle.artifacts)
        if size > self.max_bundle_bytes:
            raise ArtifactLimitError(f"bundle uses {size} bytes; limit is {self.max_bundle_bytes}")
        root = self.root.expanduser().resolve()
        for artifact in bundle.artifacts:
            path = (root / artifact.relative_path).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ArtifactNotFoundError(f"generated artifact is missing: {artifact.name}")
            content = path.read_bytes()
            _verify_checksum(content, artifact.sha256)
            self.client.put_object(
                Bucket=self.bucket,
                Key=artifact.relative_path,
                Body=content,
                Metadata={"sha256": artifact.sha256},
            )
        if self.cleanup_local:
            shutil.rmtree(bundle.directory)

    def _load(self, relative_path: str, expected_sha256: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=relative_path)
        except Exception as error:
            if _is_missing_object_error(error):
                raise ArtifactNotFoundError("artifact object does not exist") from error
            raise ArtifactStorageError("artifact storage request failed") from error
        size = int(response.get("ContentLength", 0))
        if size > self.max_download_bytes:
            raise ArtifactLimitError("artifact exceeds the download byte limit")
        body = response.get("Body")
        if body is None or not hasattr(body, "read"):
            raise ArtifactStorageError("artifact response has no readable body")
        try:
            content = cast(bytes, body.read(self.max_download_bytes + 1))
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        if len(content) > self.max_download_bytes:
            raise ArtifactLimitError("artifact exceeds the download byte limit")
        _verify_checksum(content, expected_sha256)
        return content


def create_artifact_storage(settings: Settings) -> ArtifactStorage:
    """Create local or S3-compatible storage from validated settings."""
    if settings.artifact_storage_backend == "local":
        return LocalArtifactStorage(
            settings.artifact_root,
            settings.artifact_max_bundle_bytes,
            settings.artifact_max_download_bytes,
        )

    import boto3  # type: ignore[import-untyped]
    from botocore.config import Config  # type: ignore[import-untyped]

    if (
        settings.artifact_s3_bucket is None
        or settings.artifact_s3_endpoint_url is None
        or settings.artifact_s3_access_key_id is None
        or settings.artifact_s3_secret_access_key is None
    ):
        raise ValueError("S3 artifact settings are incomplete")
    client = boto3.client(
        "s3",
        endpoint_url=settings.artifact_s3_endpoint_url,
        region_name=settings.artifact_s3_region,
        aws_access_key_id=settings.artifact_s3_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.artifact_s3_secret_access_key.get_secret_value(),
        config=Config(signature_version="s3v4"),
    )
    return S3ArtifactStorage(
        settings.artifact_root,
        settings.artifact_s3_bucket,
        cast(S3Client, client),
        settings.artifact_max_bundle_bytes,
        settings.artifact_max_download_bytes,
    )


def _verify_checksum(content: bytes, expected_sha256: str) -> None:
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ArtifactIntegrityError("artifact checksum does not match")


def _is_missing_object_error(error: Exception) -> bool:
    if isinstance(error, KeyError):
        return True
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return False
    details = response.get("Error")
    if not isinstance(details, dict):
        return False
    return str(details.get("Code")) in {"404", "NoSuchKey", "NotFound"}
