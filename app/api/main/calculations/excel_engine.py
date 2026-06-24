# app/api/main/calculations_router.py
import asyncio
import time
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from app.core.constants import (
    KAPITAL_CUSTOM_INPUT_CELL_MAP,
    KAPITAL_DAMODARAN_CELL_MAP,
    KAPITAL_EMBI_CELL_MAP,
    KAPITAL_INPUT_CELL_MAP,
    KAPITAL_INPUT_SHEET,
    KAPITAL_INPUT_WACC,
    KAPITAL_PRIMA_CELL_MAP,
    KAPITAL_RESULTS_BOA_CELL,
    KAPITAL_RESULTS_CELL_MAP,
    KAPITAL_RESULTS_SHEET,
    KAPITAL_RF_CELL_MAP,
    KAPITAL_RIESGO_CELL_MAP,
    KAPITAL_SENSITIVITY_CELL_MAP,
    KAPITAL_SENSITIVITY_INPUT_CELL_MAP,
    KAPITAL_TAX_CELL_MAP,
)
from app.models.main import CalculationType
from app.services.onedrive.service import get_onedrive_service

from .formatters import (
    _extract_number,
    _first_matrix_value,
    _now_iso,
    _to_excel_input_value,
)
from .payload_manager import _extract_input_payload


def _build_template_copy_name(calc_type: CalculationType) -> str:
    return f"{calc_type.value}-{uuid4().hex}"


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


