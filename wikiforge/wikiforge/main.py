"""Application entry point."""
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import get_settings
from .database import init_db
from .parsers import SUPPORTED_EXTENSIONS
from .pipeline import get_queue
from .routers import agent, files, monitoring, projects, wiki

logger = logging.getLogger(__name__)
_STARTED_AT = time.monotonic()
_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    await init_db()

    queue = get_queue()
    await queue.start()
    # A restart abandons in-flight jobs, since the queue is in memory. Anything left
    # mid-pipeline is picked back up here rather than sitting half-processed forever.
    await queue.requeue_unfinished()

    if settings.require_auth and not settings.sso_jwt_secret:
        # Fails closed, so this is a lockout rather than a hole — but silently
        # rejecting every login would be baffling without saying why.
        logger.error(
            "WIKIFORGE_REQUIRE_AUTH is on but SSO_JWT_SECRET is unset — every "
            "token will be rejected. Set it in the environment."
        )

    logger.info(
        "WikiForge %s ready — data_dir=%s llm=%s",
        __version__, settings.data_dir,
        settings.switchboard_model if settings.llm_configured else "NOT CONFIGURED",
    )
    try:
        yield
    finally:
        await queue.stop()


app = FastAPI(
    title="WikiForge",
    description="Turn documents into a structured, cross-linked, searchable wiki.",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# The UI is served from this same origin, so CORS exists for agents and other
# NexusLayer products calling the API directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (projects, files, wiki, monitoring, agent):
    app.include_router(module.router)


@app.exception_handler(Exception)
async def unhandled(request: Request, cause: Exception) -> JSONResponse:
    """Never leak a traceback to a caller; log it instead."""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "Something went wrong."}},
    )


@app.get("/health", tags=["system"])
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "healthy",
        "version": __version__,
        "uptime_seconds": int(time.monotonic() - _STARTED_AT),
        "llm": {
            "provider": "switchboard",
            "model": settings.switchboard_model,
            "configured": settings.llm_configured,
        },
        "auth": {
            "required": settings.require_auth,
            "identity_server": settings.identity_server_url,
        },
        "queue_depth": get_queue().depth,
    }


@app.get("/capabilities", tags=["system"])
async def capabilities() -> dict:
    """What this deployment can actually do, so the UI never offers what it cannot."""
    settings = get_settings()
    return {
        "supported_extensions": list(SUPPORTED_EXTENSIONS),
        "llm_available": settings.llm_configured,
        "ai_generation_available": settings.llm_configured,
        "semantic_search": "lexical",  # no embedding provider is reachable
        "max_upload_mb": 100,
        "auth_required": settings.require_auth,
    }


# --- static UI --------------------------------------------------------------
# Mounted last so it never shadows an API route. Missing during backend-only
# development, which must not stop the server from booting.
if (_STATIC_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    """Serve the single-page app, letting it own client-side routing.

    API paths are excluded deliberately. Without this, a request to a mistyped or
    not-yet-deployed endpoint under /api/ falls through to here and gets
    index.html with a 200 — so a client sees a successful response full of HTML
    instead of a 404, and reports something inexplicable much later. A wrong API
    path must fail like a wrong API path.
    """
    if full_path.startswith(("api/", "health", "capabilities")):
        raise HTTPException(status_code=404, detail=f"No such endpoint: /{full_path}")

    index = _STATIC_DIR / "index.html"
    if not index.is_file():
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "No UI is bundled in this build. The API is at /api/docs.",
                }
            },
        )
    candidate = (_STATIC_DIR / full_path).resolve()
    # Only serve real files from inside the static dir; everything else is a route
    # the SPA handles. The resolve()/relative_to() pair blocks ../ traversal.
    if full_path:
        try:
            candidate.relative_to(_STATIC_DIR.resolve())
            if candidate.is_file():
                return FileResponse(candidate)
        except ValueError:
            pass
    return FileResponse(index)


def run() -> None:
    """Console-script entry point."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "wikiforge.main:app", host="0.0.0.0", port=settings.port,
        log_level=settings.log_level.lower(),
    )
