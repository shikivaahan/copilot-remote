"""FastAPI application factory and lifespan.

Routers are mounted as placeholders here; the real route tables are
filled in during Phase 4 (``api.py``) and Phase 4 (``websocket.py``).
The lifespan hook owns DB schema bootstrap and (later) session registry
shutdown.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import api, websocket
from app.config import get_settings
from app.database import init_db
from app.session_manager import get_session_manager

logger = logging.getLogger(__name__)

APP_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: initialise the DB and start the session manager."""
    settings = get_settings()
    logger.info(
        "copilot-remote starting on %s:%d (env=%s)",
        settings.bind,
        settings.port,
        settings.environment,
    )
    init_db()
    mgr = get_session_manager()
    await mgr.start()
    try:
        yield
    finally:
        await mgr.shutdown()
        logger.info("copilot-remote shutting down")


def create_app() -> FastAPI:
    """Build and return a configured :class:`FastAPI` instance.

    No module-level state is captured; ``get_settings()`` is resolved
    lazily so tests can swap ``COPILOT_REMOTE_CONFIG`` before the
    factory runs.
    """
    app = FastAPI(
        title="Copilot Remote",
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        """Process liveness probe - no auth, no DB access."""
        return {"status": "ok", "version": APP_VERSION}

    # Single-origin SPA: no CORS allowed. Browsers will treat cross-site
    # requests as opaque and they will be blocked by SameSite=Strict
    # cookies anyway.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api.router)
    app.include_router(websocket.router)

    # Mount the built frontend as a SPA. ``vite build`` outputs to
    # ``backend/frontend_dist/`` (see vite.config.ts). When the dist
    # directory is missing (e.g. backend-only dev), the SPA routes
    # 404 gracefully instead of crashing.
    frontend_dist = Path(__file__).resolve().parent.parent / "frontend_dist"
    if frontend_dist.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(frontend_dist / "assets")),
            name="assets",
        )

        # Concrete asset routes MUST be defined before the catch-all
        # ``/{full_path:path}`` route, otherwise FastAPI's route
        # ordering matches the catch-all first.
        for asset in ("manifest.webmanifest", "icon-192.png", "icon-512.png"):
            p = frontend_dist / asset
            if p.is_file():

                def _make_handler(_p: Path):
                    def _handler() -> FileResponse:
                        return FileResponse(_p)
                    return _handler

                app.get("/" + asset, include_in_schema=False)(
                    _make_handler(p)
                )

        # Also serve sw.js, workbox-*.js from the dist root.
        for asset in ("sw.js",):
            p = frontend_dist / asset
            if p.is_file():
                app.get("/" + asset, include_in_schema=False)(
                    lambda _p=p: FileResponse(_p)
                )

        @app.get("/", include_in_schema=False)
        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str = "") -> FileResponse:
            """Serve the SPA index for any non-API GET route."""
            # Don't shadow real /api or /ws routes (FastAPI matches
            # them first since they're declared above this handler).
            if (
                full_path.startswith("api/")
                or full_path.startswith("ws/")
                or full_path == "health"
                or full_path.startswith("assets/")
            ):
                from fastapi import HTTPException

                raise HTTPException(status_code=404)
            index = frontend_dist / "index.html"
            if index.is_file():
                return FileResponse(index)
            raise HTTPException(status_code=404, detail="frontend not built")

    return app


# A default instance for ``uvicorn app.main:app`` invocations.
app = create_app()
