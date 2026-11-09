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
