import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, and_, text
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.analytics import AnalyticsSession, AnalyticsPageView, AnalyticsEvent
from app.schemas.analytics import (
    TrackPayload,
    AnalyticsSessionCreate,
    AnalyticsSessionUpdate,
    AnalyticsPageViewCreate,
    AnalyticsEventCreate,
    DashboardData,
    DashboardSummary,
    TopItem,
    TimeSeriesItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["Analytics"])

# Lima, Peru timezone (UTC-5)
LIMA_TZ = timezone(timedelta(hours=-5))


def now_lima() -> datetime:
    return datetime.now(LIMA_TZ)


def is_private_ip(ip: Optional[str]) -> bool:
    if not ip:
        return True
    ip = ip.strip()
    return ip.startswith(("127.", "192.168.", "10.", "172.", "localhost", "::1", "fe80:"))


def extract_client_ip(request: Request, payload_ip: Optional[str] = None) -> Optional[str]:
    """
    Extrae la IP real del cliente considerando reverse proxies (Nginx, Cloudflare, etc.).
    """
    if payload_ip and not is_private_ip(payload_ip):
        return payload_ip.strip()

    # Header CF-Connecting-IP (Cloudflare tiene la IP real del cliente)
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip and not is_private_ip(cf_ip):
        return cf_ip.strip()

    # Header X-Real-IP (Nginx)
    real_ip = request.headers.get("x-real-ip")
    if real_ip and not is_private_ip(real_ip):
        return real_ip.strip()

    # Header X-Forwarded-For (Nginx / proxies encadenados: toma la primera IP pública)
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        ips = [ip.strip() for ip in forwarded_for.split(",")]
        for ip in ips:
            if ip and not is_private_ip(ip):
                return ip

    # Fallback si solo hay IP privada (desarrollo local / Docker bridge)
    if request.client and request.client.host:
        return request.client.host

    return None


async def get_ip_location(ip: str) -> tuple[Optional[str], Optional[str]]:
    """
    Consulta ip.guide (y ip-api.com como fallback) para obtener ciudad y país a partir de la IP.
    Retorna (city, country) o (None, None) en caso de error.
    """
    if not ip or is_private_ip(ip):
        return None, None

    # Intentar ip.guide primero
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"https://ip.guide/{ip}", headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code == 200:
                data = response.json()
                location = data.get("location", {})
                city = location.get("city")
                country = location.get("country")
                if city or country:
                    return city, country
    except Exception as e:
        logger.warning(f"Error consulting ip.guide for {ip}: {e}")

    # Fallback a ip-api.com
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"http://ip-api.com/json/{ip}")
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    city = data.get("city")
                    country = data.get("country")
                    if city or country:
                        return city, country
    except Exception as e:
        logger.warning(f"Error consulting ip-api.com for {ip}: {e}")

    return None, None


# ==================== TRACKING ENDPOINTS ====================

@router.post("/track")
async def track_event(request: Request, payload: TrackPayload, db: Session = Depends(get_db)):
    """
    Endpoint unificado para trackear sesiones, pageviews y eventos.
    Crea la sesión si no existe, y registra el pageview/evento.
    """
    # Extraer IP real del cliente considerando reverse proxies (Nginx, Cloudflare)
    client_ip = extract_client_ip(request, payload.ip_address)

    city = payload.city
    country = payload.country

    # Si no viene ciudad/país en payload y tenemos IP, consultar geolocalización
    if client_ip and (not city or not country):
        geo_city, geo_country = await get_ip_location(client_ip)
        if not city:
            city = geo_city
        if not country:
            country = geo_country

    # Verificar si la sesión existe
    session = db.execute(
        select(AnalyticsSession).where(AnalyticsSession.session_id == payload.session_id)
    ).scalars().first()

    if not session:
        session_data = AnalyticsSessionCreate(
            session_id=payload.session_id,
            user_id=payload.user_id,
            ip_address=client_ip,
            city=city,
            country=country,
            device_type=payload.device_type,
            os=payload.os,
            browser=payload.browser,
            entry_page=payload.page_path,
            referrer=payload.referrer,
        )
        session = AnalyticsSession(**session_data.model_dump())
        session.start_time = now_lima()
        db.add(session)
        db.flush()
    else:
        # Si la sesión ya existía pero no tenía IP o geolocalización, actualizarla ahora
        updated = False
        if client_ip and not session.ip_address:
            session.ip_address = client_ip
            updated = True
        if city and not session.city:
            session.city = city
            updated = True
        if country and not session.country:
            session.country = country
            updated = True
        if updated:
            db.add(session)

    # Registrar page view
    page_view = AnalyticsPageView(
        session_id=payload.session_id,
        page_path=payload.page_path,
        referrer=payload.referrer,
        timestamp=now_lima(),
    )
    db.add(page_view)

    # Si es un evento específico (no solo pageview implícito), registrarlo
    if payload.event_name != "page_view":
        event = AnalyticsEvent(
            session_id=payload.session_id,
            event_name=payload.event_name,
            page_path=payload.page_path,
            event_metadata=payload.event_metadata,
            timestamp=now_lima(),
        )
        db.add(event)

    db.commit()
    return {"status": "tracked"}


