# app/api/main/calculations_router.py
import asyncio
import logging
import time
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
import numpy as np

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

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
    for chunk in chunks:
        logger.info(f"[KAPITAL WRITE] Enviando chunk de {len(chunk)} requests")
        responses = await service.execute_batch(chunk)
        for r in responses:
            if r.get("status", 0) >= 400:
                logger.error(
                    f"[KAPITAL WRITE ERROR] id={r.get('id')} status={r.get('status')} body={r.get('body')}"
                )


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

    # Dividir las celdas en lotes de 20 y ejecutar secuencialmente
    chunks = [read_requests[i : i + 20] for i in range(0, len(read_requests), 20)]
    batch_results: list[list[dict]] = []
    for chunk in chunks:
        logger.info(f"[KAPITAL READ] Enviando chunk de {len(chunk)} requests")
        batch_results.append(await service.execute_batch(chunk))

    # Procesar el mega-paquete de respuestas
    for chunk_responses in batch_results:
        for resp in chunk_responses:
            if resp.get("status", 0) >= 400:
                logger.error(
                    f"[KAPITAL READ ERROR] id={resp.get('id')} status={resp.get('status')} body={resp.get('body')}"
                )
                continue
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
    # Si no pasaron sesión, crea una nueva con persistencia para copia de trabajo
    if not session_id:
        t0 = time.perf_counter()
        session_id = await service._create_workbook_session(
            item_id, persist_changes=True
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

    # Forzar años a enteros puros. FORECAST.ETS requiere eje temporal numérico;
    # si una celda del rango se escribe como texto, la función devuelve error.
    normalized_years = []
    for y in years:
        n = _extract_number(y)
        if n is not None:
            normalized_years.append(int(n))
        else:
            # Si no se puede parsear, lo dejamos como None para no enviar string
            normalized_years.append(None)

    N = len(normalized_years)
    if N == 0:
        return

    N = min(N, 8)

    # Siempre ordenar años de menor a mayor (2018...,2025) para que E2 sea el
    # año más antiguo y L2 el más reciente. Se invierten los valores de cada
    # fila del balance y resultado para mantener la correspondencia con el eje.
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

    # Truncamos a máximo 8 años.
    years_to_write = normalized_years[:N]

    # El rango de años se ajusta al número de años enviados.
    # Ej: 8 años -> E2:L2; 5 años -> H2:L2. Así no se pisan columnas vacías
    # ni se envía una matriz de dimensiones incorrectas a Graph API.
    def _col_letter(offset: int) -> str:
        # offset 0 -> C, 1 -> D, ..., 9 -> L
        return chr(ord("C") + offset)

    years_start_col = _col_letter(10 - N)
    years_range = f"{years_start_col}2:L2"
    years_range_er = f"{years_start_col}37:L37"
    logger.info(
        f"[VALORA WRITE] Rango de años: {years_range} para {N} años "
        f"ordenados ascendente: {years_to_write}"
    )

    def _build_year_row(years: list) -> list:
        """Genera una fila de años del tamaño exacto del rango destino."""
        return [[int(y) if y is not None and y != "" else None for y in years]]

    # 1. Matriz de Balance General: E4:L35 (32 filas x 8 columnas)
    # años ordenados ascendentemente: el primer valor va a la primera columna (E).
    bg_matrix = [[None for _ in range(8)] for _ in range(32)]
    for r in range(min(32, len(bg_rows))):
        row_dict = bg_rows[r] if isinstance(bg_rows[r], dict) else {}
        row_vals = list(row_dict.get("values", [])[:N])
        for col_offset, val in enumerate(row_vals):
            n = _extract_number(val)
            if n is not None:
                bg_matrix[r][col_offset] = n
            # Si no es numérico, dejamos None (no string) para no corromper fórmulas

    # 2. Matriz de Estado de Resultados: E38:L51 (14 filas x 8 columnas)
    er_matrix = [[None for _ in range(8)] for _ in range(14)]
    for r in range(min(14, len(er_rows))):
        row_dict = er_rows[r] if isinstance(er_rows[r], dict) else {}
        row_vals = list(row_dict.get("values", [])[:N])
        for col_offset, val in enumerate(row_vals):
            n = _extract_number(val)
            if n is not None:
                er_matrix[r][col_offset] = n
            # Si no es numérico, dejamos None

    headers = {"Content-Type": "application/json"}
    if session_id:
        headers["workbook-session-id"] = session_id

    sheet_name = "Proyección"

    write_requests = [
        {
            "id": "1",
            "method": "PATCH",
            "url": _build_excel_range_url(email, item_id, sheet_name, years_range),
            "body": {"values": _build_year_row(years_to_write)},
            "headers": headers,
        },
        {
            "id": "2",
            "method": "PATCH",
            "url": _build_excel_range_url(email, item_id, sheet_name, years_range_er),
            "body": {"values": _build_year_row(years_to_write)},
            "headers": headers,
        },
        {
            "id": "3",
            "method": "PATCH",
            "url": _build_excel_range_url(email, item_id, sheet_name, "E4:L35"),
            "body": {"values": bg_matrix},
            "headers": headers,
        },
        {
            "id": "4",
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
        write_requests_fallback = []
        for req in write_requests:
            try:
                raw_range = req["url"].split("/range(address='")[1].split("')")[0]
            except IndexError:
                raw_range = ""
            if not raw_range:
                write_requests_fallback.append(req)
                continue
            write_requests_fallback.append(
                {
                    "id": req["id"],
                    "method": req["method"],
                    "url": _build_excel_range_url(
                        email,
                        item_id,
                        sheet_name_fallback,
                        raw_range,
                    ),
                    "body": req["body"],
                    "headers": req["headers"],
                }
            )
        if write_requests_fallback:
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

async def _enrich_payload_with_valora_excel(
    payload_data: dict[str, Any],
    item_id: str,
    existing_session_id: str | None = None,
) -> dict[str, Any]:
    from time import perf_counter

    def _lap(label: str, start: float) -> float:
        elapsed = perf_counter() - start
        logger.info(f"[VALORA TIMER] {label}: {elapsed:.3f} seg")
        return perf_counter()

    service = get_onedrive_service()
    latest_input = _extract_input_payload(payload_data)

    t_total = perf_counter()
    session_id = existing_session_id
    t0 = perf_counter()

    if session_id:
        try:
            await service.force_calculate_excel(item_id, session_id=session_id)
        except Exception:
            session_id = None
        else:
            t0 = _lap("force_calculate_excel en sesión previa", t0)

    if not session_id:
        t0 = perf_counter()
        session_id = await service._create_workbook_session(
            item_id, persist_changes=True
        )
        t0 = _lap("create_workbook_session", t0)

    logger.info(f"[VALORA] Sesión {session_id} abierta para item {item_id}")

    try:
        if latest_input:
            logger.info(
                f"[VALORA] Escribiendo inputs en Excel para item {item_id}; "
                f"balance_rows={len(latest_input.get('balance_table', {}).get('rows', []))}, "
                f"results_rows={len(latest_input.get('results_table', {}).get('rows', []))}"
            )
            await _write_valora_inputs_to_excel(
                item_id=item_id, input_payload=latest_input, session_id=session_id
            )
            t0 = _lap("_write_valora_inputs_to_excel", t0)

        await asyncio.sleep(0.3)
        t0 = _lap("sleep post-escritura", t0)

        logger.info("[VALORA] Forzando recálculo fullRebuild")
        await service.force_calculate_excel(item_id, session_id=session_id)
        t0 = _lap("force_calculate_excel fullRebuild", t0)

        logger.info("[VALORA] Leyendo resultados")
        resultados = await _build_valora_output_entry(item_id, session_id=session_id)
        t0 = _lap("_build_valora_output_entry", t0)

        logger.info(f"[VALORA] Resultados leídos: {resultados}")
        payload_data["active_session_id"] = session_id
        payload_data["resultados"] = resultados
        payload_data["resultados"]["inputs"] = latest_input
    except Exception as exc:
        logger.exception(f"[VALORA] Error durante enriquecimiento Excel: {exc}")
        raise
    finally:
        try:
            await service._close_workbook_session(item_id, session_id)
            logger.info(f"[VALORA] Sesión {session_id} cerrada")
        except Exception:
            logger.warning(
                f"[VALORA] No se pudo cerrar la sesión {session_id} del workbook",
                exc_info=True,
            )

    _lap("TIEMPO TOTAL enrich_payload_with_valora_excel", t_total)
    return payload_data