# --- METODO PARA RUTAS BATCH ---
def _build_excel_range_url(
    user_email: str, item_id: str, sheet_name: str, cell: str
) -> str:
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

    def add_write_req(field_data, cell_map, fallback_sheet=KAPITAL_INPUT_SHEET):
        nonlocal req_id
        # Si field_data no es un diccionario válido, salimos
        if not isinstance(field_data, dict):
            return

        for f, target_code in cell_map.items():
            # Buscamos 'f' dentro de 'field_data', NO en 'input_payload'
            if not target_code or f not in field_data:
                continue

            mapped_val = _to_excel_input_value(f, field_data[f])
            headers = {"Content-Type": "application/json"}
            if session_id:
                headers["workbook-session-id"] = session_id

            write_requests.append(
                {
                    "id": str(req_id),
                    "method": "PATCH",
                    "url": _build_excel_range_url(
                        email, item_id, fallback_sheet, target_code
                    ),
                    "body": {"values": [[mapped_val]]},
                    "headers": headers,
                }
            )
            req_id += 1

    add_write_req(input_payload, KAPITAL_INPUT_CELL_MAP)
    add_write_req(input_payload, KAPITAL_SENSITIVITY_INPUT_CELL_MAP)
    add_write_req(input_payload, KAPITAL_CUSTOM_INPUT_CELL_MAP, KAPITAL_RESULTS_SHEET)

    # tasa impositiva y devaluacion para WACC
    add_write_req(input_payload, KAPITAL_INPUT_WACC, KAPITAL_RESULTS_SHEET)

    # Guardamos los datos de damodaran, rf, ir, embi, prima y riesgo en el excel

    add_write_req(
        input_payload.get("damodaran", {}),
        KAPITAL_DAMODARAN_CELL_MAP,
        KAPITAL_RESULTS_SHEET,
    )
    add_write_req(
        input_payload.get("prima", {}), KAPITAL_PRIMA_CELL_MAP, KAPITAL_RESULTS_SHEET
    )
    add_write_req(
        input_payload.get("embi", {}), KAPITAL_EMBI_CELL_MAP, KAPITAL_RESULTS_SHEET
    )
    add_write_req(
        input_payload.get("rf", {}), KAPITAL_RF_CELL_MAP, KAPITAL_RESULTS_SHEET
    )
    add_write_req(
        input_payload.get("riesgo", {}), KAPITAL_RIESGO_CELL_MAP, KAPITAL_RESULTS_SHEET
    )
    add_write_req(
        input_payload.get("tax", {}), KAPITAL_TAX_CELL_MAP, KAPITAL_RESULTS_SHEET
    )

    # Enviar a Microsoft en lotes de 20 (Límite del API Graph)
    chunks = [write_requests[i : i + 20] for i in range(0, len(write_requests), 20)]
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
        result[field] = await _read_rendered_cell_number(
            service, item_id, sheet_name, cell, session_id=session_id
        )
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

    def add_read_req(category, fallback_sheet, block_map, market_name=None):
        nonlocal req_id
        for field, target_code in block_map.items():
            mapping[str(req_id)] = (category, market_name, field)
            read_requests.append(
                {
                    "id": str(req_id),
                    "method": "GET",
                    "url": _build_excel_range_url(
                        email, item_id, fallback_sheet, target_code
                    ),
                    "headers": {"workbook-session-id": session_id}
                    if session_id
                    else {},
                }
            )
            req_id += 1

    # 1. Peticiones de Resultados Generales
    for market, block in KAPITAL_RESULTS_CELL_MAP.items():
        add_read_req("resultados", KAPITAL_RESULTS_SHEET, block, market)

    # 2. Peticiones de Sensibilización
    for market, block in KAPITAL_SENSITIVITY_CELL_MAP.items():
        add_read_req("sensibilidad", KAPITAL_RESULTS_SHEET, block, market)

    # 3. Peticiones de los BOAs (Resultados y Sensibilidad)
    add_read_req("boa_res", KAPITAL_RESULTS_SHEET, {"boa": KAPITAL_RESULTS_BOA_CELL})
    add_read_req(
        "boa_sens",
        KAPITAL_INPUT_SHEET,
        {"boa": KAPITAL_SENSITIVITY_INPUT_CELL_MAP["beta_desapalancado"]},
    )

    # Dividir las celdas en lotes de 20 y ejecutar simultáneamente
    chunks = [read_requests[i : i + 20] for i in range(0, len(read_requests), 20)]
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
            print(
                f"[PING] Sesión validada en {time.perf_counter() - t_ping:.2f} seg",
                flush=True,
            )
        except (httpx.HTTPError, httpx.TimeoutException):
            print(
                "Sesión expirada detectada en el Ping rápido. Descartando...",
                flush=True,
            )
            session_id = None
    # Si no pasaron sesión, crea una nueva
    if not session_id:
        t0 = time.perf_counter()
        session_id = await service._create_workbook_session(
            item_id, persist_changes=False
        )
        print(
            f"[RAM] Nueva sesión creada: {time.perf_counter() - t0:.2f} seg", flush=True
        )

    async def _execute_excel_logic(sid: str):
        if latest_input:
            t1 = time.perf_counter()
            await _write_inputs_to_excel(
                item_id=item_id, input_payload=latest_input, session_id=sid
            )
            print(f"[BATCH] Escritura: {time.perf_counter() - t1:.2f} seg", flush=True)

        t2 = time.perf_counter()
        await service.force_calculate_excel(item_id, session_id=sid)
        print(
            f"[TIMER] Recálculo forzado: {time.perf_counter() - t2:.2f} seg", flush=True
        )

        await asyncio.sleep(0.5)

        t3 = time.perf_counter()
        res, sens = await _build_excel_output_entries(item_id, session_id=sid)
        print(f"[BATCH] Lectura: {time.perf_counter() - t3:.2f} seg", flush=True)
        return res, sens

    try:
        resultados_entry, sensibilidad_entry = await _execute_excel_logic(session_id)
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        if retry_count >= 2:
            print(
                f"Fallo crítico de red tras múltiples intentos ({e}). Abortando.",
                flush=True,
            )
            raise e

        print(
            f"Microcorte de red o inestabilidad en Graph detectado ({e}). Reintentando recuperación ({retry_count + 1}/2)...",
            flush=True,
        )

        # Si falló por la red/Microsoft, forzamos una nueva creación de sesión
        return await _enrich_payload_with_excel_outputs(
            payload_data,
            item_id,
            include_resultados=include_resultados,
            include_sensibilizacion=include_sensibilizacion,
            existing_session_id=None,
            retry_count=retry_count + 1,
        )

    print(f"TIEMPO TOTAL ENRICH: {time.perf_counter() - t_start:.2f} seg", flush=True)

    # Inyección explícita del BOA desde el input del usuario para asegurar su persistencia
    if include_resultados:
        if latest_input.get("beta_desapalancado_custom") is not None:
            resultados_entry["boa"] = _extract_number(latest_input["beta_desapalancado_custom"])
        elif latest_input.get("beta_desapalancado") is not None:
            resultados_entry["boa"] = _extract_number(latest_input["beta_desapalancado"])

    if include_sensibilizacion and latest_input.get("beta_desapalancado") is not None:
        sensibilidad_entry["boa"] = _extract_number(latest_input["beta_desapalancado"])
        if isinstance(latest_input.get("subsector_sensibilizacion"), str):
            sensibilidad_entry["subsector"] = latest_input.get("subsector_sensibilizacion", "").strip()

    enriched["resultados"] = [resultados_entry] if include_resultados else []
    enriched["sensibilizacion"] = (
        [sensibilidad_entry] if include_sensibilizacion else []
    )

    # GUARDAMOS LA SESIÓN ACTIVA EN EL PAYLOAD
    enriched["active_session_id"] = session_id

    return enriched
