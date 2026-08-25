from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict


# ==================== ANALYTICS SESSION SCHEMAS ====================
class AnalyticsSessionCreate(BaseModel):
    session_id: str = Field(..., max_length=64)
    user_id: Optional[int] = None
    ip_address: Optional[str] = Field(None, max_length=45)
    city: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    device_type: Optional[str] = Field(None, max_length=20)
    os: Optional[str] = Field(None, max_length=50)
    browser: Optional[str] = Field(None, max_length=50)
    entry_page: Optional[str] = Field(None, max_length=255)
    referrer: Optional[str] = Field(None, max_length=500)


class AnalyticsSessionUpdate(BaseModel):
    end_time: Optional[datetime] = None
    duration_seconds: Optional[int] = None


class AnalyticsSessionResponse(AnalyticsSessionCreate):
    id: int
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==================== ANALYTICS PAGE VIEW SCHEMAS ====================
class AnalyticsPageViewCreate(BaseModel):
    session_id: str = Field(..., max_length=64)
    page_path: str = Field(..., max_length=255)
    referrer: Optional[str] = Field(None, max_length=500)
    time_on_page: Optional[int] = None


class AnalyticsPageViewResponse(AnalyticsPageViewCreate):
    id: int
    timestamp: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==================== ANALYTICS EVENT SCHEMAS ====================
class AnalyticsEventCreate(BaseModel):
    session_id: str = Field(..., max_length=64)
    event_name: str = Field(..., max_length=50)
    page_path: Optional[str] = Field(None, max_length=255)
    event_metadata: Optional[Dict[str, Any]] = None


class AnalyticsEventResponse(AnalyticsEventCreate):
    id: int
    timestamp: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==================== ANALYTICS TRACK PAYLOAD ====================
class TrackPayload(BaseModel):
    session_id: str = Field(..., max_length=64)
    event_name: str = Field(..., max_length=50)
    page_path: str = Field(..., max_length=255)
    user_id: Optional[int] = None
    ip_address: Optional[str] = Field(None, max_length=45)
    city: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    device_type: Optional[str] = Field(None, max_length=20)
    os: Optional[str] = Field(None, max_length=50)
    browser: Optional[str] = Field(None, max_length=50)
    referrer: Optional[str] = Field(None, max_length=500)
    event_metadata: Optional[Dict[str, Any]] = None


# ==================== ANALYTICS DASHBOARD SCHEMAS ====================
class DashboardSummary(BaseModel):
    total_sessions: int
    total_page_views: int
    total_events: int
    avg_duration_seconds: Optional[float]
    unique_visitors: int
    active_sessions: int = 0


class TopItem(BaseModel):
    label: str
    count: int
    percentage: float


class TimeSeriesItem(BaseModel):
    date: str
    count: int


class CalculationFunnel(BaseModel):
    users_started: int
    activation_rate: float
    started: int
    completed: int
    completion_rate: float


class RetentionMetrics(BaseModel):
    new_users: int
    recurring_users: int


class OccupationProfileMetrics(BaseModel):
    total_devices: int
    audiences: List[TopItem]
    specialist_roles: List[TopItem]
    company_names: List[TopItem]


class DashboardData(BaseModel):
    summary: DashboardSummary
    devices: List[TopItem]
    cities: List[TopItem]
    browsers: List[TopItem]
    hourly_distribution: List[TopItem]
    daily_distribution: List[TopItem]
    pages: List[TopItem]
    sessions_over_time: List[TimeSeriesItem]
    kapital_funnel: CalculationFunnel
    kapital_retention: RetentionMetrics
    occupation_profiles: OccupationProfileMetrics
    cta_clicks: int
    avg_time_on_page: Optional[float]
