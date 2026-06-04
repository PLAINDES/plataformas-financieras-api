# app/api/chatbot/schemas.py
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ChatHistoryPart(BaseModel):
    text: str


class ChatHistoryMessage(BaseModel):
    role: str
    parts: List[ChatHistoryPart]


class ChatRequest(BaseModel):
    message: str
    form_data: Dict[str, Any] = {}
    # history: List[ChatHistoryMessage] = []


class ChatResponse(BaseModel):
    text: str
    tickers: List[str] = []
    # new_beta: Optional[float] = None
    # raw_history_appends: List[ChatHistoryMessage] = []


class AnalyzeCompaniesRequest(BaseModel):
    tickers: List[str]


class CompanyData(BaseModel):
    ticker: str
    company_name: str
    sector: str
    country: Optional[str] = None
    listing_currency: Optional[str] = None
    reporting_currency: Optional[str] = None
    fx_rate: Optional[float] = None
    debt_value: Optional[float] = None
    equity_value: Optional[float] = None
    total_assets: Optional[float] = None
    dc_ratio: Optional[float] = None
    effective_tax_rate: Optional[float] = None
    tax_source: Optional[str] = None
    beta_levered: Optional[float] = None
    beta_unlevered: Optional[float] = None
    pct_debt: Optional[float] = None
    pct_equity: Optional[float] = None
    market_cap: Optional[float] = None


class GroupStatistics(BaseModel):
    avg_beta_unlevered: float
    avg_dc_ratio: float
    avg_tax_rate: float


class YahooFinanceResponse(BaseModel):
    success: bool
    valid_companies: List[CompanyData] = []
    group_statistics: Optional[GroupStatistics] = None
