import re
from datetime import datetime as _dt


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
        "country",
        "revenue_forecast_rate",
        "fdc_forecast_rate",
        "perpetual_growth_rate",
    }

    if field not in percentage_like_fields:
        n = _extract_number(value)
        final_val = n if n is not None else value
        return final_val

    n = _extract_number(value)
    if n is None:
        print(
            f"[EXCEL WRITE] Percentage Field '{field}': Could not extract number from '{value}'"
        )
        return value

    # ASIGNAMOS UN VALOR POR DEFECTO PARA EVITAR ERRORES DE LOCAL VARIABLE
    final_val = n

    if field == "country":
        final_val = n / 10000 if abs(n) > 1 else n / 100
    elif field in (
        "devaluacion",
        "costo_deuda",
        "revenue_forecast_rate",
        "fdc_forecast_rate",
        "perpetual_growth_rate",
    ):
        final_val = n / 100
    else:
        # Para todos los demás porcentajes (tasa_impositiva, porcentaje_deuda, etc)
        final_val = n / 100 if abs(n) > 1 else n

    return final_val
