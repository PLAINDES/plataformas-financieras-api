import json

from app.models.main import CalculationType

from .formatters import _now_iso


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


def _extract_input_payload(data: object) -> dict:
    if not isinstance(data, dict):
        return {}

    maybe_inputs = data.get("inputs")
    if isinstance(maybe_inputs, list) and maybe_inputs:
        latest = maybe_inputs[-1]
        if not isinstance(latest, dict):
            return {}
        return {k: v for k, v in latest.items() if k != "created_at"}

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


def _merge_unique_entries(
    existing_entries: list[dict], incoming_entries: object
) -> list[dict]:
    """
    Mezcla las entradas históricas garantizando la unicidad basada en el valor del BOA.
    Si un escenario con el mismo BOA ya existe, lo actualiza con los parámetros más recientes.
    """

    merged = {e.get("boa"): e for e in existing_entries if e.get("boa") is not None}
    incoming = _stamp_entries(incoming_entries)

    # Fallback de compatibilidad si la estructura no pertenece a bloques de sensibilización con BOA
    if not merged and existing_entries:
        existing_keys = {
            json.dumps(
                _entry_payload_without_timestamp(entry),
                sort_keys=True,
                ensure_ascii=False,
            )
            for entry in existing_entries
        }
        res = list(existing_entries)
        for entry in incoming:
            key = json.dumps(
                _entry_payload_without_timestamp(entry),
                sort_keys=True,
                ensure_ascii=False,
            )
            if key not in existing_keys:
                res.append(entry)
        return _stamp_entries(res)

    # Fusionar entradas entrantes usando el 'boa' como clave única de comparación
    for entry in incoming:
        boa_val = entry.get("boa")
        if boa_val is not None:
            # Reemplaza o añade el bloque del escenario específico
            merged[boa_val] = entry

    # Convertir los valores del diccionario a una lista
    return _stamp_entries(list(merged.values()))


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
    current_file_raw = (
        existing.get("file") if isinstance(existing.get("file"), dict) else None
    )

    if file_meta:
        normalized["file"] = file_meta
    elif current_file_raw:
        normalized["file"] = current_file_raw

    if isinstance(payload_data, dict) and "active_session_id" in payload_data:
        normalized["active_session_id"] = payload_data["active_session_id"]
    elif isinstance(existing, dict) and "active_session_id" in existing:
        normalized["active_session_id"] = existing["active_session_id"]

    return normalized
