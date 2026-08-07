# app/api/main/calculations_router.py
import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
import numpy as np

from app.core.constants import (
    KAPITAL_CUSTOM_INPUT_CELL_MAP,
    KAPITAL_DAMODARAN_CELL_MAP,
    KAPITAL_EMBI_CELL_MAP,
    KAPITAL_INPUT_CELL_MAP,
    KAPITAL_INPUT_SHEET,
    KAPITAL_INPUT_WACC,
    KAPITAL_PRIMA_CELL_MAP,
    KAPITAL_RESULTS_BOA_CELL,
    KAPITAL_RESULTS_BOA_SECTOR_CELL,
    KAPITAL_RESULTS_BOA_SUBSECTOR_CELL,
    KAPITAL_RESULTS_CELL_MAP,
    KAPITAL_RESULTS_SHEET,
    KAPITAL_RF_CELL_MAP,
    KAPITAL_RIESGO_CELL_MAP,
    KAPITAL_SENSITIVITY_CELL_MAP,
    KAPITAL_SENSITIVITY_INPUT_CELL_MAP,
    KAPITAL_TAX_CELL_MAP,
    VALORA_INPUT_CELL_MAP,
    VALORA_INTEGRATED_INPUT_CELL_MAP,
    VALORA_PROJECTION_INPUT_CELL_MAP,
    VALORA_RESULTS_CELL_MAP,
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

logger = logging.getLogger(__name__)


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


def _append_input_write_requests(
    write_requests: list[dict[str, Any]],
    field_data: dict[str, Any] | None,
    cell_map: dict[str, str],
    *,
    user_email: str,
    item_id: str,
    sheet_name: str,
    headers: dict[str, str],
    req_id: int,
    skip_empty: bool = False,
) -> int:
    if not isinstance(field_data, dict):
        return req_id

    for field, target_cell in cell_map.items():
        if not target_cell or field not in field_data:
            continue

        value = field_data[field]
        if skip_empty and value in (None, ""):
            continue

        write_requests.append(
            {
                "id": str(req_id),
                "method": "PATCH",
                "url": _build_excel_range_url(
                    user_email, item_id, sheet_name, target_cell
                ),
                "body": {"values": [[_to_excel_input_value(field, value)]]},
                "headers": headers,
            }
        )
        req_id += 1

    return req_id


async def _write_inputs_to_excel(
    item_id: str, input_payload: dict, session_id: str | None = None
) -> None:
    service = get_onedrive_service()
    email = service.config.user_email

    write_requests = []
    req_id = 1

    def add_write_req(field_data, cell_map, fallback_sheet=KAPITAL_INPUT_SHEET):
        nonlocal req_id
        headers = {"Content-Type": "application/json"}
        if session_id:
            headers["workbook-session-id"] = session_id
        req_id = _append_input_write_requests(
            write_requests,
            field_data,
            cell_map,
            user_email=email,
            item_id=item_id,
            sheet_name=fallback_sheet,
            headers=headers,
            req_id=req_id,
        )

    add_write_req(input_payload, KAPITAL_INPUT_CELL_MAP)
    add_write_req(input_payload, KAPITAL_SENSITIVITY_INPUT_CELL_MAP)
    
    # Si viene beta_subsector, lo duplicamos para F40
    beta_subsector = input_payload.get("beta_subsector") or input_payload.get("beta_subsector_custom")
    if beta_subsector is not None:
        input_payload["beta_subsector"] = beta_subsector
        input_payload["beta_subsector_alt"] = beta_subsector

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
    item_id: str, session_id: str | None = None, include_sensibilidad: bool = True
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

    # 2. Peticiones de Sensibilización (Opcional)
    if include_sensibilidad:
        for market, block in KAPITAL_SENSITIVITY_CELL_MAP.items():
            add_read_req("sensibilidad", KAPITAL_RESULTS_SHEET, block, market)

    # 3. Peticiones de los BOAs (Resultados y Sensibilidad)
    add_read_req("boa_res", KAPITAL_RESULTS_SHEET, {
        "boa": KAPITAL_RESULTS_BOA_CELL,
        "boa_sector": KAPITAL_RESULTS_BOA_SECTOR_CELL,
        "boa_subsector": KAPITAL_RESULTS_BOA_SUBSECTOR_CELL
    })

    if include_sensibilidad:
        add_read_req(
            "boa_sens",
            KAPITAL_RESULTS_SHEET,
            {
                "boa": KAPITAL_RESULTS_BOA_CELL,
                "boa_sector": KAPITAL_RESULTS_BOA_SECTOR_CELL,
                "boa_subsector": KAPITAL_RESULTS_BOA_SUBSECTOR_CELL
            },
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
                resultados_entry[field] = _extract_number(val)
            elif cat == "boa_sens":
                sensibilidad_entry[field] = _extract_number(val)

    return resultados_entry, sensibilidad_entry


async def _enrich_payload_with_excel_outputs(
    payload_data: object,
    item_id: str | None,
    *,
    include_resultados: bool,
    include_sensibilizacion: bool,
    existing_session_id: str | None = None,
    sensitivity_input: dict | None = None,
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

    async def _execute_excel_logic(sid: str, current_input: dict, read_sens: bool = False):
        if current_input:
            t1 = time.perf_counter()
            await _write_inputs_to_excel(
                item_id=item_id, input_payload=current_input, session_id=sid
            )
            print(f"[BATCH] Escritura: {time.perf_counter() - t1:.2f} seg", flush=True)

        t2 = time.perf_counter()
        await service.force_calculate_excel(item_id, session_id=sid)
        print(
            f"[TIMER] Recálculo forzado: {time.perf_counter() - t2:.2f} seg", flush=True
        )

        await asyncio.sleep(0.5)

        t3 = time.perf_counter()
        res, sens = await _build_excel_output_entries(item_id, session_id=sid, include_sensibilidad=read_sens)
        print(f"[BATCH] Lectura: {time.perf_counter() - t3:.2f} seg", flush=True)
        return res, sens

    try:
        # 1. CÁLCULO PRINCIPAL
        resultados_entry, sensibilidad_entry = await _execute_excel_logic(
            session_id, latest_input, read_sens=include_sensibilizacion and not sensitivity_input
        )

        # 2. CÁLCULO DE SENSIBILIZACIÓN (Si se proporciona un input específico)
        if include_sensibilizacion and sensitivity_input:
            print("Ejecutando cálculo de sensibilización como copia del principal...", flush=True)
            sens_res, _ = await _execute_excel_logic(session_id, sensitivity_input, read_sens=False)
            # El resultado del cálculo normal ahora es nuestra sensibilidad_entry
            sensibilidad_entry = sens_res
            # Inyectar los inputs usados para esta sensibilización específica
            sensibilidad_entry["inputs"] = sensitivity_input
            
            # Inyectar el BOA y subsector desde el input de sensibilidad
            if sensitivity_input.get("beta_desapalancado") is not None:
                sensibilidad_entry["boa"] = _extract_number(sensitivity_input["beta_desapalancado"])

            # Si el cálculo del excel no trajo boa_sector/subsector, intentamos mantener coherencia
            if not sensibilidad_entry.get("boa_sector") and sensitivity_input.get("beta_desapalancado"):
                sensibilidad_entry["boa_sector"] = _extract_number(sensitivity_input["beta_desapalancado"])

            # BOA del subsector de sensibilidad
            beta_subsector_sens = sensitivity_input.get("beta_subsector") or sensitivity_input.get("beta_subsector_custom")
            if beta_subsector_sens is not None:
                sensibilidad_entry["boa_subsector"] = _extract_number(beta_subsector_sens)

            if sensitivity_input.get("subsector") is not None:
                sensibilidad_entry["subsector"] = sensitivity_input["subsector"]
            if sensitivity_input.get("industria") is not None:
                sensibilidad_entry["industria"] = sensitivity_input["industria"]

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
            sensitivity_input=sensitivity_input,
            retry_count=retry_count + 1,
        )

    print(f"TIEMPO TOTAL ENRICH: {time.perf_counter() - t_start:.2f} seg", flush=True)

    # Inyección explícita del BOA desde el input del usuario para asegurar su persistencia
    if include_resultados:
        # Inyectar también los inputs en el bloque de resultados principal
        resultados_entry["inputs"] = latest_input
        
        # Mapear industria y subsector
        resultados_entry["industria"] = latest_input.get("industria")
        resultados_entry["subsector"] = latest_input.get("subsector")

        # EL BOA principal (Sector)
        resultados_entry["boa"] = resultados_entry.get("boa_sector") or resultados_entry.get("boa")

        # EL BOA del subsector (para visualización)
        beta_subsector_principal = latest_input.get("beta_subsector") or latest_input.get("beta_subsector_custom")
        if beta_subsector_principal is not None:
            resultados_entry["boa_subsector"] = _extract_number(beta_subsector_principal)

    # Si NO usamos un sensitivity_input externo, usamos la lógica anterior para compatibilidad
    if include_sensibilizacion and not sensitivity_input:
        if latest_input.get("beta_desapalancado") is not None:
            sensibilidad_entry["boa"] = _extract_number(latest_input["beta_desapalancado"])
            if isinstance(latest_input.get("subsector_sensibilizacion"), str):
                sensibilidad_entry["subsector"] = latest_input.get("subsector_sensibilizacion", "").strip()
        beta_subsector_legacy = latest_input.get("beta_subsector") or latest_input.get("beta_subsector_custom")
        if beta_subsector_legacy is not None:
            sensibilidad_entry["boa_subsector"] = _extract_number(beta_subsector_legacy)

    enriched["resultados"] = [resultados_entry] if include_resultados else []
    enriched["sensibilizacion"] = (
        [sensibilidad_entry] if include_sensibilizacion else []
    )

    # GUARDAMOS LA SESIÓN ACTIVA EN EL PAYLOAD
    enriched["active_session_id"] = session_id

    return enriched


async def _write_valora_inputs_to_excel(
    item_id: str, input_payload: dict, session_id: str | None = None
) -> None:
    service = get_onedrive_service()
    email = service.config.user_email

    balance_table = input_payload.get("balance_table") or {}
    results_table = input_payload.get("results_table") or {}

    bg_rows = balance_table.get("rows", [])
    er_rows = results_table.get("rows", [])
    years = balance_table.get("years", []) or results_table.get("years", [])

    normalized_years = []
    for y in years:
        y_str = str(y).strip()
        if y_str.isdigit():
            normalized_years.append(int(y_str))
        else:
            normalized_years.append(y_str)

    # Reordenar de menor a mayor si vienen en orden descendente
    if len(normalized_years) >= 2:
        y0 = normalized_years[0]
        y1 = normalized_years[-1]
        if isinstance(y0, int) and isinstance(y1, int) and y0 > y1:
            normalized_years = list(reversed(normalized_years))
            bg_rows = [
                {**r, "values": list(reversed(r.get("values", [])))}
                if isinstance(r, dict)
                else r
                for r in bg_rows
            ]
            er_rows = [
                {**r, "values": list(reversed(r.get("values", [])))}
                if isinstance(r, dict)
                else r
                for r in er_rows
            ]

    N = len(normalized_years)
    if N == 0:
        return

    N = min(N, 8)

    # 1. Matriz de años para Fila 3: C3:L3 (1 x 10)
    # La maestra usa E:L para ocho periodos históricos. Los vacíos se escriben
    # explícitamente para no mezclar datos residuales de cálculos anteriores.
    bg_matrix = [["" for _ in range(8)] for _ in range(32)]
    for r in range(min(32, len(bg_rows))):
        row_dict = bg_rows[r] if isinstance(bg_rows[r], dict) else {}
        row_vals = list(row_dict.get("values", [])[:N])
        if row_vals:
            row_vals = [row_vals[0]] * (8 - len(row_vals)) + row_vals
        for col_offset, val in enumerate(row_vals[-8:]):
            if val is not None and val != "":
                try:
                    bg_matrix[r][col_offset] = float(val)
                except (ValueError, TypeError):
                    bg_matrix[r][col_offset] = val

    # 3. Estado de Resultados: C38:L51 (14 filas x 10 columnas)
    er_matrix = [["" for _ in range(8)] for _ in range(14)]
    for r in range(min(14, len(er_rows))):
        row_dict = er_rows[r] if isinstance(er_rows[r], dict) else {}
        row_vals = list(row_dict.get("values", [])[:N])
        if row_vals:
            row_vals = [row_vals[0]] * (8 - len(row_vals)) + row_vals
        for col_offset, val in enumerate(row_vals[-8:]):
            if val is not None and val != "":
                try:
                    er_matrix[r][col_offset] = float(val)
                except (ValueError, TypeError):
                    er_matrix[r][col_offset] = val

    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["workbook-session-id"] = session_id

    sheet_name = "Proyección"

    write_requests = [
        {
            "id": "1",
            "method": "PATCH",
            "url": _build_excel_range_url(email, item_id, sheet_name, "C3:L3"),
            "body": {
                "formulas": [[
                    '=IF(C2="","",1)',
                    '=IF(D2="","",MAX($C3:C3)+1)',
                    '=IF(E2="","",MAX($C3:D3)+1)',
                    '=IF(F2="","",MAX($C3:E3)+1)',
                    '=IF(G2="","",MAX($C3:F3)+1)',
                    '=IF(H2="","",MAX($C3:G3)+1)',
                    '=IF(I2="","",MAX($C3:H3)+1)',
                    '=IF(J2="","",MAX($C3:I3)+1)',
                    '=IF(K2="","",MAX($C3:J3)+1)',
                    '=IF(L2="","",MAX($C3:K3)+1)',
                ]],
            },
            "headers": headers,
        },
        {
            "id": "2",
            "method": "PATCH",
            "url": _build_excel_range_url(email, item_id, sheet_name, "E4:L35"),
            "body": {"values": bg_matrix},
            "headers": headers,
        },
        {
            "id": "3",
            "method": "PATCH",
            "url": _build_excel_range_url(email, item_id, sheet_name, "E38:L51"),
            "body": {"values": er_matrix},
            "headers": headers,
        },
    ]

    try:
        await service.execute_batch(write_requests)
    except Exception:
        sheet_name_fallback = "Proyeccion"
        write_requests_fallback = [
            {
                "id": req["id"],
                "method": req["method"],
                "url": _build_excel_range_url(
                    email,
                    item_id,
                    sheet_name_fallback,
                    req["url"].split("/range(address='")[1].split("')")[0],
                ),
                "body": req["body"],
                "headers": req["headers"],
            }
            for req in write_requests
        ]
        await service.execute_batch(write_requests_fallback)

    mapped_write_requests: list[dict[str, Any]] = []
    req_id = 1

    def add_valora_write_requests(
        field_data: dict[str, Any] | None,
        cell_map: dict[str, str],
        sheet: str,
    ) -> None:
        nonlocal req_id
        req_id = _append_input_write_requests(
            mapped_write_requests,
            field_data,
            cell_map,
            user_email=email,
            item_id=item_id,
            sheet_name=sheet,
            headers=headers,
            req_id=req_id,
            skip_empty=True,
        )

    add_valora_write_requests(input_payload, VALORA_INPUT_CELL_MAP, "Plantilla Usuario")
    add_valora_write_requests(input_payload, KAPITAL_INPUT_WACC, KAPITAL_RESULTS_SHEET)
    add_valora_write_requests(
        input_payload.get("damodaran"),
        KAPITAL_DAMODARAN_CELL_MAP,
        KAPITAL_RESULTS_SHEET,
    )
    add_valora_write_requests(
        input_payload.get("prima"), KAPITAL_PRIMA_CELL_MAP, KAPITAL_RESULTS_SHEET
    )
    add_valora_write_requests(
        input_payload.get("embi"), KAPITAL_EMBI_CELL_MAP, KAPITAL_RESULTS_SHEET
    )
    add_valora_write_requests(
        input_payload.get("rf"), KAPITAL_RF_CELL_MAP, KAPITAL_RESULTS_SHEET
    )
    add_valora_write_requests(
        input_payload.get("riesgo"), KAPITAL_RIESGO_CELL_MAP, KAPITAL_RESULTS_SHEET
    )
    add_valora_write_requests(
        input_payload.get("tax"), KAPITAL_TAX_CELL_MAP, KAPITAL_RESULTS_SHEET
    )
    add_valora_write_requests(
        input_payload, VALORA_PROJECTION_INPUT_CELL_MAP, "Proyección"
    )
    add_valora_write_requests(
        input_payload, VALORA_INTEGRATED_INPUT_CELL_MAP, "Integrado"
    )

    chunks = [
        mapped_write_requests[i : i + 20]
        for i in range(0, len(mapped_write_requests), 20)
    ]
    for chunk in chunks:
        await service.execute_batch(chunk)


async def _build_valora_output_entry(
    item_id: str, session_id: str | None = None
) -> dict[str, Any]:
    service = get_onedrive_service()
    email = service.config.user_email
    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["workbook-session-id"] = session_id

    result = {
        "created_at": _now_iso(),
        "balance": {},
        "conceptos": {},
        "integrado": {},
    }
    requests = []
    mapping = {}

    for key, target in VALORA_RESULTS_CELL_MAP.items():
        if key == "wacc":
            sheet_name, cell = target
            mapping[str(len(requests) + 1)] = ("wacc", None)
            requests.append((sheet_name, cell))
            continue
        for field, (sheet_name, cell) in target.items():
            mapping[str(len(requests) + 1)] = (key, field)
            requests.append((sheet_name, cell))

    responses = await service.execute_batch(
        [
            {
                "id": str(index),
                "method": "GET",
                "url": _build_excel_range_url(email, item_id, sheet_name, cell),
                "headers": headers,
            }
            for index, (sheet_name, cell) in enumerate(requests, start=1)
        ]
    )

    for response in responses:
        target = mapping.get(str(response.get("id")))
        body = response.get("body") or {}
        if not target or response.get("status") != 200:
            continue
        value = _first_matrix_value(body.get("text"))
        if value is None:
            value = _first_matrix_value(body.get("values"))
        category, field = target
        if field is None:
            result[category] = value
        else:
            result.setdefault(category, {})[field] = value

    return result


def _is_excel_error(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return value.strip().startswith("#")


# =========================================================
# VALORA FORECAST FALLBACK (ETS)
# =========================================================

# Celdas FORECAST.ETS de la maestra. Inmutable: nunca se reescriben sobre la
# sesión persistente. Solo cuando la maestra no las resuelve, el fallback
# calcula su valor en Python (statsmodels ETS) y lo propaga mediante una sesión
# temporal (persist chazar are false) SIN persistir nada.
_VALORA_FORECAST_CELLS = [
    {
        "key": "ingresos",
        "sheet": "Proyección",
        "cell": "M89",
        "hist_range": "E89:L89",
        "section": "conceptos",
    },
    {
        "key": "gastos_admin",
        "sheet": "Proyección",
        "cell": "M137",
        "hist_range": "E137:L137",
        "section": "conceptos",
    },
    {
        "key": "depreciacion",
        "sheet": "Proyección",
        "cell": "M170",
        "hist_range": "E170:L170",
        "section": "conceptos",
    },
    {
        "key": "capex_1",
        "sheet": "Proyección",
        "cell": "M105",
        "hist_range": "E105:L105",
        "section": "conceptos",
    },
    {
        "key": "capex_2",
        "sheet": "Proyección",
        "cell": "M120",
        "hist_range": "E120:L120",
        "section": "conceptos",
    },
    {
        "key": "capex_3",
        "sheet": "Proyección",
        "cell": "M121",
        "hist_range": "E121:L121",
        "section": "conceptos",
    },
    {
        "key": "fdc",
        "sheet": "Integrado",
        "cell": "M7",
        "hist_range": "E8:L8",
        "section": "integrado",
    },
]

_SECTION_CELLS = {
    "conceptos": {
        "activo": ("Conceptos", "Q24"),
        "pasivo": ("Conceptos", "Q26"),
        "empresa": ("Conceptos", "Q25"),
        "patrimonio": ("Conceptos", "Q27"),
        "precio_accion": ("Conceptos", "Q28"),
        "tasa_forecast": ("Conceptos", "T30"),
        "tasa_perpetua": ("Conceptos", "T31"),
    },
    "integrado": {
        "activo": ("Integrado", "P34"),
        "pasivo": ("Integrado", "P36"),
        "empresa": ("Integrado", "P35"),
        "patrimonio": ("Integrado", "P37"),
        "precio_accion": ("Integrado", "P38"),
        "tasa_forecast": ("Integrado", "S40"),
        "tasa_perpetua": ("Integrado", "S41"),
    },
}


def _ets_forecast_next(values: list[Any]) -> tuple[float | None, str | None]:
    """Pronostica un punto siguiente con ETS (AAA con fallback a AA).

    No se fija seasonal_periods: se intenta AAA y, si el ajuste fracasa o la
    serie no es suficientemente larga para estacionalidad, se cae a AA.
    """
    nums: list[float] = []
    for v in values:
        n = _extract_number(v)
        if n is not None:
            nums.append(n)
    if len(nums) < 3:
        return None, None

    series = np.asarray(nums, dtype=float)

    try:
        from statsmodels.tsa.exponential_smoothing.ets import ETSModel
    except Exception as exc:  # pragma: no cover - dep opcional
        print(f"[VALORA][ETS] statsmodels no disponible: {exc}", flush=True)
        return None, None

    # 1. Intento AAA (aditivo-aditivo-additivo) con estacionalidad autodetectada.
    # El ajuste ETS es determinista por construcción (L-BFGS sobre start_params
    # derivados de los datos, sin uso del RNG global: np.random solo se usa en
    # simulate(), no en fit()). No se toca el estado global de numpy.
    try:
        seasonal_len = max(2, len(series) // 2)
        model = ETSModel(
            series,
            error="add",
            trend="add",
            seasonal="add",
            seasonal_periods=seasonal_len,
            damped_trend=False,
        )
        fit = model.fit(disp=False)
        fc = float(np.asarray(fit.forecast(1))[0])
        if np.isfinite(fc):
            return fc, "ets_aaa"
    except Exception:
        pass

    # 2. Fallback AA (aditivo-aditivo sin estacionalidad).
    try:
        model = ETSModel(
            series,
            error="add",
            trend="add",
            seasonal=None,
            damped_trend=False,
        )
        fit = model.fit(disp=False)
        fc = float(np.asarray(fit.forecast(1))[0])
        if np.isfinite(fc):
            return fc, "ets_aa"
    except Exception as exc:
        print(f"[VALORA][ETS] fallback AA fallido: {exc}", flush=True)

    return None, None


async def _read_row_series(
    service,
    item_id: str,
    sheet: str,
    hist_range: str,
    session_id: str | None,
) -> list[float]:
    """Lee una fila histórica y devuelve solo las columnas con datos reales."""
    body = await service.read_excel_cell(
        item_id=item_id,
        sheet_name=sheet,
        cell_address=hist_range,
        session_id=session_id,
    )
    values = body.get("values") or []
    row = values[0] if values and isinstance(values[0], list) else (values or [])
    series: list[float] = []
    for v in row:
        if v is None:
            continue
        if isinstance(v, str) and (v.strip() == "" or v.strip().startswith("#")):
            continue
        n = _extract_number(v)
        if n is not None:
            series.append(n)
    # Sólo la parte con datos reales (no padded hacia la izquierda).
    return series


async def _apply_valora_forecast_fallback(
    payload_data: dict[str, Any],
    item_id: str,
    session_id: str | None,
    resultados: dict[str, Any],
    latest_input: dict,
) -> dict[str, str]:
    """Detecta celdas FORECAST.ETS en error y, si hay, recalcula en Python.

    Propaga vía una sesión TEMPORAL (persist_changes=False) y mezcla en
    'resultados' solo las secciones afectadas. Devuelve el mapa forecast_method.
    """
    service = get_onedrive_service()
    email = service.config.user_email
    forecast_method = {"conceptos": "excel", "integrado": "excel"}

    # 1. Leer los forecast en la sesión real abierta.
    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["workbook-session-id"] = session_id

    check_requests = [
        {
            "id": str(i),
            "method": "GET",
            "url": _build_excel_range_url(email, item_id, fc["sheet"], fc["cell"]),
            "headers": headers,
        }
        for i, fc in enumerate(_VALORA_FORECAST_CELLS)
    ]
    check_responses = await service.execute_batch(check_requests)
    check_by_id = {str(resp.get("id")): resp for resp in check_responses}

    failed: list[dict] = []
    for fc, req in zip(_VALORA_FORECAST_CELLS, check_requests):
        resp = check_by_id.get(str(req["id"])) or {}
        body = resp.get("body") or {}
        text = _first_matrix_value(body.get("text"))
        if _is_excel_error(text if text is not None else ""):
            failed.append(fc)

    if not failed:
        return forecast_method

    affected_sections = {fc["section"] for fc in failed}
    computed: dict[str, dict] = {}
    for fc in failed:
        series = await _read_row_series(
            service, item_id, fc["sheet"], fc["hist_range"], session_id
        )
        value, model = _ets_forecast_next(series)
        computed[fc["key"]] = {"cell": fc["cell"], "sheet": fc["sheet"],
                               "value": value, "model": model}
        print(
            f"[VALORA][FALLBACK] item={item_id} celda={fc['sheet']}!{fc['cell']} "
            f"modelo={model} valor={value}",
            flush=True,
        )

    # 2) Sesión temporal (no persiso nada) para todas las fallidas juntas.
    temp_session = await service._create_workbook_session(
        item_id, persist_changes=False
    )
    try:
        # Reescribe históricos base para que la sesion temporal tenga contexto.
        if latest_input:
            await _write_valora_inputs_to_excel(
                item_id=item_id, input_payload=latest_input, session_id=temp_session
            )

        temp_headers = {"Content-Type": "application/json", "workbook-session-id": temp_session}
        override_requests = []
        for i, fc in enumerate(failed):
            value = (computed.get(fc["key"]) or {}).get("value")
            if value is None:
                continue
            override_requests.append(
                {
                    "id": str(i),
                    "method": "PATCH",
                    "url": _build_excel_range_url(
                        email, item_id, fc["sheet"], fc["cell"]
                    ),
                    "body": {"values": [[value]]},
                    "headers": temp_headers,
                }
            )
        print(
            f"[VALORA][FALLBACK-DBG] OVERRIDES a escribir en sesión temp {temp_session}: "
            f"{override_requests}",
            flush=True,
        )
        override_responses = []
        if override_requests:
            override_responses = await service.execute_batch(override_requests)
            print(
                f"[VALORA][FALLBACK-DBG] Respuestas de overrides: "
                f"{[(r.get('id'), r.get('status'), r.get('body')) for r in override_responses]}",
                flush=True,
            )

        print(
            f"[VALORA][FALLBACK-DBG] fullRebuild ANTES de leer salidas (sesión temp)",
            flush=True,
        )
        await service.force_calculate_excel(item_id, session_id=temp_session)
        print(
            f"[VALORA][FALLBACK-DBG] fullRebuild HECHO (sesión temp)",
            flush=True,
        )

        # 3) Leer solo las celdas de salida de las secciones afectadas.
        section_requests = []
        section_mapping = {}
        index = 1
        for section in ["conceptos", "integrado"]:
            if section not in affected_sections:
                continue
            for field, (sheet, cell) in _SECTION_CELLS[section].items():
                section_mapping[str(index)] = (section, field)
                section_requests.append(
                    {
                        "id": str(index),
                        "method": "GET",
                        "url": _build_excel_range_url(email, item_id, sheet, cell),
                        "headers": {"workbook-session-id": temp_session},
                    }
                )
                index += 1

        section_responses = await service.execute_batch(section_requests)

        # Leer también los 3 forecast sobre-escritos para confirmar qué valor real
        # quedó (y su tipo) en la sesión temp tras el fullRebuild.
        verify_forecast = [
            {
                "id": str(900 + i),
                "method": "GET",
                "url": _build_excel_range_url(email, item_id, fc["sheet"], fc["cell"]),
                "headers": {"workbook-session-id": temp_session},
            }
            for i, fc in enumerate([f for f in _VALORA_FORECAST_CELLS if f in failed])
        ]
        if verify_forecast:
            verify_responses = await service.execute_batch(verify_forecast)
            verify_by_id = {str(resp.get("id")): resp for resp in verify_responses}
            for req in verify_forecast:
                resp = verify_by_id.get(str(req["id"]))
                fc_cell = req["url"].split("address='")[1].split("'")[0]
                print(
                    f"[VALORA][FALLBACK-DBG] forecast tras rebuild {fc_cell} -> "
                    f"status={resp.get('status') if resp else 'MISSING'} "
                    f"body={resp.get('body') if resp else None}",
                    flush=True,
                )

        # Diagnóstico de la cadena de Conceptos: eslabones intermedios entre los
        # forecast y el NPV(M19:AA19). Body completo (para ver errorText real).
        chain_requests = []
        chain_by_label = {}
        chain_targets = [
            ("Proyección", "M92", "prop_ing"),
            ("Proyección", "M193", "fb_x_ing"),
            ("Proyección", "M195", "fb_cfe"),
            ("Proyección", "M214", "fb_term"),
            ("Conceptos", "M19:AA19", "fcf_npv_row"),
            ("Conceptos", "Q22", "npv_result"),
        ]
        for i, (sh, cel, label) in enumerate(chain_targets, start=2000):
            chain_requests.append(
                {
                    "id": str(i),
                    "method": "GET",
                    "url": _build_excel_range_url(email, item_id, sh, cel),
                    "headers": {"workbook-session-id": temp_session},
                }
            )
            chain_by_label[label] = str(i)
        chain_responses = await service.execute_batch(chain_requests)
        chain_by_id = {str(resp.get("id")): resp for resp in chain_responses}
        for label, rid in chain_by_label.items():
            resp = chain_by_id.get(rid)
            print(
                f"[VALORA][FALLBACK-DBG] CHAIN {label} -> "
                f"status={resp.get('status') if resp else 'MISSING'} "
                f"body={json.dumps(resp.get('body') if resp else None, default=str)}",
                flush=True,
            )

        for resp in section_responses:
            target = section_mapping.get(str(resp.get("id")))
            body = resp.get("body") or {}
            if not target:
                continue
            section, field = target
            raw_text = _first_matrix_value(body.get("text"))
            raw_value = _first_matrix_value(body.get("values"))
            print(
                f"[VALORA][FALLBACK-DBG] LECTURA {section}.{field} "
                f"status={resp.get('status')} text={raw_text!r} values={raw_value!r}",
                flush=True,
            )
            if resp.get("status") != 200:
                print(
                    f"[VALORA][FALLBACK-DBG] {section}.{field} status!=200 -> se ignora",
                    flush=True,
                )
                continue
            value = raw_text if raw_text is not None else raw_value
            # NO pisar con un valor nulo/error: si la lectura B2 no trae un valor
            # limpio, conservamos el que ya tenía 'resultados' (el bueno).
            if _is_excel_error(value if isinstance(value, str) else "") or value in (None, ""):
                print(
                    f"[VALORA][FALLBACK-DBG] {section}.{field} trajo valor inválido "
                    f"({value!r}) -> se conserva el existente: "
                    f"{resultados.get(section, {}).get(field)!r}",
                    flush=True,
                )
                continue
            resultados.setdefault(section, {})[field] = value

        print(
            f"[VALORA][FALLBACK-DBG] RESULTADOS finales tras merge: "
            f"{json.dumps(resultados, default=str)}",
            flush=True,
        )

        for sec in affected_sections:
            forecast_method[sec] = "ets_fallback"
    finally:
        await service._close_workbook_session(item_id, temp_session)

    return forecast_method


async def _enrich_payload_with_valora_excel(
    payload_data: dict[str, Any],
    item_id: str,
    existing_session_id: str | None = None,
) -> dict[str, Any]:
    service = get_onedrive_service()
    latest_input = _extract_input_payload(payload_data)

    session_id = existing_session_id
    if session_id:
        try:
            await service.force_calculate_excel(item_id, session_id=session_id)
        except Exception:
            session_id = None

    if not session_id:
        session_id = await service._create_workbook_session(
            item_id, persist_changes=True
        )

    if latest_input:
        await _write_valora_inputs_to_excel(
            item_id=item_id, input_payload=latest_input, session_id=session_id
        )

    await service.force_calculate_excel(item_id, session_id=session_id)

    payload_data["active_session_id"] = session_id
    payload_data["resultados"] = await _build_valora_output_entry(
        item_id, session_id=session_id
    )
    payload_data["resultados"]["inputs"] = latest_input

    # FALLBACK B2: capa adicional tras el flujo normal. Si alguna celda
    # FORECAST.ETS quedó en error, se recalcula en Python (ETS) vía una sesión
    # TEMPORAL sin persistir y solo se fusionan las secciones afectadas.
    try:
        forecast_method = await _apply_valora_forecast_fallback(
            payload_data,
            item_id,
            session_id,
            payload_data["resultados"],
            latest_input,
        )
        payload_data["forecast_method"] = forecast_method
    except Exception as exc:
        logger.warning(
            f"Fallback forecast de Valora no aplicable en esta pasada "
            f"(item={item_id}): {exc}"
        )
        payload_data.setdefault(
            "forecast_method", {"conceptos": "excel", "integrado": "excel"}
        )

    return payload_data