@router.post("/session/end")
def end_session(session_id: str, duration_seconds: int, db: Session = Depends(get_db)):
    """
    Marca una sesión como terminada y establece su duración total.
    """
    session = db.execute(
        select(AnalyticsSession).where(AnalyticsSession.session_id == session_id)
    ).scalars().first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.end_time = now_lima()
    session.duration_seconds = duration_seconds
    db.commit()
    return {"status": "ended"}


@router.put("/pageview/duration")
def update_page_view_duration(
    session_id: str,
    page_path: str,
    time_on_page: int,
    db: Session = Depends(get_db)
):
    """
    Actualiza el tiempo en página del último pageview de una sesión.
    """
    page_view = db.execute(
        select(AnalyticsPageView)
        .where(
            and_(
                AnalyticsPageView.session_id == session_id,
                AnalyticsPageView.page_path == page_path,
            )
        )
        .order_by(AnalyticsPageView.timestamp.desc())
    ).scalars().first()

    if page_view:
        page_view.time_on_page = time_on_page
        db.commit()

    return {"status": "updated"}


# ==================== ACTIVE SESSIONS ====================

@router.get("/active-sessions")
def get_active_sessions(
    minutes: int = Query(15, ge=1, le=120, description="Minutos de inactividad para considerar una sesión activa"),
    db: Session = Depends(get_db),
):
    """
    Retorna la cantidad de sesiones activas en los últimos N minutos.
    Considera activa una sesión que no ha terminado (end_time IS NULL) 
    o que tuvo actividad en los últimos minutos.
    """
    since = now_lima() - timedelta(minutes=minutes)

    # Sesiones que no han terminado y tuvieron actividad reciente
    active_count = db.execute(
        select(func.count(func.distinct(AnalyticsSession.id)))
        .where(
            and_(
                AnalyticsSession.start_time >= since,
                AnalyticsSession.end_time.is_(None),
            )
        )
    ).scalar() or 0

    # O sesiones con pageview reciente (por si el beacon de end no funcionó)
    recent_sessions = db.execute(
        select(func.count(func.distinct(AnalyticsPageView.session_id)))
        .where(AnalyticsPageView.timestamp >= since)
    ).scalar() or 0

    return {
        "active_sessions": max(active_count, recent_sessions),
        "window_minutes": minutes,
    }


# ==================== DASHBOARD ENDPOINTS ====================

