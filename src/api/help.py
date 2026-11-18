import asyncio

import anthropic
from fastapi import APIRouter, HTTPException

from src.services.help_assistant import ask_help

router = APIRouter(prefix="/api/v1", tags=["help"])


@router.post("/help/chat")
async def help_chat(body: dict) -> dict:
    """Answer a how-to question about the app. Reads no user data and changes nothing."""
    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(422, "message is required")
    history = body.get("history") or []
    if not isinstance(history, list) or not all(isinstance(t, dict) for t in history):
        raise HTTPException(422, "history must be a list of {role, content} objects")
    screen = body.get("screen")
    try:
        answer = await asyncio.to_thread(ask_help, message, history, str(screen) if screen else None)
    except RuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc
    except anthropic.APIError as exc:
        raise HTTPException(502, "The help assistant is unavailable right now. Try again shortly.") from exc
    return {"message": answer}
