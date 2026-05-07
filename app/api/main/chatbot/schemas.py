# app/api/chatbot/schemas.py
from pydantic import BaseModel
from typing import List, Dict, Optional, Any

class ChatHistoryPart(BaseModel):
    text: str

class ChatHistoryMessage(BaseModel):
    role: str
    parts: List[ChatHistoryPart]

class ChatRequest(BaseModel):
    message: str
    history: List[ChatHistoryMessage] = []
    form_data: Dict[str, Any] = {}

class ChatResponse(BaseModel):
    text: str
    tickers: List[str] = []
    new_beta: Optional[float] = None
    raw_history_appends: List[ChatHistoryMessage] = []
