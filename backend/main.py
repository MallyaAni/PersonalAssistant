import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.v1.api import api_router
from backend.config.settings import settings
from backend.core.dependencies import (
    get_binary_artifact_store,
    get_vision_embedding_provider,
)
from backend.core.logging_config import setup_logging
from backend.core.telemetry import configure_telemetry
from backend.services.image_embedding_reconciler import ImageEmbeddingReconciler

setup_logging("DEBUG" if settings.DEBUG else "INFO")
logger = logging.getLogger(__name__)


# Run the self-healing image-embedding reconciler for the app's lifetime, so any
# image that failed to embed at write time is backfilled and stays recallable.
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    reconciler = ImageEmbeddingReconciler(
        get_vision_embedding_provider(),
        get_binary_artifact_store(),
        settings.VISION_EMBEDDING_RECONCILE_INTERVAL_SECONDS,
    )
    reconciler.start()
    try:
        yield
    finally:
        await reconciler.stop()


app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)

# Instrument the app and outbound HTTP when tracing is enabled; a no-op otherwise.
configure_telemetry(app)

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# Say which field a rejected request failed on, in the log.
#
# A 422 was previously invisible from the server side: uvicorn recorded the
# status and nothing else, the browser showed "Server responded with 422", and
# working out which of six possible fields was at fault meant guessing. The
# field location and the validator's own message are logged; the submitted
# values are not, because a chat body carries the user's message text.
@app.exception_handler(RequestValidationError)
async def log_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    logger.warning(
        "Request rejected: %s %s -- %s",
        request.method,
        request.url.path,
        "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ),
    )
    # Encoded, not passed through: a validator that raises ValueError puts the
    # exception object itself in the error's `ctx`, which JSONResponse cannot
    # serialize - and the failure surfaces as the original error propagating
    # rather than as a 422, turning every blank-field rejection into a crash.
    return JSONResponse(
        status_code=422, content={"detail": jsonable_encoder(exc.errors())}
    )


app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "app": "AniOS"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
