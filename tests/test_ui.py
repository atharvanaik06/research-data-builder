"""Tests for the browser application shell."""

import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def test_browser_application_and_assets_are_public(app: FastAPI) -> None:
    async def scenario() -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            root = await client.get("/", follow_redirects=False)
            page = await client.get("/app")
            css = await client.get("/static/app.css")
            script = await client.get("/static/app.js")

        assert root.status_code == 307
        assert root.headers["location"] == "/app"
        assert page.status_code == 200
        assert "Research Data Builder" in page.text
        assert "Save and build dataset" in page.text
        assert css.status_code == 200
        assert script.status_code == 200
        assert "/api/v1/builds/" in script.text

    asyncio.run(scenario())
