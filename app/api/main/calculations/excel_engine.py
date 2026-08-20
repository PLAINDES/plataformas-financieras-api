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
    VALORA_SENSITIVITY_INPUT_CELL_MAP,
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


def _build_valora_linest_formulas(years_start_col: str) -> list[dict[str, str]]:
    """Build the LINEST formulas using the same first historical-year column."""
    start_col = years_start_col.upper()
    special_start_col = chr(ord(start_col) + 1)

    return [
        {"sheet": "Proyección", "range": "E95:F95", "formula": f"=LINEST({start_col}89:M89,LN({start_col}87:M87))"},
        {"sheet": "Proyección", "range": "J95:K95", "formula": f"=LINEST({start_col}88:L88,LN({start_col}87:L87))"},
        {"sheet": "Proyección", "range": "E111:F111", "formula": f"=LINEST({start_col}105:M105,LN({start_col}103:M103))"},
        {"sheet": "Proyección", "range": "J111:K111", "formula": f"=LINEST({start_col}104:L104,LN({start_col}103:L103))"},
        {"sheet": "Proyección", "range": "E127:F127", "formula": f"=LINEST({start_col}121:M121,LN({start_col}119:M119))"},
        {"sheet": "Proyección", "range": "J127:K127", "formula": f"=LINEST({start_col}120:L120,LN({start_col}119:L119))"},
        {"sheet": "Proyección", "range": "E143:F143", "formula": f"=LINEST({start_col}137:M137,LN({start_col}135:M135))"},
        {"sheet": "Proyección", "range": "J143:K143", "formula": f"=LINEST({start_col}136:L136,LN({start_col}135:L135))"},
        {"sheet": "Proyección", "range": "G160:H160", "formula": f"=LINEST({start_col}154:L154,LN({start_col}152:L152))"},
        {"sheet": "Proyección", "range": "J160:K160", "formula": f"=LINEST({start_col}153:L153,LN({start_col}152:L152))"},
        {"sheet": "Proyección", "range": "G176:H176", "formula": f"=LINEST({start_col}170:M170,LN({start_col}168:M168))"},
        {"sheet": "Proyección", "range": "J176:K176", "formula": f"=LINEST({start_col}169:L169,LN({start_col}168:L168))"},
        {
            "sheet": "Proyección",
            "range": "F198:G198",
            "formula": f"=LINEST({special_start_col}194:L194,LN({start_col}189:K189))",
        },
        {
            "sheet": "Proyección",
            "range": "K198:L198",
            "formula": f"=LINEST({special_start_col}193:L193,LN({start_col}189:K189))",
        },
        {"sheet": "Proyección", "range": "F219:G219", "formula": f"=LINEST({start_col}213:L213,LN({start_col}208:L208))"},
        {"sheet": "Proyección", "range": "K219:L219", "formula": f"=LINEST({start_col}212:L212,LN({start_col}208:L208))"},
        {"sheet": "Integrado", "range": "J14:K14", "formula": f"=LINEST({start_col}7:L7,LN({start_col}6:L6))"},
    ]


