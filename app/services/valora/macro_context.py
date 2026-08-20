# app/services/valora/macro_context.py
"""
Construye el contexto macroeconómico/sectorial para la estimación de tasas Valora.
Lee los complementos de plantilla (Damodaran, EMBI, IR, RF, prima, riesgo, tax)
que el admin carga en el sistema.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.main import TemplateComplement

logger = logging.getLogger(__name__)


def _extract_year(date_value: Any) -> str | None:
    """Extrae el año a 4 dígitos de una fecha (string, año numérico o serial Excel)."""
    if date_value is None or date_value == "":
        return None

    # Número que ya es un año
    if isinstance(date_value, (int, float)):
        if 1000 <= float(date_value) <= 9999:
            return str(int(date_value))
        # Serial de Excel (rango aproximado 1982-2070)
        try:
            serial = float(date_value)
            if 30000 <= serial <= 50000:
                dt = datetime(1899, 12, 30) + timedelta(days=serial)
                return str(dt.year)
        except (ValueError, TypeError):
            pass
        return None

    # String con año
    match = re.search(r"\d{4}", str(date_value))
    return match.group(0) if match else None


def _fetch_complement(db: Session, name: str) -> list[dict[str, Any]]:
    """Obtiene el último complemento activo por nombre."""
    comp = (
        db.execute(
            select(TemplateComplement)
            .where(
                TemplateComplement.nombre == name,
                TemplateComplement.deleted_at.is_(None),
            )
            .order_by(TemplateComplement.created_at.desc())
        )
        .scalars()
        .first()
    )
    return comp.data if comp and isinstance(comp.data, list) else []


def build_valora_macro_context(
    db: Session, date_str: str | None, country: str | None, industry: str | None
) -> dict[str, Any]:
    """
    Arma un dict con datos de configuración del sistema relevantes para Valora.

    Args:
        db: Sesión de SQLAlchemy.
        date_str: Fecha del cálculo (ej. "31/12/2023").
        country: País (ej. "Peru").
        industry: Industria/Sector (ej. "Software").

    Returns:
        Dict con Damodaran, EMBI, IR, RF, prima, riesgo y tax.
    """
    year = _extract_year(date_str)

    context: dict[str, Any] = {
        "date": date_str,
        "year": year,
        "country": country,
        "industry": industry,
    }

    # Damodaran: beta, cost of equity, etc. por año + industria
    damodaran: dict[str, Any] | None = None
    if year and industry:
        damo_data = _fetch_complement(db, "damodaran")
        for item in damo_data:
            if (
                str(item.get("fecha")) == year
                and str(item.get("industria", "")).lower() == industry.lower()
            ):
                damodaran = item
                break
    context["damodaran"] = damodaran

    # EMBI: spread país para la fecha
    embi: dict[str, Any] | None = None
    if date_str and country:
        embi_data = _fetch_complement(db, "embi")
        embi_match = next(
            (item for item in embi_data if item.get("fecha") == date_str), None
        )
        if embi_match:
            country_key = next(
                (k for k in embi_match.keys() if k.lower() == country.lower()), None
            )
            embi = {
                "date": embi_match.get("fecha"),
                "country": country,
                "value": embi_match.get(country_key) if country_key else None,
            }
    context["embi"] = embi

    # IR (impuesto a la renta) por país + año
    ir: dict[str, Any] | None = None
    if year and country:
        ir_data = _fetch_complement(db, "ir")
        for item in ir_data:
            if (
                str(item.get("pais", "")).lower() == country.lower()
                and str(item.get("fecha")) == year
            ):
                ir = {"country": country, "year": year, "value": item.get("valor")}
                break
    context["ir"] = ir

    # RF (tasa libre de riesgo) para la fecha
    rf: dict[str, Any] | None = None
    if date_str:
        rf_data = _fetch_complement(db, "rf")
        rf_match = next(
            (item for item in rf_data if item.get("fecha") == date_str), None
        )
        if rf_match:
            rf = {"date": date_str, **{k: v for k, v in rf_match.items() if k != "fecha"}}
    context["rf"] = rf

    # Prima de riesgo de mercado por año
    prima: dict[str, Any] | None = None
    if year:
        prima_data = _fetch_complement(db, "prima")
        prima = next(
            (item for item in prima_data if str(item.get("fecha")) == year), None
        )
    context["prima"] = prima

    # Tasa impositiva por año
    tax: dict[str, Any] | None = None
    if year:
        tax_data = _fetch_complement(db, "tax")
        tax = next(
            (item for item in tax_data if str(item.get("fecha")) == year), None
        )
    context["tax"] = tax

    # Riesgo país por año
    riesgo: list[dict[str, Any]] = []
    if year:
        riesgo_data = _fetch_complement(db, "riesgo")
        riesgo = [
            item for item in riesgo_data if str(item.get("fecha")) == year
        ]
    context["riesgo"] = riesgo

    logger.info(
        f"[VALORA MACRO CONTEXT] date={date_str} country={country} "
        f"industry={industry} damodaran={damodaran is not None} "
        f"embi={embi is not None} ir={ir is not None} rf={rf is not None}"
    )
    return context