@router.get("/dashboard", response_model=DashboardData)
def get_dashboard(
    days: int = Query(30, ge=1, le=365),
    page_filter: Optional[str] = Query(None, description="Filtrar por página específica (ej: /kapital, /)"),
    db: Session = Depends(get_db),
):
    """
    Retorna todas las métricas agregadas para el dashboard de analytics.
    """
    since = now_lima() - timedelta(days=days)

    total_sessions = db.execute(
        select(func.count(AnalyticsSession.id)).where(AnalyticsSession.start_time >= since)
    ).scalar() or 0

    total_page_views = db.execute(
        select(func.count(AnalyticsPageView.id)).where(AnalyticsPageView.timestamp >= since)
    ).scalar() or 0

    total_events = db.execute(
        select(func.count(AnalyticsEvent.id)).where(AnalyticsEvent.timestamp >= since)
    ).scalar() or 0

    unique_visitors = db.execute(
        select(func.count(func.distinct(AnalyticsSession.session_id))).where(AnalyticsSession.start_time >= since)
    ).scalar() or 0

    # Sesiones activas (últimos 15 minutos)
    active_since = now_lima() - timedelta(minutes=15)
    active_sessions = db.execute(
        select(func.count(func.distinct(AnalyticsSession.id)))
        .where(
            and_(
                AnalyticsSession.start_time >= active_since,
                AnalyticsSession.end_time.is_(None),
            )
        )
    ).scalar() or 0

    recent_sessions = db.execute(
        select(func.count(func.distinct(AnalyticsPageView.session_id)))
        .where(AnalyticsPageView.timestamp >= active_since)
    ).scalar() or 0
    active_sessions = max(active_sessions, recent_sessions)

    avg_duration = db.execute(
        select(func.avg(AnalyticsSession.duration_seconds))
        .where(AnalyticsSession.start_time >= since)
        .where(AnalyticsSession.duration_seconds.isnot(None))
    ).scalar()

    avg_time_on_page = db.execute(
        select(func.avg(AnalyticsPageView.time_on_page))
        .where(AnalyticsPageView.timestamp >= since)
        .where(AnalyticsPageView.time_on_page.isnot(None))
    ).scalar()

    # CTA clicks WhatsApp (captación)
    cta_clicks = db.execute(
        select(func.count(AnalyticsEvent.id))
        .where(AnalyticsEvent.timestamp >= since)
        .where(AnalyticsEvent.event_name == "cta_whatsapp_click")
    ).scalar() or 0

    # Devices
    devices_result = db.execute(
        select(AnalyticsSession.device_type, func.count(AnalyticsSession.id))
        .where(AnalyticsSession.start_time >= since)
        .group_by(AnalyticsSession.device_type)
        .order_by(func.count(AnalyticsSession.id).desc())
    ).all()
    devices = [TopItem(label=d[0] or "Unknown", count=d[1], percentage=round(d[1] / max(total_sessions, 1) * 100, 1)) for d in devices_result]

    # Cities
    cities_result = db.execute(
        select(AnalyticsSession.city, func.count(AnalyticsSession.id))
        .where(AnalyticsSession.start_time >= since)
        .where(AnalyticsSession.city.isnot(None))
        .group_by(AnalyticsSession.city)
        .order_by(func.count(AnalyticsSession.id).desc())
        .limit(10)
    ).all()
    cities = [TopItem(label=c[0], count=c[1], percentage=round(c[1] / max(total_sessions, 1) * 100, 1)) for c in cities_result]

    # Browsers
    browsers_result = db.execute(
        select(AnalyticsSession.browser, func.count(AnalyticsSession.id))
        .where(AnalyticsSession.start_time >= since)
        .group_by(AnalyticsSession.browser)
        .order_by(func.count(AnalyticsSession.id).desc())
    ).all()
    browsers = [TopItem(label=b[0] or "Unknown", count=b[1], percentage=round(b[1] / max(total_sessions, 1) * 100, 1)) for b in browsers_result]

    # Hourly distribution (por page view timestamp, no session start — refleja actividad real)
    hourly_result = db.execute(
        select(func.hour(AnalyticsPageView.timestamp), func.count(AnalyticsPageView.id))
        .where(AnalyticsPageView.timestamp >= since)
        .group_by(func.hour(AnalyticsPageView.timestamp))
        .order_by(func.hour(AnalyticsPageView.timestamp))
    ).all()
    hourly = [TopItem(label=f"{h[0]:02d}:00", count=h[1], percentage=round(h[1] / max(total_page_views, 1) * 100, 1)) for h in hourly_result]

    # Daily distribution (por día de la semana, fechas ya en hora Lima UTC-5)
    daily_result = db.execute(
        select(func.dayofweek(AnalyticsSession.start_time), func.count(AnalyticsSession.id))
        .where(AnalyticsSession.start_time >= since)
        .group_by(func.dayofweek(AnalyticsSession.start_time))
        .order_by(func.dayofweek(AnalyticsSession.start_time))
    ).all()
    days_map = {1: "Domingo", 2: "Lunes", 3: "Martes", 4: "Miércoles", 5: "Jueves", 6: "Viernes", 7: "Sábado"}
    daily = [TopItem(label=days_map.get(d[0], "?"), count=d[1], percentage=round(d[1] / max(total_sessions, 1) * 100, 1)) for d in daily_result]

    # Pages (agrupar subrutas: /kapital/xxx → /kapital)
    pages_result = db.execute(
        select(AnalyticsPageView.page_path, func.count(AnalyticsPageView.id))
        .where(AnalyticsPageView.timestamp >= since)
        .group_by(AnalyticsPageView.page_path)
        .order_by(func.count(AnalyticsPageView.id).desc())
    ).all()

    # Agrupar manualmente subrutas
    pages_map: dict[str, int] = {}
    for path, count in pages_result:
        if path.startswith("/kapital/"):
            group = "/kapital"
        else:
            group = path
        pages_map[group] = pages_map.get(group, 0) + count

    sorted_pages = sorted(pages_map.items(), key=lambda x: x[1], reverse=True)[:10]
    pages = [TopItem(label=p[0], count=p[1], percentage=round(p[1] / max(total_page_views, 1) * 100, 1)) for p in sorted_pages]

    # Sessions over time (últimos 30 días, fechas ya en hora Lima UTC-5)
    sessions_time_result = db.execute(
        select(func.date(AnalyticsSession.start_time), func.count(AnalyticsSession.id))
        .where(AnalyticsSession.start_time >= since)
        .group_by(func.date(AnalyticsSession.start_time))
        .order_by(func.date(AnalyticsSession.start_time))
    ).all()
    sessions_over_time = [TimeSeriesItem(date=str(s[0]), count=s[1]) for s in sessions_time_result]

    summary = DashboardSummary(
        total_sessions=total_sessions,
        total_page_views=total_page_views,
        total_events=total_events,
        avg_duration_seconds=round(avg_duration, 1) if avg_duration else None,
        unique_visitors=unique_visitors,
        active_sessions=active_sessions,
    )

    return DashboardData(
        summary=summary,
        devices=devices,
        cities=cities,
        browsers=browsers,
        hourly_distribution=hourly,
        daily_distribution=daily,
        pages=pages,
        sessions_over_time=sessions_over_time,
        cta_clicks=cta_clicks,
        avg_time_on_page=round(avg_time_on_page, 1) if avg_time_on_page else None,
    )
