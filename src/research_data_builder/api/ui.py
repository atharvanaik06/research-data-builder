"""Browser application routes."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
router = APIRouter(include_in_schema=False)


@router.get("/")
async def application_root() -> RedirectResponse:
    return RedirectResponse("/app", status_code=307)


@router.get("/app", response_class=FileResponse)
async def browser_application() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html", media_type="text/html")
