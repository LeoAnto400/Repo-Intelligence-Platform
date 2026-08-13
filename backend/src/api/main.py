import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routes import router as api_router
from src.core.config import settings
from src.core.logging import configure_logging
from src.services.github import safe_rmtree

configure_logging()
logger = logging.getLogger(__name__)


def _clear_stale_temp_clones() -> None:
    """
    Wipe any leftover repository clone directories from .temp_clones/.

    Each ingestion request cleans up its own clone directory as soon as it
    finishes, success or failure, so anything still present at process
    startup can only be debris from a previous process that was killed
    mid-clone (e.g. a crash or a hard reload) - safe to remove unconditionally.
    """
    temp_clones_dir = os.path.join(os.getcwd(), ".temp_clones")
    if not os.path.isdir(temp_clones_dir):
        return

    removed = 0
    for entry in os.scandir(temp_clones_dir):
        if entry.is_dir():
            safe_rmtree(entry.path)
            removed += 1

    if removed:
        logger.info("Cleared %d stale director%s from .temp_clones/ on startup", removed, "y" if removed == 1 else "ies")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _clear_stale_temp_clones()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="REST API for ingesting GitHub repositories and answering questions about their code.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Allow the frontend dev server to call the API directly from the browser
# (the frontend no longer proxies through Next.js rewrites - see api-client.ts).
# In production, replace these origins with your actual frontend domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://192.168.1.7:3000",  # matches allowedDevOrigins in frontend/next.config.ts
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.exception_handler(Exception)
async def log_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """
    Last-resort safety net: log the full traceback and return a proper HTTP 500
    for any exception that escapes a route handler's own error handling,
    instead of letting the ASGI worker crash the connection outright.
    """
    logger.exception(
        "Unhandled exception in %s %s: %s", request.method, request.url.path, exc
    )
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {exc}"},
    )


@app.get("/health", tags=["Health"])
def health_check():
    """Service health check endpoint."""
    return {"status": "healthy"}

