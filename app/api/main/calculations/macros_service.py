# app/api/main/calculations_router.py
import os
import re
import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import (
    KAPITAL_DAMODARAN_CELL_MAP,
)
from app.models.main import CalculationType, TemplateComplement
from app.models.templates import MasterTemplate
from app.services.onedrive.service import OneDriveConfig, get_onedrive_service

from .excel_engine import _build_template_copy_name


def get_default_or_latest_master_template(db: Session) -> MasterTemplate | None:
    t0 = time.perf_counter()
    template = (
        db.execute(
            select(MasterTemplate)
            .where(
                MasterTemplate.deleted_at.is_(None),
                MasterTemplate.is_default.is_(True),
            )
            .order_by(MasterTemplate.updated_at.desc(), MasterTemplate.id.desc())
        )
        .scalars()
        .first()
    )
    if template:
        print(f"[DB] get_default_or_latest_master_template (default): {time.perf_counter() - t0:.3f} seg", flush=True)
        return template

    template = (
        db.execute(
            select(MasterTemplate)
            .where(MasterTemplate.deleted_at.is_(None))
            .order_by(MasterTemplate.created_at.desc(), MasterTemplate.id.desc())
        )
        .scalars()
        .first()
    )
    print(f"[DB] get_default_or_latest_master_template (fallback): {time.perf_counter() - t0:.3f} seg", flush=True)
    return template


async def _clone_default_template_for_calculation(
    db: Session,
    calc_type: CalculationType,
) -> dict:
    source_template = get_default_or_latest_master_template(db)
    if not source_template or source_template.deleted_at is not None:
        raise HTTPException(
            status_code=400, detail="No master template available to clone"
        )

    if not source_template.onedrive_item_id:
        raise HTTPException(
            status_code=400, detail="Default master template has no OneDrive file"
        )

    one_drive_cfg = OneDriveConfig()
    if not one_drive_cfg.is_configured():
        raise HTTPException(status_code=503, detail="OneDrive is not configured")

    source_filename = (
        source_template.onedrive_filename or f"template-{source_template.id}.xlsx"
    )
    suffix = os.path.splitext(source_filename)[1] or ".xlsx"
    base_name = _build_template_copy_name(calc_type)
    copied_filename = f"{base_name}{suffix}"
    target_env = source_template.onedrive_env or "development"
    target_folder = calc_type.value

    service = get_onedrive_service()
    copied_item = await service.copy_file(
        source_item_id=source_template.onedrive_item_id,
        new_filename=copied_filename,
        env=target_env,
        folder=target_folder,
    )

    return {
        "onedrive_item_id": copied_item.get("id"),
        "original_name": source_filename,
        "copied_name": copied_filename,
    }


def _inject_macro_data_into_payload(db: Session, payload_data: dict) -> None:
    """
    Toma el payload proveniente del frontend, extrae los parámetros clave
    y busca en la BD los datos exactos para inyectarlos en el input.
    """
    if "inputs" not in payload_data or not payload_data["inputs"]:
        return

    t0 = time.perf_counter()
    # Trabajamos directamente sobre la referencia del último input para mutarlo
    latest_input = payload_data["inputs"][-1]
    _enrich_input_with_macros(db, latest_input)
    print(f"[DB] _inject_macro_data_into_payload total: {time.perf_counter() - t0:.3f} seg", flush=True)


def _enrich_input_with_macros(db: Session, input_dict: dict) -> None:
    """
    Enriquece un diccionario de input individual con datos de complementos de la BD.
    """
    t0 = time.perf_counter()
    date = str(input_dict.get("fecha", "")).strip()

    year = ""
    match = re.search(r"\d{4}", date)
    if match:
        year = match.group(0)

    country = input_dict.get("pais")
    industry = input_dict.get("industria")
    anio_bono = input_dict.get("anio_bono")

    # Helper interno para buscar en la BD
    def _fetch_complement_data(name: str) -> list:
        t_comp = time.perf_counter()
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
        print(f"[DB] _fetch_complement_data '{name}': {time.perf_counter() - t_comp:.3f} seg", flush=True)
        return comp.data if comp and isinstance(comp.data, list) else []

    if date:
        rf_data = _fetch_complement_data("rf")
        rf_match = next((item for item in rf_data if item.get("fecha") == date), None)

        if rf_match and anio_bono is not None:
            # Formateamos a 2 decimales
            try:
                formatted_anio = f"{float(anio_bono):.2f}"
            except ValueError:
                formatted_anio = str(anio_bono)

            valor_rf = rf_match.get(formatted_anio)
            if valor_rf is not None:
                input_dict["rf"] = {"fecha": rf_match.get("fecha"), "year": valor_rf}
            else:
                input_dict["rf"] = {}
        else:
            input_dict["rf"] = {}

        # EMBI: Extraemos solo la fecha y el país seleccionado
        embi_data = _fetch_complement_data("embi")
        embi_match = next(
            (item for item in embi_data if item.get("fecha") == date), None
        )
        if embi_match and country:
            filtered_embi = {"fecha": embi_match.get("fecha")}
            country_key = next(
                (k for k in embi_match.keys() if k.lower() == country.lower()), None
            )
            if country_key:
                filtered_embi["country"] = embi_match.get(country_key)
            input_dict["embi"] = filtered_embi
        else:
            input_dict["embi"] = {}

    if year:
        riesgo_data = _fetch_complement_data("riesgo")
        riesgo_matches = [
            item for item in riesgo_data if str(item.get("fecha")) == year
        ]

        prima_data = _fetch_complement_data("prima")
        prima_match = next(
            (item for item in prima_data if str(item.get("fecha")) == year), None
        )
        input_dict["prima"] = prima_match if prima_match else {}

        tax_data = _fetch_complement_data("tax")
        tax_match = next(
            (item for item in tax_data if str(item.get("fecha")) == year), None
        )
        input_dict["tax"] = tax_match if tax_match else {}

        if industry:
            damo_data = _fetch_complement_data("damodaran")
            damo_match = next(
                (
                    item
                    for item in damo_data
                    if str(item.get("fecha")) == year
                    and item.get("industria") == industry
                ),
                None,
            )
            if damo_match:
                # Retenemos solo las llaves activas en el mapa
                allowed_keys = KAPITAL_DAMODARAN_CELL_MAP.keys()
                input_dict["damodaran"] = {
                    k: v for k, v in damo_match.items() if k in allowed_keys
                }
            else:
                input_dict["damodaran"] = {}

        if country:
            ir_data = _fetch_complement_data("ir")
            ir_payload = {"pais": country}  # Inicializamos con el nombre del país

            for item in ir_data:
                if (
                    str(item.get("pais")).lower() == country.lower()
                    and str(item.get("fecha")) == year
                ):
                    ir_payload["year"] = item.get("valor")
                    break
            input_dict["ir"] = ir_payload

        flattened_riesgo = {}
        if riesgo_matches:
            flattened_riesgo["fecha"] = year
            for idx, r_item in enumerate(riesgo_matches, start=1):
                flattened_riesgo[f"num{idx}_basis_spread"] = r_item.get("basis_spread")
                flattened_riesgo[f"num{idx}_max_deviation"] = r_item.get(
                    "max_deviation"
                )
                flattened_riesgo[f"num{idx}_min_deviation"] = r_item.get(
                    "min_deviation"
                )

        input_dict["riesgo"] = flattened_riesgo
    print(f"[DB] _enrich_input_with_macros total: {time.perf_counter() - t0:.3f} seg", flush=True)