def _build_valora_linest_write_requests(
    *,
    user_email: str,
    item_id: str,
    years_start_col: str,
    headers: dict[str, str],
    projection_sheet: str = "Proyección",
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for req_id, definition in enumerate(
        _build_valora_linest_formulas(years_start_col), start=1
    ):
        sheet_name = (
            projection_sheet
            if definition["sheet"] == "Proyección"
            else definition["sheet"]
        )
        requests.append(
            {
                "id": str(req_id),
                "method": "PATCH",
                "url": _build_excel_range_url(
                    user_email,
                    item_id,
                    sheet_name,
                    definition["range"],
                ),
                # LINEST returns two coefficients. Graph treats null as "do not
                # change this cell", so only the existing formula anchor changes.
                "body": {"formulas": [[definition["formula"], None]]},
                "headers": headers,
            }
        )
    return requests


def _build_valora_projection_block_formulas(
    years_start_col: str,
) -> list[list[str | None]]:
    """Extend the existing projection formulas over the active historical years."""
    start_col = years_start_col.upper()
    columns = [chr(col) for col in range(ord(start_col), ord("L") + 1)]
    first_row = 53
    last_row = 75
    matrix: list[list[str | None]] = [
        [None for _ in columns] for _ in range(last_row - first_row + 1)
    ]

    def set_formula(row: int, column_index: int, formula: str) -> None:
        matrix[row - first_row][column_index] = formula

    # The first year is written as a fixed value. Every following year keeps
    # the template's original continuation formula: previous year + 1.
    for header_row in (53, 67, 72):
        for column_index in range(1, len(columns)):
            previous_col = columns[column_index - 1]
            set_formula(
                header_row,
                column_index,
                f"={previous_col}{header_row}+1",
            )

    source_rows = {
        54: lambda col: f"={col}38",
        55: lambda col: f"={col}39",
        56: lambda col: f"={col}40",
        57: lambda col: f"={col}41",
        58: lambda col: f"={col}43",
        59: lambda col: f"=+{col}44",
        60: lambda col: f"=+{col}56+{col}57+{col}58+{col}59",
        61: lambda col: f"=-{col}64*{col}60",
        62: lambda col: f"={col}42",
        63: lambda col: f"={col}60+{col}61+{col}62",
        64: lambda col: f"=-{col}50/{col}49",
        65: lambda col: f"=-{col}61/{col}49",
        68: lambda col: f"={col}13",
        69: lambda col: f"={col}14",
        70: lambda col: f"={col}68+{col}69",
        73: lambda col: f"={col}5+{col}8",
        74: lambda col: f"={col}20",
        75: lambda col: f"={col}73-{col}74",
    }
    for row, formula_builder in source_rows.items():
        for column_index, column in enumerate(columns):
            set_formula(row, column_index, formula_builder(column))

    return matrix


def _build_valora_projection_block_write_requests(
    *,
    user_email: str,
    item_id: str,
    years_start_col: str,
    first_year: int,
    headers: dict[str, str],
    projection_sheet: str = "Proyección",
) -> list[dict[str, Any]]:
    requests = []
    for req_id, row in enumerate((53, 67, 72), start=1):
        requests.append(
            {
                "id": str(req_id),
                "method": "PATCH",
                "url": _build_excel_range_url(
                    user_email,
                    item_id,
                    projection_sheet,
                    f"{years_start_col}{row}",
                ),
                "body": {"values": [[first_year]]},
                "headers": headers,
            }
        )

    requests.append(
        {
            "id": "4",
            "method": "PATCH",
            "url": _build_excel_range_url(
                user_email,
                item_id,
                projection_sheet,
                f"{years_start_col}53:L75",
            ),
            # Null cells preserve formulas and blanks outside this block's
            # existing year-continuation and calculation formulas.
            "body": {
                "formulas": _build_valora_projection_block_formulas(
                    years_start_col
                )
            },
            "headers": headers,
        }
    )
    return requests


def _build_valora_linest_source_formulas(
    years_start_col: str,
) -> tuple[list[list[str | None]], list[list[str | None]]]:
    """Build the source tables used by every dynamic LINEST calculation."""
    start_col = years_start_col.upper()
    columns = [chr(col) for col in range(ord(start_col), ord("M") + 1)]
    historical_columns = columns[:-1]
    projection_first_row = 86
    projection_last_row = 214
    projection: list[list[str | None]] = [
        [None for _ in columns]
        for _ in range(projection_last_row - projection_first_row + 1)
    ]

    def set_projection(row: int, column: str, formula: str) -> None:
        projection[row - projection_first_row][columns.index(column)] = formula

    def populate_header(year_row: int, index_row: int) -> None:
        for column in historical_columns:
            set_projection(year_row, column, f"={column}$72")
        set_projection(year_row, "M", f"=L{year_row}+1")
        for index, column in enumerate(columns[1:], start=1):
            previous = columns[index - 1]
            set_projection(index_row, column, f"={previous}{index_row}+1")

    def populate_log_block(
        *,
        year_row: int,
        index_row: int,
        historical_row: int,
        estimate_row: int,
        final_row: int,
        source_formula,
        slope_cell: str,
        adjusted_constant_cell: str,
        forecast_linear: bool,
    ) -> None:
        populate_header(year_row, index_row)
        for column in historical_columns:
            set_projection(
                historical_row,
                column,
                source_formula(column),
            )
            set_projection(
                estimate_row,
                column,
                f"=LN({column}{index_row})*{slope_cell}+{adjusted_constant_cell}",
            )
            set_projection(final_row, column, f"={column}{historical_row}")
        if forecast_linear:
            set_projection(
                estimate_row,
                "M",
                f"=FORECAST.LINEAR(M{year_row},"
                f"${start_col}${estimate_row}:$L${estimate_row},"
                f"${start_col}${year_row}:$L${year_row})",
            )

    populate_log_block(
        year_row=86,
        index_row=87,
        historical_row=88,
        estimate_row=89,
        final_row=92,
        source_formula=lambda col: f"={col}54",
        slope_cell="$J$95",
        adjusted_constant_cell="$K$100",
        forecast_linear=True,
    )
    for index, column in enumerate(historical_columns[1:], start=1):
        previous = historical_columns[index - 1]
        set_projection(91, column, f"=+{column}88/{previous}88-1")

    populate_log_block(
        year_row=102,
        index_row=103,
        historical_row=104,
        estimate_row=105,
        final_row=108,
        source_formula=lambda col: f'=IFERROR(-{col}39,"")',
        slope_cell="$J$111",
        adjusted_constant_cell="$K$116",
        forecast_linear=True,
    )

    # Sales expenses keep the template's smoothed historical series.
    populate_header(118, 119)
    for column in historical_columns:
        set_projection(120, column, f'=IFERROR(-{column}57,"")')
        set_projection(124, column, f"={column}120")
    first_average_end = historical_columns[3]
    set_projection(
        121,
        start_col,
        f"=AVERAGE({start_col}120:{first_average_end}120)",
    )
    for index, column in enumerate(historical_columns[1:-1], start=1):
        previous = historical_columns[index - 1]
        set_projection(
            121,
            column,
            "=ROUND(LET("
            f"hoy,{column}120,ayer,{previous}120,suav_ant,{previous}121,"
            f"crec_hist,MIN(MAX(IFERROR(hoy/ayer-1,0%),0%),10%),"
            "estimado,suav_ant*(1+crec_hist),"
            "candidato,IF(AND(hoy>=suav_ant,hoy<=suav_ant*1.1),hoy,estimado),"
            "MAX(suav_ant,MIN(candidato,suav_ant*1.1))),0)",
        )
    previous_to_l = historical_columns[-2]
    set_projection(
        121,
        "L",
        "=ROUND(LET("
        f"hist_ult,L120,hist_ant,{previous_to_l}120,"
        f"suav_ant,{previous_to_l}121,"
        f"prom_3max,AVERAGE(LARGE({start_col}120:L120,1),"
        f"LARGE({start_col}120:L120,2),LARGE({start_col}120:L120,3)),"
        "crec_hist,MIN(MAX(IFERROR(hist_ult/hist_ant-1,0%),0%),10%),"
        "estimado,suav_ant*(1+crec_hist),"
        "objetivo,MAX(hist_ult,prom_3max,estimado),"
        "MAX(suav_ant,MIN(objetivo,suav_ant*1.1))),0)",
    )
    set_projection(
        121,
        "M",
        f"=FORECAST.LINEAR(M118,${start_col}$121:$L$121,"
        f"${start_col}$118:$L$118)",
    )

    populate_log_block(
        year_row=134,
        index_row=135,
        historical_row=136,
        estimate_row=137,
        final_row=140,
        source_formula=lambda col: f"=-{col}58",
        slope_cell="$J$143",
        adjusted_constant_cell="$K$148",
        forecast_linear=True,
    )
    populate_log_block(
        year_row=151,
        index_row=152,
        historical_row=153,
        estimate_row=154,
        final_row=157,
        source_formula=lambda col: f"={col}59",
        slope_cell="$J$160",
        adjusted_constant_cell="$K$165",
        forecast_linear=False,
    )
    set_projection(154, "M", "=+LN(M152)*$G$160+H165")
    populate_log_block(
        year_row=167,
        index_row=168,
        historical_row=169,
        estimate_row=170,
        final_row=173,
        source_formula=lambda col: f"={col}62",
        slope_cell="$J$176",
        adjusted_constant_cell="$K$181",
        forecast_linear=True,
    )

    # CAPEX: the dependent series starts one column after the first year and
    # excludes L's following index, exactly as F194:L194 vs E189:K189 does.
    populate_header(188, 189)
    for column in historical_columns:
        set_projection(190, column, f"={column}70")
    for index, column in enumerate(historical_columns[1:], start=1):
        previous = historical_columns[index - 1]
        set_projection(192, column, f"={column}190-{previous}190")
        set_projection(193, column, f"={column}192/{column}92")
        set_projection(
            194,
            column,
            f"=LN({previous}189)*$K$198+$L$203",
        )
        set_projection(195, column, f"={column}192")
    set_projection(193, "M", "=LN(L189)*F198+G203")
    set_projection(195, "M", "=$M$193*M92")
    set_projection(190, "M", "=+L190+M195")

    populate_header(207, 208)
    for column in historical_columns:
        set_projection(209, column, f"={column}75")
        set_projection(212, column, f"={column}209/{column}92")
        set_projection(
            213,
            column,
            f"=LN({column}208)*$K$219+$L$224",
        )
    for index, column in enumerate(historical_columns[1:], start=1):
        previous = historical_columns[index - 1]
        set_projection(214, column, f"={column}209-{previous}209")
    set_projection(211, "M", "=LN(M208)*F219+G224")
    set_projection(212, "M", "=$M$211*M92")
    set_projection(214, "M", "=M212-L209")

    integrated_rows = 5
    integrated: list[list[str | None]] = [
        [None for _ in columns] for _ in range(integrated_rows)
    ]

    def set_integrated(row: int, column: str, formula: str) -> None:
        integrated[row - 7][columns.index(column)] = formula

    for column in historical_columns:
        set_integrated(7, column, f"=Proyección!{column}63")
        set_integrated(8, column, f"=LN({column}6)*$J$14+$K$19")
        set_integrated(11, column, f"={column}7")
    set_integrated(
        8,
        "M",
        f"=FORECAST.LINEAR(M5,{start_col}8:L8,{start_col}5:L5)",
    )

    return projection, integrated


def _build_valora_linest_source_write_requests(
    *,
    user_email: str,
    item_id: str,
    years_start_col: str,
    headers: dict[str, str],
    projection_sheet: str = "Proyección",
) -> list[dict[str, Any]]:
    projection, integrated = _build_valora_linest_source_formulas(
        years_start_col
    )
    requests: list[dict[str, Any]] = []
    for request_id, row in enumerate((87, 103, 119, 135, 152, 168, 189, 208), start=1):
        requests.append(
            {
                "id": str(request_id),
                "method": "PATCH",
                "url": _build_excel_range_url(
                    user_email,
                    item_id,
                    projection_sheet,
                    f"{years_start_col}{row}",
                ),
                "body": {"values": [[1]]},
                "headers": headers,
            }
        )
    requests.extend(
        [
            {
                "id": "9",
                "method": "PATCH",
                "url": _build_excel_range_url(
                    user_email,
                    item_id,
                    projection_sheet,
                    f"{years_start_col}86:M214",
                ),
                "body": {"formulas": projection},
                "headers": headers,
            },
            {
                "id": "10",
                "method": "PATCH",
                "url": _build_excel_range_url(
                    user_email,
                    item_id,
                    "Integrado",
                    f"{years_start_col}7:M11",
                ),
                "body": {"formulas": integrated},
                "headers": headers,
            },
        ]
    )
    if years_start_col != "C":
        inactive_end_col = chr(ord(years_start_col) - 1)
        inactive_width = ord(inactive_end_col) - ord("C") + 1
        requests.append(
            {
                "id": "11",
                "method": "PATCH",
                "url": _build_excel_range_url(
                    user_email,
                    item_id,
                    "Integrado",
                    f"C7:{inactive_end_col}11",
                ),
                "body": {
                    "values": [
                        ["" for _ in range(inactive_width)] for _ in range(5)
                    ]
                },
                "headers": headers,
            }
        )
    return requests


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

    if not normalized_years:
        return

    # Siempre ordenar años de menor a mayor para que el año más antiguo quede
    # a la izquierda y el más reciente a la derecha. Se invierten también los
    # valores de cada fila para mantener la correspondencia con el eje.
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

    # La plantilla admite como máximo 10 años (C:L). Si llegan más periodos,
    # conservamos los 10 más recientes para que el mayor año permanezca en L.
    source_start = max(0, len(normalized_years) - 10)
    years_to_write = normalized_years[source_start:]
    N = len(years_to_write)

    # El rango de años se ajusta al número de años enviados.
    # Ej: 10 años -> C2:L2; 8 años -> E2:L2; 5 años -> H2:L2. Así no se
    # pisan columnas vacías ni se envían dimensiones incorrectas a Graph API.
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

    # 1. Matriz de Balance General: rango dinámico de 32 filas x N años.
    bg_matrix = [[None for _ in range(N)] for _ in range(32)]
    for r in range(min(32, len(bg_rows))):
        row_dict = bg_rows[r] if isinstance(bg_rows[r], dict) else {}
        row_vals = list(row_dict.get("values", [])[source_start : source_start + N])
        for col_offset, val in enumerate(row_vals):
            n = _extract_number(val)
            if n is not None:
                bg_matrix[r][col_offset] = n
            # Si no es numérico, dejamos None (no string) para no corromper fórmulas

    # 2. Matriz de Estado de Resultados: rango dinámico de 14 filas x N años.
    er_matrix = [[None for _ in range(N)] for _ in range(14)]
    for r in range(min(14, len(er_rows))):
        row_dict = er_rows[r] if isinstance(er_rows[r], dict) else {}
        row_vals = list(row_dict.get("values", [])[source_start : source_start + N])
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
            "url": _build_excel_range_url(
                email, item_id, sheet_name, f"{years_start_col}4:L35"
            ),
            "body": {"values": bg_matrix},
            "headers": headers,
        },
        {
            "id": "4",
            "method": "PATCH",
            "url": _build_excel_range_url(
                email, item_id, sheet_name, f"{years_start_col}38:L51"
            ),
            "body": {"values": er_matrix},
            "headers": headers,
        },
    ]

    # Remove the template's static historical years to the left of the active
    # range. This prevents a 5-year input, for example, from retaining E:G from
    # the original 8-year workbook.
    if years_start_col != "C":
        inactive_end_col = chr(ord(years_start_col) - 1)
        inactive_width = ord(inactive_end_col) - ord("C") + 1

        def _blank_matrix(rows: int) -> list[list[str]]:
            return [["" for _ in range(inactive_width)] for _ in range(rows)]

        inactive_ranges = (
            ("C2", f"{inactive_end_col}2", 1),
            ("C4", f"{inactive_end_col}35", 32),
            ("C37", f"{inactive_end_col}37", 1),
            ("C38", f"{inactive_end_col}51", 14),
            ("C53", f"{inactive_end_col}75", 23),
            ("C86", f"{inactive_end_col}92", 7),
            ("C102", f"{inactive_end_col}108", 7),
            ("C118", f"{inactive_end_col}124", 7),
            ("C134", f"{inactive_end_col}140", 7),
            ("C151", f"{inactive_end_col}157", 7),
            ("C167", f"{inactive_end_col}173", 7),
            ("C188", f"{inactive_end_col}195", 8),
            ("C207", f"{inactive_end_col}214", 8),
        )
        for request_id, (range_start, range_end, row_count) in enumerate(
            inactive_ranges, start=5
        ):
            write_requests.append(
                {
                    "id": str(request_id),
                    "method": "PATCH",
                    "url": _build_excel_range_url(
                        email,
                        item_id,
                        sheet_name,
                        f"{range_start}:{range_end}",
                    ),
                    "body": {"values": _blank_matrix(row_count)},
                    "headers": headers,
                }
            )

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

    projection_block_requests = _build_valora_projection_block_write_requests(
        user_email=email,
        item_id=item_id,
        years_start_col=years_start_col,
        first_year=years_to_write[0],
        headers=headers,
    )
    projection_block_responses = await service.execute_batch(
        projection_block_requests
    )
    projection_block_failures = (
        [
            response
            for response in projection_block_responses
            if response.get("status", 0) >= 400
        ]
        if isinstance(projection_block_responses, list)
        else []
    )
    if projection_block_failures and all(
        response.get("status") == 404
        for response in projection_block_failures
    ):
        projection_block_requests = _build_valora_projection_block_write_requests(
            user_email=email,
            item_id=item_id,
            years_start_col=years_start_col,
            first_year=years_to_write[0],
            headers=headers,
            projection_sheet="Proyeccion",
        )
        projection_block_responses = await service.execute_batch(
            projection_block_requests
        )
        projection_block_failures = (
            [
                response
                for response in projection_block_responses
                if response.get("status", 0) >= 400
            ]
            if isinstance(projection_block_responses, list)
            else []
        )
    if projection_block_failures:
        raise RuntimeError(
            "No se pudieron extender las formulas historicas de Proyeccion: "
            f"{projection_block_failures}"
        )

    logger.info(
        "[VALORA WRITE] Bloques historicos actualizados desde %s para %s anios",
        years_start_col,
        N,
    )

    linest_source_requests = _build_valora_linest_source_write_requests(
        user_email=email,
        item_id=item_id,
        years_start_col=years_start_col,
        headers=headers,
    )
    linest_source_responses = await service.execute_batch(
        linest_source_requests
    )
    linest_source_failures = (
        [
            response
            for response in linest_source_responses
            if response.get("status", 0) >= 400
        ]
        if isinstance(linest_source_responses, list)
        else []
    )
    source_projection_404_ids = {
        str(response.get("id"))
        for response in linest_source_failures
        if response.get("status") == 404 and int(response.get("id", 0)) <= 9
    }
    source_non_sheet_failures = [
        response
        for response in linest_source_failures
        if str(response.get("id")) not in source_projection_404_ids
    ]
    if source_non_sheet_failures:
        raise RuntimeError(
            "No se pudieron actualizar las tablas fuente de LINEST: "
            f"{source_non_sheet_failures}"
        )
    if source_projection_404_ids:
        source_fallback_requests = _build_valora_linest_source_write_requests(
            user_email=email,
            item_id=item_id,
            years_start_col=years_start_col,
            headers=headers,
            projection_sheet="Proyeccion",
        )
        source_fallback_requests = [
            request
            for request in source_fallback_requests
            if request["id"] in source_projection_404_ids
        ]
        source_fallback_responses = await service.execute_batch(
            source_fallback_requests
        )
        source_fallback_failures = (
            [
                response
                for response in source_fallback_responses
                if response.get("status", 0) >= 400
            ]
            if isinstance(source_fallback_responses, list)
            else []
        )
        if source_fallback_failures:
            raise RuntimeError(
                "No se pudieron actualizar las tablas fuente en Proyeccion: "
                f"{source_fallback_failures}"
            )

    linest_requests = _build_valora_linest_write_requests(
        user_email=email,
        item_id=item_id,
        years_start_col=years_start_col,
        headers=headers,
    )
    linest_responses = await service.execute_batch(linest_requests)
    linest_failures = (
        [response for response in linest_responses if response.get("status", 0) >= 400]
        if isinstance(linest_responses, list)
        else []
    )

    # Some workbooks expose the projection sheet without the accent. Retry only
    # that known naming mismatch; other formula errors must remain visible.
    projection_404_ids = {
        str(response.get("id"))
        for response in linest_failures
        if response.get("status") == 404 and int(response.get("id", 0)) <= 16
    }
    non_sheet_failures = [
        response
        for response in linest_failures
        if str(response.get("id")) not in projection_404_ids
    ]
    if non_sheet_failures:
        raise RuntimeError(
            f"No se pudieron actualizar las formulas LINEST: {non_sheet_failures}"
        )

    if projection_404_ids:
        fallback_requests = _build_valora_linest_write_requests(
            user_email=email,
            item_id=item_id,
            years_start_col=years_start_col,
            headers=headers,
            projection_sheet="Proyeccion",
        )
        fallback_requests = [
            request
            for request in fallback_requests
            if request["id"] in projection_404_ids
        ]
        fallback_responses = await service.execute_batch(fallback_requests)
        fallback_failures = (
            [
                response
                for response in fallback_responses
                if response.get("status", 0) >= 400
            ]
            if isinstance(fallback_responses, list)
            else []
        )
        if fallback_failures:
            raise RuntimeError(
                "No se pudieron actualizar las formulas LINEST en Proyeccion: "
                f"{fallback_failures}"
            )

    logger.info(
        "[VALORA WRITE] Formulas LINEST actualizadas para %s anios desde %s",
        N,
        years_start_col,
    )

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
    sensitivity_input: dict[str, Any] | None = None,
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

    sensibilidad_entry: dict[str, Any] | None = None

    try:
        if latest_input:
            logger.info(
                f"[VALORA] Escribiendo inputs base en Excel para item {item_id}; "
                f"balance_rows={len(latest_input.get('balance_table', {}).get('rows', []))}, "
                f"results_rows={len(latest_input.get('results_table', {}).get('rows', []))}"
            )
            await _write_valora_inputs_to_excel(
                item_id=item_id, input_payload=latest_input, session_id=session_id
            )
            t0 = _lap("_write_valora_inputs_to_excel", t0)

        # --- SENSIBILIDAD VALORA ---
        if sensitivity_input:
            logger.info(
                f"[VALORA] Escribiendo inputs de sensibilidad: {sensitivity_input}"
            )
            for field, cell in VALORA_SENSITIVITY_INPUT_CELL_MAP.items():
                val = sensitivity_input.get(field)
                if val is not None:
                    # Normalizar valor si es porcentaje
                    final_val = _to_excel_input_value(field, val)
                    logger.info(
                        f"[VALORA SENSITIVITY] Writing {field}={final_val} to Plantilla Usuario!{cell}"
                    )
                    await service.update_excel_cell(
                        item_id,
                        "Plantilla Usuario",
                        cell,
                        final_val,
                        session_id=session_id,
                    )
            t0 = _lap("write_valora_sensitivity_inputs", t0)

        await asyncio.sleep(0.3)
        t0 = _lap("sleep post-escritura", t0)

        logger.info("[VALORA] Forzando recálculo fullRebuild")
        await service.force_calculate_excel(item_id, session_id=session_id)
        t0 = _lap("force_calculate_excel fullRebuild", t0)

        logger.info("[VALORA] Leyendo resultados")
        resultados = await _build_valora_output_entry(item_id, session_id=session_id)
        t0 = _lap("_build_valora_output_entry", t0)

        source_currency = str(latest_input.get("moneda") or "USD").upper()
        resultados["source_currency"] = source_currency
        if source_currency == "USD":
            resultados["fx_to_usd"] = 1.0
        else:
            from app.api.main.chatbot.boa import get_fx_rate

            try:
                fx_to_usd = await asyncio.to_thread(
                    get_fx_rate, source_currency
                )
                # BOA uses 1.0 as its network-failure fallback. None prevents
                # Valora from presenting an unconverted local amount as USD.
                resultados["fx_to_usd"] = (
                    fx_to_usd if abs(fx_to_usd - 1.0) > 1e-9 else None
                )
            except Exception:
                resultados["fx_to_usd"] = None
                logger.exception(
                    "[VALORA] No se pudo obtener FX %s -> USD", source_currency
                )

        logger.info(f"[VALORA] Resultados leídos: {resultados}")
        payload_data["active_session_id"] = session_id
        payload_data["resultados"] = resultados
        payload_data["resultados"]["inputs"] = latest_input

        if sensitivity_input:
            sensibilidad_entry = {
                "created_at": _now_iso(),
                "inputs": sensitivity_input,
            }
            # Copiar resultados relevantes de sensibilidad
            for key in ("wacc", "balance", "conceptos", "integrado"):
                if key in resultados:
                    sensibilidad_entry[key] = resultados[key]
            logger.info(f"[VALORA] Sensibilidad entry construida: {sensibilidad_entry}")
            payload_data["sensibilizacion"] = [sensibilidad_entry]
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

