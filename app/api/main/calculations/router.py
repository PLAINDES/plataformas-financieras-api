# app/api/main/calculations_router.py
import os
import logging
import re
import json
import time
from datetime import datetime as _dt
from uuid import uuid4
from typing import Any, List, Optional
import httpx
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select
from urllib.parse import quote

from app.db.database import get_db
from app.models.main import Calculation, CalculationType, TemplateComplement
from app.models.templates import MasterTemplate
from app.schemas.main import CalculationCreate, CalculationUpdate, CalculationResponse
from app.services.onedrive_service import get_onedrive_service, OneDriveConfig
from app.core.constants import (
    KAPITAL_INPUT_CELL_MAP,
    KAPITAL_INPUT_SHEET,
    KAPITAL_RESULTS_BOA_CELL,
    KAPITAL_RESULTS_CELL_MAP,
    KAPITAL_RESULTS_SHEET,
    KAPITAL_SENSITIVITY_CELL_MAP,
    KAPITAL_SENSITIVITY_INPUT_CELL_MAP,
    KAPITAL_EXPECTED_DEVALUATION,
    KAPITAL_DAMODARAN_CELL_MAP,
    KAPITAL_PRIMA_CELL_MAP,
    KAPITAL_EMBI_CELL_MAP,
    KAPITAL_RF_CELL_MAP,
    KAPITAL_RIESGO_CELL_MAP,
    KAPITAL_INPUT_WACC,
    KAPITAL_TAX_CELL_MAP
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/main", tags=["Calculations"])

# ==================== HELPER FUNCTIONS ====================

def _to_calc_type(value: str | CalculationType) -> CalculationType:
    return value if isinstance(value, CalculationType) else CalculationType(value)

def _build_template_copy_name(calc_type: CalculationType) -> str:
    return f"{calc_type.value}-{uuid4().hex}"

def _extract_input_payload(data: object) -> dict:
    if not isinstance(data, dict):
        return {}

    maybe_inputs = data.get("inputs")
    if isinstance(maybe_inputs, list) and maybe_inputs:
        latest = maybe_inputs[-1]
        if not isinstance(latest, dict):
            return {}
        return {
            k: v for k, v in latest.items() if k != "created_at"
        }

    return {
        k: v
        for k, v in data.items()
        if k
        not in {
            "inputs",
            "resultados",
            "sensibilizacion",
            "file",
            "created_at",
        }
    }

def _sanitize_input_for_history(input_payload: object) -> dict:
    if not isinstance(input_payload, dict):
        return {}
    # beta_desapalancado solo se usa para sensibilizacion (BOA), no para historial base de inputs
    return {
        k: v
        for k, v in input_payload.items()
        if k not in {"created_at", "beta_desapalancado"}
    }

def _extract_latest_input_from_history(data: object) -> dict:
    if not isinstance(data, dict):
        return {}
    raw_inputs = data.get("inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        return {}
    latest = raw_inputs[0]
    return latest if isinstance(latest, dict) else {}

def _merge_unique_entries(existing_entries: list[dict], incoming_entries: object) -> list[dict]:
    merged = list(existing_entries)
    incoming = _stamp_entries(incoming_entries)
    if not incoming:
        return merged

    existing_keys = {
        json.dumps(_entry_payload_without_timestamp(entry), sort_keys=True, ensure_ascii=False)
        for entry in merged
    }
    for entry in incoming:
        key = json.dumps(_entry_payload_without_timestamp(entry), sort_keys=True, ensure_ascii=False)
        if key in existing_keys:
            continue
        merged.append(entry)
        existing_keys.add(key)
    return _stamp_entries(merged)

def _now_iso() -> str:
    return _dt.utcnow().replace(microsecond=0).isoformat()

def _extract_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    cleaned = text.replace("%", "").replace(" ", "").replace("\u00a0", "")

    if "," in cleaned and "." in cleaned:
        last_comma = cleaned.rfind(",")
        last_dot = cleaned.rfind(".")
        if last_comma > last_dot:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")

    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None

def _first_matrix_value(matrix: object) -> object:
    if not isinstance(matrix, list) or not matrix:
        return None
    first_row = matrix[0]
    if not isinstance(first_row, list) or not first_row:
        return None
    return first_row[0]

async def _read_rendered_cell_number(
    service,
    item_id: str,
    sheet_name: str,
    cell: str,
    session_id: str | None = None,
) -> str | None:
    cell_data = await service.read_excel_cell(
        item_id=item_id,
        sheet_name=sheet_name,
        cell_address=cell,
        session_id=session_id,
    )

    # 1. Prioriza SIEMPRE la propiedad 'text' de Graph API (El valor renderizado exacto)
    text_value = _first_matrix_value((cell_data or {}).get("text"))
    if text_value is not None and str(text_value).strip() != "":
        return str(text_value).strip()

    # 2. Fallback al valor crudo si text no está disponible
    value = _first_matrix_value((cell_data or {}).get("values"))
    return str(value) if value is not None else None


def _date_to_excel_serial(date_str: str) -> int | None:
    """
    Convierte una fecha en formato dd/mm/yyyy a un número serial de Excel.
    Excel usa epoch 1/1/1900 = 1, con el bug de que cuenta 29/02/1900
    (que no existió) como día 60.
    """

    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            dt = _dt.strptime(date_str.strip(), fmt)
            excel_epoch = _dt(1899, 12, 30)
            delta = dt - excel_epoch
            return delta.days
        except ValueError:
            continue
    return None

def _to_excel_input_value(field: str, value: object) -> object:
    if value is None:
        return value

    if field == "fecha" and isinstance(value, str):
        serial = _date_to_excel_serial(value)
        if serial is not None:
            return serial
        return value

    percentage_like_fields = {
        "tasa_impositiva",
        "devaluacion",
        "costo_deuda",
        "porcentaje_deuda",
        "porcentaje_capital",
        "tasa_efectiva_impuesto",
        "country"
    }
    if field not in percentage_like_fields:
        return value

    n = _extract_number(value)
    if n is None:
        return value

    # Para country, hacer división extra por 100
    if field == "country":
        return n / 10000 if abs(n) > 1 else n / 100

    if field == "devaluacion" or field == "costo_deuda":
        return n / 100

    return n / 100 if abs(n) > 1 else n

# --- METODO PARA RUTAS BATCH ---
def _build_excel_range_url(user_email: str, item_id: str, sheet_name: str, cell: str) -> str:
    return f"/users/{user_email}/drive/items/{item_id}/workbook/worksheets('{quote(sheet_name)}')/range(address='{quote(cell)}')"

# =========================================================
# LÓGICA CORE DE BATCHING (LECTURA Y ESCRITURA MASIVA)
# =========================================================

async def _write_inputs_to_excel(
    item_id: str, input_payload: dict, session_id: str | None = None
) -> None:
    service = get_onedrive_service()
    email = service.config.user_email

    write_requests = []
    req_id = 1

    def add_write_req(field_data, cell_map, sheet_name=KAPITAL_INPUT_SHEET):
        nonlocal req_id
        # Si field_data no es un diccionario válido, salimos
        if not isinstance(field_data, dict):
            return

        for f, cell in cell_map.items():
            # Buscamos 'f' dentro de 'field_data', NO en 'input_payload'
            if not cell or f not in field_data:
                continue
            mapped_val = _to_excel_input_value(f, field_data[f])
            headers = {"Content-Type": "application/json"}
            if session_id:
                headers["workbook-session-id"] = session_id

            write_requests.append({
                "id": str(req_id),
                "method": "PATCH",
                "url": _build_excel_range_url(email, item_id, sheet_name, cell),
                "body": {"values": [[mapped_val]]},
                "headers": headers
            })
            req_id += 1

    add_write_req(input_payload, KAPITAL_INPUT_CELL_MAP)
    add_write_req(input_payload, KAPITAL_SENSITIVITY_INPUT_CELL_MAP)

    # tasa impositiva y devaluacion para WACC
    add_write_req(input_payload, KAPITAL_INPUT_WACC, KAPITAL_RESULTS_SHEET)

    # Guardamos los datos de damodaran, rf, ir, embi, prima y riesgo en el excel

    add_write_req(input_payload.get("damodaran", {}), KAPITAL_DAMODARAN_CELL_MAP, KAPITAL_RESULTS_SHEET)
    add_write_req(input_payload.get("prima", {}), KAPITAL_PRIMA_CELL_MAP, KAPITAL_RESULTS_SHEET)
    add_write_req(input_payload.get("embi", {}), KAPITAL_EMBI_CELL_MAP, KAPITAL_RESULTS_SHEET)
    add_write_req(input_payload.get("rf", {}), KAPITAL_RF_CELL_MAP, KAPITAL_RESULTS_SHEET)
    add_write_req(input_payload.get("riesgo", {}), KAPITAL_RIESGO_CELL_MAP, KAPITAL_RESULTS_SHEET)
    add_write_req(input_payload.get("tax", {}), KAPITAL_TAX_CELL_MAP, KAPITAL_RESULTS_SHEET)

    # Enviar a Microsoft en lotes de 20 (Límite del API Graph)
    chunks = [write_requests[i:i+20] for i in range(0, len(write_requests), 20)]
    batch_tasks = [service.execute_batch(chunk) for chunk in chunks]
    if batch_tasks:
        await asyncio.gather(*batch_tasks)

async def _read_market_block(
    service,
    item_id: str,
    sheet_name: str,
    block_map: dict[str, str],
    session_id: str | None = None,
) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for field, cell in block_map.items():
        result[field] = await _read_rendered_cell_number(service, item_id, sheet_name, cell, session_id=session_id)
    return result

async def _build_excel_output_entries(
    item_id: str, session_id: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    service = get_onedrive_service()
    email = service.config.user_email

    read_requests = []
    mapping = {}  # Mapeamos ID -> (Categoria, Mercado, Campo)
    req_id = 1

    # Preparar estructuras vacías para evitar KeyErrors
    resultados_entry = {"created_at": _now_iso()}
    for m in KAPITAL_RESULTS_CELL_MAP.keys():
        resultados_entry[m] = {}

    sensibilidad_entry = {"created_at": _now_iso()}
    for m in KAPITAL_SENSITIVITY_CELL_MAP.keys():
        sensibilidad_entry[m] = {}

    def add_read_req(category, sheet, block_map, market_name=None):
        nonlocal req_id
        for field, cell in block_map.items():
            mapping[str(req_id)] = (category, market_name, field)
            read_requests.append({
                "id": str(req_id),
                "method": "GET",
                "url": _build_excel_range_url(email, item_id, sheet, cell),
                "headers": {"workbook-session-id": session_id} if session_id else {}
            })
            req_id += 1

    # 1. Peticiones de Resultados Generales
    for market, block in KAPITAL_RESULTS_CELL_MAP.items():
        add_read_req("resultados", KAPITAL_RESULTS_SHEET, block, market)

    # 2. Peticiones de Sensibilización
    for market, block in KAPITAL_SENSITIVITY_CELL_MAP.items():
        add_read_req("sensibilidad", KAPITAL_RESULTS_SHEET, block, market)

    # 3. Peticiones de los BOAs (Resultados y Sensibilidad)
    add_read_req("boa_res", KAPITAL_RESULTS_SHEET, {"boa": KAPITAL_RESULTS_BOA_CELL})
    add_read_req("boa_sens", KAPITAL_INPUT_SHEET, {"boa": KAPITAL_SENSITIVITY_INPUT_CELL_MAP["beta_desapalancado"]})

    # Dividir las celdas en lotes de 20 y ejecutar simultáneamente
    chunks = [read_requests[i:i+20] for i in range(0, len(read_requests), 20)]
    batch_tasks = [service.execute_batch(chunk) for chunk in chunks]
    batch_results = await asyncio.gather(*batch_tasks)

    # Procesar el mega-paquete de respuestas
    for chunk_responses in batch_results:
        for resp in chunk_responses:
            cat, market, field = mapping[resp["id"]]

            val = None
            if resp.get("status") == 200:
                body = resp.get("body", {})
                txt = _first_matrix_value(body.get("text"))
                if txt is not None and str(txt).strip() != "":
                    val = str(txt).strip()
                else:
                    raw_val = _first_matrix_value(body.get("values"))
                    val = str(raw_val) if raw_val is not None else None

            # Asignar los valores limpios al diccionario que le corresponde
            if cat == "resultados":
                resultados_entry[market][field] = val
            elif cat == "sensibilidad":
                sensibilidad_entry[market][field] = val
            elif cat == "boa_res":
                resultados_entry["boa"] = _extract_number(val)
            elif cat == "boa_sens":
                sensibilidad_entry["boa"] = _extract_number(val)


    return resultados_entry, sensibilidad_entry

async def _enrich_payload_with_excel_outputs(
    payload_data: object,
    item_id: str | None,
    *,
    include_resultados: bool,
    include_sensibilizacion: bool,
    existing_session_id: str | None = None
) -> object:

    t_start = time.perf_counter()

    if not isinstance(payload_data, dict) or not item_id:
        return payload_data

    enriched = dict(payload_data)
    latest_input = _extract_input_payload(enriched)
    service = get_onedrive_service()

    session_id = existing_session_id

    # Si no nos pasaron sesión, creamos una nueva
    if not session_id:
        t0 = time.perf_counter()
        session_id = await service._create_workbook_session(item_id, persist_changes=True)
        print(f"[RAM] Nueva sesión creada: {time.perf_counter() - t0:.2f} seg", flush=True)
    else:
        print(f"Intentando reusar sesión: {session_id}", flush=True)

    async def _execute_excel_logic(sid: str):
        if latest_input:
            t1 = time.perf_counter()
            await _write_inputs_to_excel(item_id=item_id, input_payload=latest_input, session_id=sid)
            print(f"[BATCH] Escritura: {time.perf_counter() - t1:.2f} seg", flush=True)

        t2 = time.perf_counter()
        await service.force_calculate_excel(item_id, session_id=sid)
        print(f"[TIMER] Recálculo forzado: {time.perf_counter() - t2:.2f} seg", flush=True)

        await asyncio.sleep(0.5)

        t3 = time.perf_counter()
        res, sens = await _build_excel_output_entries(item_id, session_id=sid)
        print(f"[BATCH] Lectura: {time.perf_counter() - t3:.2f} seg", flush=True)
        return res, sens

    try:
        resultados_entry, sensibilidad_entry = await _execute_excel_logic(session_id)
    except Exception as e:
        logger.warning(f"Sesión expirada o inválida ({e}). Reintentando con sesión nueva...")
        # Si falló, forzamos una nueva creación de sesión (recursividad segura)
        return await _enrich_payload_with_excel_outputs(
            payload_data, item_id,
            include_resultados=include_resultados,
            include_sensibilizacion=include_sensibilizacion,
            existing_session_id=None 
        )

    print(f"TIEMPO TOTAL ENRICH: {time.perf_counter() - t_start:.2f} seg", flush=True)

    enriched["resultados"] = [resultados_entry] if include_resultados else []
    enriched["sensibilizacion"] = [sensibilidad_entry] if include_sensibilizacion else []

    # GUARDAMOS LA SESIÓN ACTIVA EN EL PAYLOAD
    enriched["active_session_id"] = session_id 

    return enriched

def _entry_payload_without_timestamp(entry: object) -> dict:
    if not isinstance(entry, dict):
        return {}
    return {k: v for k, v in entry.items() if k != "created_at"}

def _stamp_entries(entries: object) -> list[dict]:
    stamped: list[dict] = []
    if not isinstance(entries, list):
        return stamped

    for raw in entries:
        if not isinstance(raw, dict):
            continue
        current = dict(raw)
        if not current.get("created_at"):
            current["created_at"] = _now_iso()
        stamped.append(current)

    stamped.sort(key=lambda e: str(e.get("created_at") or ""), reverse=True)
    return stamped

def _normalize_calculation_data(
    payload_data: object,
    existing_data: object = None,
    file_meta: dict | None = None,
    *,
    include_input_history: bool = True,
    include_resultados_history: bool = True,
    include_sensibilizacion_history: bool = True,
) -> dict:
    existing = existing_data if isinstance(existing_data, dict) else {}

    # 1. Cargamos el historial existente limpio
    inputs = _stamp_entries(existing.get("inputs") or [])
    resultados = _stamp_entries(existing.get("resultados") or [])
    sensibilizacion = _stamp_entries(existing.get("sensibilizacion") or [])

    # 2. Procesamos los inputs que vienen del frontend, reemplazamos
    incoming_input = _extract_input_payload(payload_data)
    if include_input_history and incoming_input:
        # Solo dejamos 1 elemento en la lista, el entrante.
        inputs = _stamp_entries([{**incoming_input, "created_at": _now_iso()}])

    # 3. Guardamos los resultados (que ahora traen estrictamente solo 1 registro nuevo)
    if isinstance(payload_data, dict):
        incoming_results = payload_data.get("resultados")
        if include_resultados_history and isinstance(incoming_results, list) and incoming_results:
            resultados = _stamp_entries(incoming_results)

        incoming_sens = payload_data.get("sensibilizacion")
        if include_sensibilizacion_history and isinstance(incoming_sens, list) and incoming_sens:
            sensibilizacion = _merge_unique_entries(sensibilizacion, incoming_sens)

    normalized = {
        "inputs": inputs,
        "resultados": resultados,
        "sensibilizacion": sensibilizacion,
    }

    current_file_raw = existing.get("file") if isinstance(existing.get("file"), dict) else None

    if file_meta:
        normalized["file"] = file_meta
    elif current_file_raw:
        normalized["file"] = current_file_raw

    if isinstance(payload_data, dict) and "active_session_id" in payload_data:
        normalized["active_session_id"] = payload_data["active_session_id"]
    elif isinstance(existing, dict) and "active_session_id" in existing:
        normalized["active_session_id"] = existing["active_session_id"]

    return normalized

def get_default_or_latest_master_template(db: Session) -> MasterTemplate | None:
    template = db.execute(
        select(MasterTemplate).where(
            MasterTemplate.deleted_at.is_(None),
            MasterTemplate.is_default.is_(True),
        )
        .order_by(MasterTemplate.updated_at.desc(), MasterTemplate.id.desc())
    ).scalars().first()
    if template:
        return template

    return db.execute(
        select(MasterTemplate)
        .where(MasterTemplate.deleted_at.is_(None))
        .order_by(MasterTemplate.created_at.desc(), MasterTemplate.id.desc())
    ).scalars().first()

async def _clone_default_template_for_calculation(
    db: Session,
    calc_type: CalculationType,
) -> dict:
    source_template = get_default_or_latest_master_template(db)
    if not source_template or source_template.deleted_at is not None:
        raise HTTPException(status_code=400, detail="No master template available to clone")

    if not source_template.onedrive_item_id:
        raise HTTPException(status_code=400, detail="Default master template has no OneDrive file")

    one_drive_cfg = OneDriveConfig()
    if not one_drive_cfg.is_configured():
        raise HTTPException(status_code=503, detail="OneDrive is not configured")

    source_filename = source_template.onedrive_filename or f"template-{source_template.id}.xlsx"
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

    # Trabajamos directamente sobre la referencia del último input para mutarlo
    latest_input = payload_data["inputs"][-1]

    date = str(latest_input.get("fecha", "")).strip()

    year = ""
    match = re.search(r'\d{4}', date)
    if match:
        year = match.group(0)

    country = latest_input.get("pais")
    industry = latest_input.get("industria")
    anio_bono = latest_input.get("anio_bono")

    # Helper interno para buscar en la BD
    def _fetch_complement_data(name: str) -> list:
        comp = db.execute(
            select(TemplateComplement).where(
                TemplateComplement.nombre == name,
                TemplateComplement.deleted_at.is_(None)
            ).order_by(TemplateComplement.created_at.desc())
        ).scalars().first()
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
                latest_input["rf"] = {
                    "fecha": rf_match.get("fecha"),
                    "year": valor_rf
                }
            else:
                latest_input["rf"] = {}
        else:
            latest_input["rf"] = {}

        # EMBI: Extraemos solo la fecha y el país seleccionado
        embi_data = _fetch_complement_data("embi")
        embi_match = next((item for item in embi_data if item.get("fecha") == date), None)
        if embi_match and country:
            filtered_embi = {"fecha": embi_match.get("fecha")}
            country_key = next((k for k in embi_match.keys() if k.lower() == country.lower()), None)
            if country_key:
                filtered_embi["country"] = embi_match.get(country_key)
            latest_input["embi"] = filtered_embi
        else:
            latest_input["embi"] = {}

    if year:
        riesgo_data = _fetch_complement_data("riesgo")
        riesgo_matches = [item for item in riesgo_data if str(item.get("fecha")) == year]

        prima_data = _fetch_complement_data("prima")
        prima_match = next((item for item in prima_data if str(item.get("fecha")) == year), None)
        latest_input["prima"] = prima_match if prima_match else {}

        tax_data = _fetch_complement_data("tax")
        tax_match = next((item for item in tax_data if str(item.get("fecha")) == year), None)
        latest_input["tax"] = tax_match if tax_match else {}

        if industry:
            damo_data = _fetch_complement_data("damodaran")
            damo_match = next((item for item in damo_data if str(item.get("fecha")) == year and item.get("industria") == industry), None)
            if damo_match:
                # Retenemos solo las llaves activas en el mapa
                allowed_keys = KAPITAL_DAMODARAN_CELL_MAP.keys()
                latest_input["damodaran"] = {k: v for k, v in damo_match.items() if k in allowed_keys}
            else:
                latest_input["damodaran"] = {}

        if country:
            ir_data = _fetch_complement_data("ir")
            ir_payload = {"pais": country} # Inicializamos con el nombre del país

            for item in ir_data:
                if str(item.get("pais")).lower() == country.lower() and str(item.get("fecha")) == year:
                    ir_payload["year"] = item.get("valor")
                    break
            latest_input["ir"] = ir_payload

        flattened_riesgo = {}
        if riesgo_matches:
            flattened_riesgo["fecha"] = year
            for idx, r_item in enumerate(riesgo_matches, start=1):
                flattened_riesgo[f"num{idx}_basis_spread"] = r_item.get("basis_spread")
                flattened_riesgo[f"num{idx}_max_deviation"] = r_item.get("max_deviation")
                flattened_riesgo[f"num{idx}_min_deviation"] = r_item.get("min_deviation")

        latest_input["riesgo"] = flattened_riesgo

# ==================== ENDPOINTS ====================

@router.get("/calculations", response_model=List[CalculationResponse])
def list_calculations(user_id: Optional[int] = None, db: Session = Depends(get_db)):
    query = select(Calculation)
    if user_id:
        query = query.where(Calculation.user_id == user_id)
    result = db.execute(query)
    calculations = result.scalars().all()
    return [CalculationResponse.model_validate(c) for c in calculations]

@router.get("/calculations/{calculation_id}", response_model=CalculationResponse)
def get_calculation(calculation_id: int, db: Session = Depends(get_db)):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    return CalculationResponse.model_validate(calculation)

@router.get("/calculations/by-code/{code}", response_model=CalculationResponse)
def get_calculation_by_code(code: str, db: Session = Depends(get_db)):
    calculation = db.execute(
        select(Calculation).where(Calculation.code == code)
    ).scalars().first()

    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    return CalculationResponse.model_validate(calculation)

@router.post("/calculations", response_model=CalculationResponse, status_code=status.HTTP_201_CREATED)
async def create_calculation(payload: CalculationCreate, db: Session = Depends(get_db)):

    t_post = time.perf_counter()
    calc_type = _to_calc_type(payload.type)


    payload_data = dict(payload.data) if isinstance(payload.data, dict) else {}
    prewarmed_session_id = payload_data.pop("prewarmed_session_id", None)

    _inject_macro_data_into_payload(db, payload_data)

    # 1. OBTENER LA PLANTILLA MAESTRA DIRECTAMENTE (SIN CLONAR)
    source_template = get_default_or_latest_master_template(db)
    if not source_template or not source_template.onedrive_item_id:
        raise HTTPException(status_code=400, detail="Master template no configurada.")

    master_item_id = source_template.onedrive_item_id

    # 2. CALCULAR EN RAM
    if calc_type == CalculationType.KAPITAL:
        latest_input = _extract_input_payload(payload_data)
        include_sensibilizacion = latest_input.get("beta_desapalancado") is not None
        try:
            payload_data = await _enrich_payload_with_excel_outputs(
                payload_data,
                master_item_id, # Usamos el maestro como calculadora
                include_resultados=True,
                include_sensibilizacion=include_sensibilizacion,
                existing_session_id=prewarmed_session_id
            )
        except Exception as exc:
            logger.warning(f"Error procesando en RAM: {exc}")

    # GUARDAR EN BD
    t_db = time.perf_counter()
    calculation = Calculation(
        user_id=payload.user_id,
        code=payload.code,
        type=calc_type,
        #calculation_file_id=(file_meta.get("onedrive_item_id") or "")[:36] or None,
        #data=_normalize_calculation_data(payload_data, #file_meta=file_meta),
        calculation_file_id=None, 
        data=_normalize_calculation_data(payload_data),
    )

    db.add(calculation)
    db.commit()
    db.refresh(calculation)

    print(f"[TIMER] TIEMPO TOTAL DEL ENDPOINT POST: {time.perf_counter() - t_post:.2f} seg", flush=True)

    return CalculationResponse.model_validate(calculation)

@router.put("/calculations/{calculation_id}", response_model=CalculationResponse)
async def update_calculation(calculation_id: int, payload: CalculationUpdate, db: Session = Depends(get_db)):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    update_data = payload.model_dump(exclude_unset=True)


    if "data" in update_data:
        include_input_history = True
        include_resultados_history = True
        include_sensibilizacion_history = True
        base_changed = True
        only_boa_update = False

        _inject_macro_data_into_payload(db, update_data["data"])

        if calculation.type == CalculationType.KAPITAL:
            # 1. Obtenemos el ID de la plantilla maestra (ya no hay archivo clonado)
            source_template = get_default_or_latest_master_template(db)
            if not source_template or not source_template.onedrive_item_id:
                raise HTTPException(status_code=400, detail="Master template no configurada.")

            master_item_id = source_template.onedrive_item_id

            incoming_input_raw = _extract_input_payload(update_data["data"])
            incoming_input_base = _sanitize_input_for_history(incoming_input_raw)
            current_input_base = _sanitize_input_for_history(
                _extract_latest_input_from_history(calculation.data)
            )
            has_beta_for_sensitivity = incoming_input_raw.get("beta_desapalancado") is not None
            base_changed = bool(incoming_input_base) and incoming_input_base != current_input_base
            only_boa_update = has_beta_for_sensitivity and not base_changed

            include_input_history = base_changed
            include_resultados_history = base_changed
            include_sensibilizacion_history = only_boa_update

            existing_session = None
            if isinstance(calculation.data, dict):
                existing_session = calculation.data.get("active_session_id")
            try:
                t_put = time.perf_counter()
                update_data["data"] = await _enrich_payload_with_excel_outputs(
                    update_data["data"],
                    master_item_id,
                    include_resultados=base_changed,
                    include_sensibilizacion=only_boa_update,
                    existing_session_id=existing_session
                )
                print(f"[TIMER] TIEMPO TOTAL DEL ENDPOINT PUT: {time.perf_counter() - t_put:.2f} seg", flush=True)
            except (HTTPException, ValueError, TypeError, RuntimeError, httpx.TimeoutException, httpx.HTTPError) as exc:
                logger.warning("Could not enrich kapital update payload from Excel: %s", exc)

        update_data["data"] = _normalize_calculation_data(
            payload_data=update_data["data"],
            existing_data=calculation.data,
            include_input_history=include_input_history,
            include_resultados_history=include_resultados_history,
            include_sensibilizacion_history=include_sensibilizacion_history,
        )

        if isinstance(update_data["data"], dict) and "active_session_id" not in update_data["data"]:
            update_data["data"]["active_session_id"] = existing_session

    for key, value in update_data.items():
        setattr(calculation, key, value)
    db.commit()
    db.refresh(calculation)
    return CalculationResponse.model_validate(calculation)

@router.delete("/calculations/{calculation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calculation(calculation_id: int, db: Session = Depends(get_db)):
    calculation = db.get(Calculation, calculation_id)
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    db.delete(calculation)
    db.commit()
    return None


@router.post("/calculations/prewarm", status_code=status.HTTP_200_OK)
async def prewarm_excel_session(db: Session = Depends(get_db)):
    """
    Abre una sesión volátil en RAM con la plantilla maestra de Excel.
    Devuelve el session_id para que el frontend lo use al hacer el cálculo real.
    """
    source_template = get_default_or_latest_master_template(db)
    if not source_template or not source_template.onedrive_item_id:
        raise HTTPException(status_code=400, detail="Master template no configurada.")

    service = get_onedrive_service()
    try:
        session_id = await service._create_workbook_session(
            source_template.onedrive_item_id, 
            persist_changes=True
        )
        return {"session_id": session_id}
    except Exception as e:
        logger.error(f"Error en pre-warm: {e}")
        raise HTTPException(status_code=500, detail="No se pudo pre-calentar la sesión de Excel")
