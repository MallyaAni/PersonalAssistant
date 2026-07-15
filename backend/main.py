from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from backend.api.v1.api import api_router
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="AniOS API", version="0.1.0")

# 1. REMOVE the wildcard "*" and specify your exact Vite frontend URL
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

# 2. Let CORSMiddleware handle everything natively
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,  # Now valid because origins are explicitly named
    allow_methods=["*"],
    allow_headers=["*"],
)

# REMOVED: The custom "Nuclear" catch-all middleware (it breaks OPTIONS preflight)

app.include_router(api_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "app": "AniOS"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
