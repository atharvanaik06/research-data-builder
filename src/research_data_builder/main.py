"""FastAPI application factory and default ASGI application."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from research_data_builder.api.audit import router as audit_router
from research_data_builder.api.auth import router as auth_router
from research_data_builder.api.health import router as health_router
from research_data_builder.api.recipes import router as recipe_router
from research_data_builder.api.ui import WEB_ROOT
from research_data_builder.api.ui import router as ui_router
from research_data_builder.core.config import Settings, get_settings
from research_data_builder.core.logging import configure_logging
from research_data_builder.db.session import Database, DatabaseLifecycle
from research_data_builder.providers.registry import ProviderRegistry
from research_data_builder.providers.runtime import ProviderRuntime

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    database: DatabaseLifecycle | None = None,
    provider_registry: ProviderRegistry | None = None,
) -> FastAPI:
    """Create a configured Research Data Builder application instance."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    resolved_database = database or Database(resolved_settings.database_url)
    provider_runtime: ProviderRuntime | None = None
    if provider_registry is None:
        provider_runtime = ProviderRuntime(resolved_settings)
        resolved_registry = provider_runtime.registry
    else:
        resolved_registry = provider_registry

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if provider_runtime is not None:
            await provider_runtime.close()
        await resolved_database.dispose()

    application = FastAPI(
        title="Research Data Builder API",
        summary="Build validated and reproducible datasets from public research APIs.",
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.database = resolved_database
    application.state.provider_registry = resolved_registry
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(audit_router)
    application.include_router(recipe_router)
    application.include_router(ui_router)
    application.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")

    logger.info(
        "application configured",
        extra={"environment": resolved_settings.environment},
    )
    return application


app = create_app()
