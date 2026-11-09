"""API contract and authentication tests for private research routes."""

import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def test_recipe_and_build_routes_are_versioned_and_documented(app: FastAPI) -> None:
    schema = app.openapi()
    paths = schema["paths"]

    assert "/api/v1/recipes" in paths
    assert set(paths["/api/v1/recipes"]) == {"get", "post"}
    assert "/api/v1/recipes/import" in paths
    assert "/api/v1/recipes/{recipe_id}/draft" in paths
    assert "/api/v1/recipes/{recipe_id}/versions" in paths
    assert "/api/v1/recipe-versions/{version_id}/export" in paths
    assert "/api/v1/recipe-versions/{version_id}/builds" in paths
    assert "/api/v1/builds/{build_id}" in paths
    assert "/api/v1/builds/{build_id}/execute" in paths
    assert "/api/v1/builds/{build_id}/job" in paths
    assert "/api/v1/builds/{build_id}/cancel" in paths
    assert "202" in paths["/api/v1/builds/{build_id}/cancel"]["post"]["responses"]
    assert "202" in paths["/api/v1/builds/{build_id}/execute"]["post"]["responses"]
    assert "/api/v1/builds/{build_id}/preview" in paths
    assert "/api/v1/builds/{build_id}/validation" in paths
    assert "/api/v1/builds/{build_id}/lineage" in paths
    assert "/api/v1/builds/{build_id}/exports" in paths
    assert "/api/v1/exports/{export_id}/download" in paths
    assert "/api/v1/builds/{build_id}/comparison/{other_build_id}" in paths
    assert "/api/v1/audit-events" in paths

    recipe_schema = schema["components"]["schemas"]["RecipeDefinition"]
    assert recipe_schema["additionalProperties"] is False


def test_every_research_operation_requires_the_session_cookie(app: FastAPI) -> None:
    schema = app.openapi()
    cookie_scheme = schema["components"]["securitySchemes"]["APIKeyCookie"]
    assert cookie_scheme == {
        "type": "apiKey",
        "in": "cookie",
        "name": "research_data_session",
    }

    for path, operations in schema["paths"].items():
        if not path.startswith("/api/v1/") or path.startswith("/api/v1/auth/"):
            continue
        for method, operation in operations.items():
            if method == "parameters":
                continue
            assert operation["security"] == [{"APIKeyCookie": []}], f"{method} {path} is public"


def test_anonymous_research_request_is_rejected_before_database_access(app: FastAPI) -> None:
    async def scenario() -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/recipes")
        assert response.status_code == 401
        assert response.json() == {"detail": "authentication required"}

    asyncio.run(scenario())
