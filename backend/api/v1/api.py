from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from backend.core.dependencies import DependencyConversationService

router = APIRouter()

# Explicitly define the name expected by main.py
api_router = router

@router.get("/")
async def root():
    return {"message": "Welcome to AniOS API v1"}

@router.post("/chat")
async def chat(
    request: Request,
    service: DependencyConversationService
):
    """
    Endpoint to interact with the AniOS Conversation Engine.
    Bypasses Pydantic models entirely for diagnostic verification.
    """
    body = await request.json()
    print(f"DEBUG_RAW_PAYLOAD: {body}")
    
    user_id = body.get("user_id")
    query = body.get("query")
    
    if not user_id or not query:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Missing user_id or query in request body")

    return StreamingResponse(
        service.process_request(user_id, query),
        media_type="text/event-stream"
    )
