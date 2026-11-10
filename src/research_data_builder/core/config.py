"""Validated environment-based application settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from research_data_builder import __version__

Environment = Literal["development", "test", "production"]
ArtifactStorageBackend = Literal["local", "s3"]


class Settings(BaseSettings):
    """Research Data Builder settings loaded from the environment or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RESEARCH_DATA_",
        extra="ignore",
    )

    app_name: str = "research-data-builder"
    app_version: str = __version__
    environment: Environment = "development"
    log_level: str = "INFO"
    database_url: str = Field(
        default="postgresql+psycopg://research_data:research_data@localhost:5432/research_data",
        min_length=1,
    )
    fred_api_key: SecretStr | None = None
    provider_http_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    provider_http_max_attempts: int = Field(default=3, ge=1, le=10)
    provider_cache_ttl_hours: int = Field(default=24, ge=1, le=24 * 30)
    artifact_root: Path = Path("artifacts")
    artifact_storage_backend: ArtifactStorageBackend = "local"
    artifact_s3_bucket: str | None = None
    artifact_s3_endpoint_url: str | None = None
    artifact_s3_region: str = "auto"
    artifact_s3_access_key_id: SecretStr | None = None
    artifact_s3_secret_access_key: SecretStr | None = None
    artifact_max_bundle_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    artifact_max_download_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    session_cookie_name: str = Field(default="research_data_session", min_length=1, max_length=64)
    session_ttl_hours: int = Field(default=168, ge=1, le=24 * 90)
    worker_poll_seconds: float = Field(default=1.0, gt=0, le=60)
    worker_lease_seconds: int = Field(default=60, ge=10, le=3600)
    max_outstanding_builds_per_user: int = Field(default=5, ge=1, le=100)
    max_recipe_bytes: int = Field(default=65536, ge=1024, le=1048576)
    embedded_worker_enabled: bool = False

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Normalize and validate Python logging levels."""
        normalized = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            message = f"log_level must be one of: {', '.join(sorted(allowed))}"
            raise ValueError(message)
        return normalized

    @field_validator("fred_api_key", mode="before")
    @classmethod
    def normalize_optional_fred_key(cls, value: object) -> object:
        """Treat the blank example value as an unconfigured optional provider."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_postgresql_url(cls, value: object) -> object:
        """Use the async psycopg driver for standard hosted PostgreSQL URLs."""
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @model_validator(mode="after")
    def validate_artifact_storage(self) -> "Settings":
        """Require complete object-storage settings when S3 storage is active."""
        if self.artifact_storage_backend == "local":
            return self
        required = {
            "artifact_s3_bucket": self.artifact_s3_bucket,
            "artifact_s3_endpoint_url": self.artifact_s3_endpoint_url,
            "artifact_s3_access_key_id": self.artifact_s3_access_key_id,
            "artifact_s3_secret_access_key": self.artifact_s3_secret_access_key,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(f"S3 artifact storage requires: {', '.join(missing)}")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings instance per process."""
    return Settings()
