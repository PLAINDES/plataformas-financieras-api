# app/api/main/calculations_router.py
import os
import re
import json
import time
from datetime import datetime as _dt
from uuid import uuid4
from typing import Any
import httpx
import asyncio
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from urllib.parse import quote
from app.db.database import get_db
from app.models.main import CalculationType, TemplateComplement
from app.models.templates import MasterTemplate
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

# ==================== HELPER FUNCTIONS ====================

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
            # 1.000,50 -> 1000.50
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # Ej: 1,000.50 -> 1000.50
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Si solo hay coma
        # 100,50 -> 100.50
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
        n = _extract_number(value)
        final_val = n if n is not None else value
        return final_val

    n = _extract_number(value)
    if n is None:
        print(f"[EXCEL WRITE] Percentage Field '{field}': Could not extract number from '{value}'")
        return value

    # ASIGNAMOS UN VALOR POR DEFECTO PARA EVITAR ERRORES DE LOCAL VARIABLE
    final_val = n

    if field == "country":
        final_val = n / 10000 if abs(n) > 1 else n / 100
    elif field in ("devaluacion", "costo_deuda"):
        final_val = n / 100
    else:
        # Para todos los demás porcentajes (tasa_impositiva, porcentaje_deuda, etc)
        final_val = n / 100 if abs(n) > 1 else n

    return final_val

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
    existing_session_id: str | None = None,
    retry_count: int = 0,
) -> object:

    t_start = time.perf_counter()

    if not isinstance(payload_data, dict) or not item_id:
        return payload_data

    enriched = dict(payload_data)
    latest_input = _extract_input_payload(enriched)
    service = get_onedrive_service()

    session_id = existing_session_id

    # 1. Validación de sesión existente
    if session_id:
        print(f"Intentando reusar sesión: {session_id}", flush=True)
        try:
            t_ping = time.perf_counter()
            # Hace un GET para verificar si la sesión sigue viva.
            await service.force_calculate_excel(item_id, session_id=session_id)
            print(f"[PING] Sesión validada en {time.perf_counter() - t_ping:.2f} seg", flush=True)
        except (httpx.HTTPError, httpx.TimeoutException):
            print("Sesión expirada detectada en el Ping rápido. Descartando...", flush=True)
            session_id = None
    # Si no pasaron sesión, crea una nueva
    if not session_id:
        t0 = time.perf_counter()
        session_id = await service._create_workbook_session(item_id, persist_changes=True)
        print(f"[RAM] Nueva sesión creada: {time.perf_counter() - t0:.2f} seg", flush=True)

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
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        if retry_count >= 2:
            print(f"Fallo crítico de red tras múltiples intentos ({e}). Abortando.", flush=True)
            raise e

        print(f"Microcorte de red o inestabilidad en Graph detectado ({e}). Reintentando recuperación ({retry_count + 1}/2)...", flush=True)

        # Si falló por la red/Microsoft, forzamos una nueva creación de sesión
        return await _enrich_payload_with_excel_outputs(
            payload_data, item_id,
            include_resultados=include_resultados,
            include_sensibilizacion=include_sensibilizacion,
            existing_session_id=None,
            retry_count=retry_count + 1
        )

    print(f"TIEMPO TOTAL ENRICH: {time.perf_counter() - t_start:.2f} seg", flush=True)

    enriched["resultados"] = [resultados_entry] if include_resultados else []
    enriched["sensibilizacion"] = [sensibilidad_entry] if include_sensibilizacion else []

    # GUARDAMOS LA SESIÓN ACTIVA EN EL PAYLOAD
    enriched["active_session_id"] = session_id

    return enriched


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

    # 1. INPUTS: Solo 1 registro (sobrescribir siempre con el más nuevo)
    incoming_input = _extract_input_payload(payload_data)
    inputs = []
    if incoming_input:
        inputs = _stamp_entries([{**incoming_input, "created_at": _now_iso()}])
    else:
        # Si no mandan nada (raro), rescatamos el último que existía
        old_inputs = _stamp_entries(existing.get("inputs") or [])
        if old_inputs:
            inputs = [old_inputs[0]]

    # 2. RESULTADOS: Solo 1 registro (sobrescribir)
    resultados = []
    if isinstance(payload_data, dict) and include_resultados_history:
        incoming_results = payload_data.get("resultados")
        if isinstance(incoming_results, list) and incoming_results:
            # Tomamos estrictamente el nuevo generado por Excel
            resultados = _stamp_entries([incoming_results[0]])

    if not resultados:
        # Si no extrajimos resultados nuevos (ej. update de solo BOA), mantenemos el que ya existía
        old_resultados = _stamp_entries(existing.get("resultados") or [])
        if old_resultados:
            resultados = [old_resultados[0]]

    # 3. SENSIBILIZACIÓN: Múltiples registros (acumular)
    sensibilizacion = _stamp_entries(existing.get("sensibilizacion") or [])
    if isinstance(payload_data, dict) and include_sensibilizacion_history:
        incoming_sens = payload_data.get("sensibilizacion")
        if isinstance(incoming_sens, list) and incoming_sens:
            # Agregamos el nuevo BOA al historial existente
            sensibilizacion = _merge_unique_entries(sensibilizacion, incoming_sens)

    normalized = {
        "inputs": inputs,
        "resultados": resultados,
        "sensibilizacion": sensibilizacion,
    }

    # Meta de archivos y Sesión activa
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
