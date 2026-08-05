# backend/routers/agents.py
import logging

from fastapi import APIRouter, HTTPException, Query, Depends
from services.agents.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentClearRequest,
    AgentClearResponse,
    AgentHistoryResponse,
    AgentSessionsResponse,
    AgentSessionCreateRequest,
    AgentSessionCreateResponse,
    AgentSessionDeleteRequest,
    AgentSessionDeleteResponse,
    AgentFeedbackRequest,
    AgentFeedbackResponse,
    AgentRegenerateRequest,
    AgentRegenerateResponse,
)
from services.agents.service import AgentService
from auth import get_current_user
from models import User

router = APIRouter(prefix="/agents", tags=["agents"])
logger = logging.getLogger(__name__)

agent_service = AgentService()

@router.post("/chat", response_model=AgentChatResponse)
def agent_chat(req: AgentChatRequest, current_user: User = Depends(get_current_user)):
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    logger.info(
        "[agent_chat] user_id=%r, agent=%r, session_id=%r, message_len=%s",
        current_user.id,
        req.agent,
        req.session_id,
        len(message),
    )

    try:
        data = agent_service.chat(
            user_id=current_user.id,
            agent=req.agent,
            message=message,
            history=req.history or [],
            session_id=req.session_id,
        )
        logger.info("[agent_chat] response_keys=%s", list(data.keys()))
        return AgentChatResponse(**data)
    except ValueError as e:
        logger.warning("[agent_chat] value error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("[agent_chat] unexpected error")
        raise HTTPException(status_code=500, detail="agent internal error")


@router.post("/clear", response_model=AgentClearResponse)
def agent_clear(req: AgentClearRequest, current_user: User = Depends(get_current_user)):
    agent = (req.agent or "").strip()
    session_id = (req.session_id or "").strip()

    if not agent:
        raise HTTPException(status_code=400, detail="agent is required")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    logger.info(
        "[agent_clear] user_id=%r, agent=%r, session_id=%r",
        current_user.id,
        agent,
        session_id,
    )

    try:
        agent_service.clear(user_id=current_user.id, agent=agent, session_id=session_id)
        data = {
            "ok": True,
            "agent": agent,
            "session_id": session_id,
        }
        logger.info("[agent_clear] ok=True, agent=%r, session_id=%r", agent, session_id)
        return AgentClearResponse(**data)
    except ValueError as e:
        logger.warning("[agent_clear] value error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("[agent_clear] unexpected error")
        raise HTTPException(status_code=500, detail="agent clear internal error")


@router.get("/history", response_model=AgentHistoryResponse)
def agent_history(
    agent: str = Query(..., description="Agent key"),
    session_id: str = Query(..., description="Chat session id"),
    current_user: User = Depends(get_current_user),
):
    try:
        data = agent_service.get_history(
            user_id=current_user.id,
            agent=agent,
            session_id=session_id,
        )
        return AgentHistoryResponse(**data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("[agent_history] unexpected error")
        raise HTTPException(status_code=500, detail="agent history internal error")


@router.get("/sessions", response_model=AgentSessionsResponse)
def agent_sessions(
    agent: str = Query(..., description="Agent key"),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    try:
        data = agent_service.get_sessions(
            user_id=current_user.id,
            agent=agent,
            limit=limit,
        )
        return AgentSessionsResponse(**data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("[agent_sessions] unexpected error")
        raise HTTPException(status_code=500, detail="agent sessions internal error")


@router.post("/session/create", response_model=AgentSessionCreateResponse)
def agent_session_create(req: AgentSessionCreateRequest, current_user: User = Depends(get_current_user)):
    try:
        data = agent_service.create_new_session(
            user_id=current_user.id,
            agent=req.agent,
            session_id=req.session_id,
            title=req.title,
        )
        return AgentSessionCreateResponse(**data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("[agent_session_create] unexpected error")
        raise HTTPException(status_code=500, detail="agent session create internal error")


@router.post("/session/delete", response_model=AgentSessionDeleteResponse)
def agent_session_delete(req: AgentSessionDeleteRequest, current_user: User = Depends(get_current_user)):
    try:
        data = agent_service.delete_session(
            user_id=current_user.id,
            agent=req.agent,
            session_id=req.session_id,
        )
        return AgentSessionDeleteResponse(**data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("[agent_session_delete] unexpected error")
        raise HTTPException(status_code=500, detail="agent session delete internal error")

@router.post("/message/feedback", response_model=AgentFeedbackResponse)
def agent_message_feedback(req: AgentFeedbackRequest, current_user: User = Depends(get_current_user)):
    try:
        data = agent_service.submit_feedback(
            user_id=current_user.id,
            agent=req.agent,
            session_id=req.session_id,
            message_id=req.message_id,
            feedback=req.feedback,
            reason_code=req.reason_code,
            reason_text=req.reason_text,
        )
        return AgentFeedbackResponse(**data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("[agent_message_feedback] unexpected error")
        raise HTTPException(status_code=500, detail="agent feedback internal error")
    
@router.post("/message/regenerate", response_model=AgentRegenerateResponse)
def agent_message_regenerate(req: AgentRegenerateRequest, current_user: User = Depends(get_current_user)):
    try:
        data = agent_service.regenerate(
            user_id=current_user.id,
            agent=req.agent,
            session_id=req.session_id,
            message_id=req.message_id,
        )
        return AgentRegenerateResponse(**data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("[agent_message_regenerate] unexpected error")
        raise HTTPException(status_code=500, detail="agent regenerate internal error")

