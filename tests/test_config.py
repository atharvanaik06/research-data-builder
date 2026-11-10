"""Settings validation tests."""

import pytest
from pydantic import ValidationError

from research_data_builder.core.config import Settings


def test_settings_use_safe_defaults() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.fred_api_key is None
    assert settings.provider_http_timeout_seconds == 15.0
    assert settings.provider_http_max_attempts == 3
    assert settings.session_cookie_name == "research_data_session"
    assert settings.session_ttl_hours == 168
    assert settings.artifact_storage_backend == "local"
    assert settings.artifact_max_bundle_bytes == 25 * 1024 * 1024
    assert settings.embedded_worker_enabled is False


def test_settings_load_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_DATA_ENVIRONMENT", "production")
    monkeypatch.setenv("RESEARCH_DATA_LOG_LEVEL", "warning")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.environment == "production"
    assert settings.log_level == "WARNING"


def test_settings_reject_invalid_log_level() -> None:
    with pytest.raises(ValidationError, match="log_level must be one of"):
        Settings(log_level="verbose", _env_file=None)  # type: ignore[call-arg]


def test_settings_treat_blank_optional_fred_key_as_unconfigured() -> None:
    settings = Settings(
        fred_api_key="",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.fred_api_key is None


def test_settings_reject_invalid_provider_http_policy() -> None:
    with pytest.raises(ValidationError):
        Settings(provider_http_max_attempts=0, _env_file=None)  # type: ignore[call-arg]


def test_settings_require_complete_s3_artifact_configuration() -> None:
    with pytest.raises(ValidationError, match="S3 artifact storage requires"):
        Settings(artifact_storage_backend="s3", _env_file=None)  # type: ignore[call-arg]

    settings = Settings(
        artifact_storage_backend="s3",
        artifact_s3_bucket="research-artifacts",
        artifact_s3_endpoint_url="https://storage.example.test",
        artifact_s3_access_key_id="access-key",  # type: ignore[arg-type]
        artifact_s3_secret_access_key="secret-key",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.artifact_s3_bucket == "research-artifacts"


def test_standard_postgresql_url_uses_async_psycopg_driver() -> None:
    settings = Settings(
        database_url="postgresql://user:secret@database.example/research",
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.database_url == (
        "postgresql+psycopg://user:secret@database.example/research"
    )
