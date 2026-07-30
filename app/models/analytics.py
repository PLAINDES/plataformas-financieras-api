import uuid
from sqlalchemy import Column, String, DateTime, Integer, Text, ForeignKey, JSON
from sqlalchemy.dialects.mysql import BIGINT as MySQLBigInt
from sqlalchemy.sql import func
from app.db.base import Base


class AnalyticsSession(Base):
    __tablename__ = "analytics_sessions"

    id = Column(MySQLBigInt(unsigned=True), primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(MySQLBigInt(unsigned=True), ForeignKey("sys_users.id"), nullable=True)
    ip_address = Column(String(45), nullable=True)
    city = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    device_type = Column(String(20), nullable=True)  # desktop, mobile, tablet
    os = Column(String(50), nullable=True)
    browser = Column(String(50), nullable=True)
    entry_page = Column(String(255), nullable=True)
    referrer = Column(String(500), nullable=True)
    start_time = Column(DateTime, default=func.now(), nullable=False)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=func.now(), nullable=False)

    def __repr__(self):
        return f"<AnalyticsSession {self.session_id}>"


class AnalyticsPageView(Base):
    __tablename__ = "analytics_page_views"

    id = Column(MySQLBigInt(unsigned=True), primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("analytics_sessions.session_id"), nullable=False, index=True)
    page_path = Column(String(255), nullable=False)
    referrer = Column(String(500), nullable=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    time_on_page = Column(Integer, nullable=True)  # segundos

    created_at = Column(DateTime, default=func.now(), nullable=False)

    def __repr__(self):
        return f"<AnalyticsPageView {self.page_path}>"


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id = Column(MySQLBigInt(unsigned=True), primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("analytics_sessions.session_id"), nullable=False, index=True)
    event_name = Column(String(50), nullable=False)  # cta_click, page_view, etc
    page_path = Column(String(255), nullable=True)
    event_metadata = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False)

    created_at = Column(DateTime, default=func.now(), nullable=False)

    def __repr__(self):
        return f"<AnalyticsEvent {self.event_name}>"
