import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, and_, case, text
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.analytics import AnalyticsSession, AnalyticsPageView, AnalyticsEvent
from app.models.main import Calculation, CalculationType
from app.services.valora.recommender import read_valora_recommendations
from app.schemas.analytics import (
    TrackPayload,
    AnalyticsSessionCreate,
    AnalyticsSessionUpdate,
    AnalyticsPageViewCreate,
    AnalyticsEventCreate,
    DashboardData,
    DashboardSummary,
    CalculationFunnel,
    RetentionMetrics,
    OccupationProfileMetrics,
    TopItem,
    TimeSeriesItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["Analytics"])

# Lima, Peru timezone (UTC-5)
LIMA_TZ = timezone(timedelta(hours=-5))


def build_occupation_profile_metrics(rows) -> OccupationProfileMetrics:
    def normalize_label(value: object) -> str:
        return str(value or "").strip()

    def normalize_key(value: object) -> str:
        return normalize_label(value).casefold()

    def canonical_label(value: object) -> str:
        label = normalize_label(value)
        if not label:
            return "Otro"
        parts = [part.capitalize() for part in label.casefold().split()]
        return " ".join(parts)

    unique_devices = set()
    for metadata, timestamp in rows:
        if not isinstance(metadata, dict):
            continue
        device_id = str(metadata.get("device_id") or "").strip()
        audience = str(metadata.get("audience") or "").strip().lower()
        if not device_id or audience not in {"specialist"}:
            continue
        unique_devices.add(device_id)

    total_devices = len(unique_devices)
    audience_counts = {"Especialistas": 0, "Empresas": 0}
    role_counts: dict[str, dict[str, object]] = {}
    company_counts: dict[str, dict[str, object]] = {}
    for metadata, timestamp in rows:
        if not isinstance(metadata, dict):
            continue
        device_id = str(metadata.get("device_id") or "").strip()
        audience = str(metadata.get("audience") or "").strip().lower()
        if not device_id or audience not in {"specialist"}:
            continue
        raw_role = canonical_label(metadata.get("role"))
        raw_company = canonical_label(metadata.get("company") or metadata.get("company_name"))
        audience_counts["Especialistas"] += 1
        role_key = normalize_key(raw_role)
        company_key = normalize_key(raw_company)
        role_entry = role_counts.setdefault(role_key, {"label": raw_role, "count": 0})
        company_entry = company_counts.setdefault(company_key, {"label": raw_company, "count": 0})
        role_entry["label"] = role_entry["label"] or raw_role
        company_entry["label"] = company_entry["label"] or raw_company
        role_entry["count"] = int(role_entry["count"]) + 1
        company_entry["count"] = int(company_entry["count"]) + 1

    audience_counts["Empresas"] = len(company_counts)

    specialist_total = audience_counts["Especialistas"]
    audiences = [
        TopItem(
            label=label,
            count=count,
            percentage=round(count / max(total_devices, 1) * 100, 1),
        )
        for label, count in audience_counts.items()
    ]
    specialist_roles = [
        TopItem(
            label=value["label"],
            count=int(value["count"]),
            percentage=round(int(value["count"]) / max(specialist_total, 1) * 100, 1),
        )
        for _, value in sorted(
            role_counts.items(), key=lambda item: (-int(item[1]["count"]), item[1]["label"])
        )
    ]
    company_names = [
        TopItem(
            label=value["label"],
            count=int(value["count"]),
            percentage=round(int(value["count"]) / max(audience_counts["Empresas"], 1) * 100, 1),
        )
        for _, value in sorted(
            company_counts.items(), key=lambda item: (-int(item[1]["count"]), item[1]["label"])
        )
    ]
    return OccupationProfileMetrics(
        total_devices=total_devices,
        audiences=audiences,
        specialist_roles=specialist_roles,
        company_names=company_names,
    )


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
        # Completar los datos que no estaban disponibles al crear la sesión.
        updated = False
        if payload.user_id and not session.user_id:
            session.user_id = payload.user_id
            updated = True
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

    kapital_visitor_key = case(
        (
            AnalyticsSession.user_id.isnot(None),
            func.concat("user:", AnalyticsSession.user_id),
        ),
        (
            AnalyticsSession.ip_address.isnot(None),
            func.concat("ip:", AnalyticsSession.ip_address),
        ),
        else_=func.concat("session:", AnalyticsSession.session_id),
    )
    users_started = db.execute(
        select(func.count(func.distinct(kapital_visitor_key)))
        .select_from(AnalyticsEvent)
        .join(
            AnalyticsSession,
            AnalyticsSession.session_id == AnalyticsEvent.session_id,
        )
        .where(AnalyticsEvent.timestamp >= since)
        .where(AnalyticsEvent.event_name == "kapital_calculator_started")
    ).scalar() or 0
    kapital_visitors = db.execute(
        select(func.count(func.distinct(kapital_visitor_key)))
        .select_from(AnalyticsPageView)
        .join(
            AnalyticsSession,
            AnalyticsSession.session_id == AnalyticsPageView.session_id,
        )
        .where(AnalyticsPageView.timestamp >= since)
        .where(AnalyticsPageView.page_path.like("/kapital%"))
    ).scalar() or 0
    activation_rate = round(
        users_started / kapital_visitors * 100, 1
    ) if kapital_visitors else 0.0

    attempt_id = func.json_unquote(
        func.json_extract(AnalyticsEvent.event_metadata, "$.attempt_id")
    )
    calculation_mode = func.json_unquote(
        func.json_extract(AnalyticsEvent.event_metadata, "$.calculation_mode")
    )
    started_attempts = (
        select(attempt_id.label("attempt_id"))
        .where(AnalyticsEvent.timestamp >= since)
        .where(AnalyticsEvent.event_name == "kapital_calculation_started")
        .where(calculation_mode == "initial")
        .where(attempt_id.isnot(None))
        .distinct()
        .subquery()
    )
    completed_attempts = (
        select(attempt_id.label("attempt_id"))
        .where(AnalyticsEvent.timestamp >= since)
        .where(AnalyticsEvent.event_name == "kapital_calculation_completed")
        .where(calculation_mode == "sensitivity")
        .where(attempt_id.isnot(None))
        .distinct()
        .subquery()
    )
    calculations_started = db.execute(
        select(func.count(started_attempts.c.attempt_id))
    ).scalar() or 0
    calculations_completed = db.execute(
        select(func.count(completed_attempts.c.attempt_id)).select_from(
            completed_attempts.join(
                started_attempts,
                started_attempts.c.attempt_id == completed_attempts.c.attempt_id,
            )
        )
    ).scalar() or 0
    completion_rate = round(
        calculations_completed / calculations_started * 100, 1
    ) if calculations_started else 0.0
    first_kapital_visits = (
        select(
            kapital_visitor_key.label("visitor_key"),
            func.min(AnalyticsPageView.timestamp).label("first_visit"),
        )
        .join(
            AnalyticsPageView,
            AnalyticsPageView.session_id == AnalyticsSession.session_id,
        )
        .where(kapital_visitor_key.isnot(None))
        .where(AnalyticsPageView.page_path.like("/kapital%"))
        .group_by(kapital_visitor_key)
        .subquery()
    )
    period_kapital_visitors = (
        select(kapital_visitor_key.label("visitor_key"))
        .join(
            AnalyticsPageView,
            AnalyticsPageView.session_id == AnalyticsSession.session_id,
        )
        .where(kapital_visitor_key.isnot(None))
        .where(AnalyticsPageView.timestamp >= since)
        .where(AnalyticsPageView.page_path.like("/kapital%"))
        .distinct()
        .subquery()
    )
    new_users, recurring_users = db.execute(
        select(
            func.coalesce(
                func.sum(case((first_kapital_visits.c.first_visit >= since, 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((first_kapital_visits.c.first_visit < since, 1), else_=0)),
                0,
            ),
        ).select_from(
            period_kapital_visitors.join(
                first_kapital_visits,
                first_kapital_visits.c.visitor_key
                == period_kapital_visitors.c.visitor_key,
            )
        )
    ).one()

    occupation_rows = db.execute(
        select(AnalyticsEvent.event_metadata, AnalyticsEvent.timestamp)
        .where(AnalyticsEvent.timestamp >= since)
        .where(AnalyticsEvent.event_name == "occupation_profile_completed")
        .order_by(AnalyticsEvent.timestamp.asc())
    ).all()
    occupation_profiles = build_occupation_profile_metrics(occupation_rows)

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
        normalized_path = path.split("?", 1)[0] or "/"
        if normalized_path.startswith("/kapital/"):
            group = "/kapital"
        else:
            group = normalized_path
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
        kapital_funnel=CalculationFunnel(
            users_started=users_started,
            activation_rate=activation_rate,
            started=calculations_started,
            completed=calculations_completed,
            completion_rate=completion_rate,
        ),
        kapital_retention=RetentionMetrics(
            new_users=int(new_users),
            recurring_users=int(recurring_users),
        ),
        occupation_profiles=occupation_profiles,
        cta_clicks=cta_clicks,
        avg_time_on_page=round(avg_time_on_page, 1) if avg_time_on_page else None,
    )


@router.get("/valora-recommendations/{calculation_id}")
async def get_valora_recommendations(
    calculation_id: int, db: Session = Depends(get_db)
):
    """
    Devuelve las tasas recomendadas para el módulo de sensibilidad de Valora
    leyendo directamente la copia de trabajo en Excel Online.
    """
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")

    if calculation.type != CalculationType.VALORA:
        raise HTTPException(
            status_code=400, detail="Solo disponible para cálculos Valora"
        )

    data = calculation.data or {}
    file_meta = data.get("file") or {}
    item_id = file_meta.get("onedrive_item_id")
    session_id = data.get("active_session_id")

    if not item_id:
        raise HTTPException(
            status_code=400, detail="No se encontró el archivo de trabajo (onedrive_item_id)"
        )

    logger.info(
        f"[VALORA RECOMMENDATIONS] calculation_id={calculation_id}, "
        f"item_id={item_id}, session_id={session_id}"
    )

    try:
        result = await read_valora_recommendations(
            item_id,
            session_id=session_id,
            calculation_data=calculation.data,
            db=db,
        )
        logger.info(
            f"[VALORA RECOMMENDATIONS] Recomendaciones obtenidas exitosamente para calculation_id={calculation_id}"
        )
        return result
    except Exception as e:
        logger.exception(
            f"[VALORA RECOMMENDATIONS] Error obteniendo recomendaciones: {e}"
        )
        raise HTTPException(
            status_code=502, detail="Error leyendo recomendaciones del Excel"
        )
