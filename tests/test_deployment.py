"""Checks for the zero-cost Render deployment description."""

from pathlib import Path

import yaml  # type: ignore[import-untyped]


def test_render_blueprint_uses_one_free_service_and_external_secrets() -> None:
    blueprint = yaml.safe_load(Path("render.yaml").read_text())

    services = blueprint["services"]
    assert len(services) == 1
    service = services[0]
    assert service["type"] == "web"
    assert service["runtime"] == "docker"
    assert service["plan"] == "free"
    assert service["region"] == "ohio"
    assert service["healthCheckPath"] == "/health"
    assert "maxShutdownDelaySeconds" not in service
    assert service["dockerCommand"] == "/app/start-render.sh"

    start_script = Path("scripts/start_render.sh").read_text()
    assert "alembic upgrade head" in start_script
    assert "exec uvicorn research_data_builder.main:app" in start_script

    environment = {item["key"]: item for item in service["envVars"]}
    assert environment["RESEARCH_DATA_EMBEDDED_WORKER_ENABLED"]["value"] == "true"
    assert environment["RESEARCH_DATA_ARTIFACT_STORAGE_BACKEND"]["value"] == "s3"

    secret_names = {
        "RESEARCH_DATA_DATABASE_URL",
        "RESEARCH_DATA_FRED_API_KEY",
        "RESEARCH_DATA_ARTIFACT_S3_BUCKET",
        "RESEARCH_DATA_ARTIFACT_S3_ENDPOINT_URL",
        "RESEARCH_DATA_ARTIFACT_S3_ACCESS_KEY_ID",
        "RESEARCH_DATA_ARTIFACT_S3_SECRET_ACCESS_KEY",
    }
    for name in secret_names:
        assert environment[name] == {"key": name, "sync": False}
