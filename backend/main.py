from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.v1.api import api_router
from backend.config.settings import settings
from backend.core.logging_config import setup_logging
from backend.core.telemetry import configure_telemetry

setup_logging("DEBUG" if settings.DEBUG else "INFO")

app = FastAPI(title=settings.APP_NAME, version="0.1.0")

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
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "app": "AniOS"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
