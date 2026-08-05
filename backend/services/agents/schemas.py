from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal


class AgentChatRequest(BaseModel):
    agent: str = Field(..., description="Agent key, e.g. platform-guide")
    message: str = Field(..., description="User message")
    session_id: Optional[str] = Field(None, description="Chat session id")
    history: Optional[List[Dict[str, Any]]] = None
    regenerate: bool = Field(False, description="Whether this request is a regeneration")


class AgentChatResponse(BaseModel):
    agent: str
    answer: str
    provider: str
    model: str
    session_id: Optional[str] = None
    actual_agent: Optional[str] = None
    answer_type: Optional[str] = None
    answer_payload: Optional[Dict[str, Any]] = None
    message_id: Optional[str] = None


class AgentFeedbackRequest(BaseModel):
    agent: str
    session_id: str
    message_id: str
    feedback: Literal["like", "dislike", "cancel"]
    reason_code: Optional[str] = None
    reason_text: Optional[str] = None


class AgentFeedbackResponse(BaseModel):
    ok: bool
    agent: str
    session_id: str
    message_id: str
    feedback: str


class AgentRegenerateRequest(BaseModel):
    agent: str
    session_id: str
    message_id: str


class AgentRegenerateResponse(BaseModel):
    ok: bool
    agent: str
    session_id: str
    message_id: str
    answer: str
    provider: str
    model: str
    actual_agent: Optional[str] = None
    answer_type: Optional[str] = None
    answer_payload: Optional[Dict[str, Any]] = None
    regenerated_from_message_id: Optional[str] = None


class AgentClearRequest(BaseModel):
    agent: str = Field(..., description="Agent key, e.g. general-chat")
    session_id: str = Field(..., description="Chat session id to clear")


class AgentClearResponse(BaseModel):
    ok: bool
    agent: str
    session_id: str


class AgentHistoryResponse(BaseModel):
    agent: str
    session_id: str
    history: List[Dict[str, Any]]


class AgentSessionItem(BaseModel):
    session_id: str
    agent: str
    user_id: int
    title: str
    created_at: int
    updated_at: int


class AgentSessionsResponse(BaseModel):
    agent: str
    sessions: List[AgentSessionItem]


class AgentSessionCreateRequest(BaseModel):
    agent: str
    session_id: str
    title: Optional[str] = None


class AgentSessionCreateResponse(BaseModel):
    ok: bool
    agent: str
    session_id: str


class AgentSessionDeleteRequest(BaseModel):
    agent: str
    session_id: str


class AgentSessionDeleteResponse(BaseModel):
    ok: bool
    agent: str
    session_id: str
