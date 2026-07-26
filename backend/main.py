from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "app": "AniOS"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
