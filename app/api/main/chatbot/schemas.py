# app/api/chatbot/schemas.py
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CompanyData(BaseModel):
    ticker: str
    company_name: str
    sector: str
    country: Optional[str] = None
    listing_currency: Optional[str] = None
    reporting_currency: Optional[str] = None
    fx_rate: Optional[float] = None
    debt_lt: Optional[float] = None
    debt_st: Optional[float] = None
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
    suffix_used: Optional[str] = None
    ticker_original: Optional[str] = None
    ticker_resolved: Optional[str] = None
    ticker_resolution_status: Optional[str] = None
    ticker_resolution_reason: Optional[str] = None
    ticker_resolution_source: Optional[str] = None
    ticker_resolution_confidence: Optional[float] = None
    ticker_resolution_candidates: List[Dict[str, Any]] = []
    ticker_resolution_details: Dict[str, Any] = {}


class SubsectorBoaError(BaseModel):
    ticker: str
    suffix_usado: Optional[str] = None
    mensaje: str
    ticker_original: Optional[str] = None
    ticker_resolved: Optional[str] = None
    ticker_resolution_status: Optional[str] = None
    ticker_resolution_reason: Optional[str] = None
    ticker_resolution_source: Optional[str] = None
    ticker_resolution_confidence: Optional[float] = None
    ticker_resolution_candidates: List[Dict[str, Any]] = []
    ticker_resolution_details: Dict[str, Any] = {}


class SubsectorBoaResponse(BaseModel):
    success: bool = True
    valid_companies: List[CompanyData] = []
    errors: List[SubsectorBoaError] = []
    total: int = 0
    processed: int = 0
    failed: int = 0
    complete_count: int = 0
    incomplete_count: int = 0
    complete_tickers: List[str] = []
    incomplete_tickers: List[str] = []
    empty_batch_tickers: List[str] = []
    job_id: Optional[str] = None
    message: Optional[str] = None
    ticker_rows: List[Dict[str, Any]] = []


class SubsectorBoaProgressResponse(BaseModel):
    status: str
    total: int = 0
    processed: int = 0
    failed: int = 0
    errors: List[SubsectorBoaError] = []
    result: Optional[dict] = None


class ChatHistoryPart(BaseModel):
    text: str


class ChatHistoryMessage(BaseModel):
    role: str
    parts: List[ChatHistoryPart]


class ChatRequest(BaseModel):
    message: str
    form_data: Dict[str, Any] = {}


class ChatResponse(BaseModel):
    text: str
    tickers: List[str] = []


class AnalyzeCompaniesRequest(BaseModel):
    tickers: List[str]


class DefaultResponse(BaseModel):
    message: str


class GenerateSubsectorsRequest(BaseModel):
    sector: str
    num_subsectors: int = 10




