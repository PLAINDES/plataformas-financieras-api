# app/services/valora/ai_estimator.py
"""
Estimación de tasas Valora (forecast ingresos, forecast FDE y crecimiento perpetuo)
usando Gemini y todo el contexto disponible: históricos de la empresa, sector/país
y datos de configuración del sistema (Damodaran, EMBI, RF, prima, etc.).
"""
import json
import logging
import re
from typing import Any

from app.services.valora.gemini_client import call_gemini

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Analista financiero DCF. Estima 3 tasas primer período proyección usando todo el contexto.

CONTEXTO:
{context}

TASAS (decimal, 0.10=10%):
1. forecast_ingresos: crecimiento ingresos/ventas.
2. forecast_fde: crecimiento FDE/FCF.
3. crecimiento_perpetuo: crecimiento perpetuo largo plazo FDE.

REGLAS:
- Partir de CAGR/YoY históricos.
- Ajustar por sector/país: Damodaran, EMBI, inflación, tasa libre riesgo, prima riesgo.
- Perpetuo conservador: cercano inflación/PIB, menor WACC.
- Si sector cíclico/volátil, suavizar hacia medias sectoriales.
- Rationale: 1-2 oraciones, citar datos clave.
- suggested_range: min/max decimales.
- confidence: "high"/"medium"/"low".

JSON EXACTO, sin texto fuera:
{{
  "forecast_ingresos": {{"value": 0.12, "rationale": "...", "confidence": "medium", "suggested_range": {{"min": 0.08, "max": 0.16}}}},
  "forecast_fde": {{"value": 0.10, "rationale": "...", "confidence": "medium", "suggested_range": {{"min": 0.06, "max": 0.14}}}},
  "crecimiento_perpetuo": {{"value": 0.025, "rationale": "...", "confidence": "high", "suggested_range": {{"min": 0.015, "max": 0.035}}}}
}}"""


RATE_LIMITS = {
    "forecast_ingresos": {"min": -0.50, "max": 1.00},
    "forecast_fde": {"min": -0.50, "max": 1.00},
    "crecimiento_perpetuo": {"min": -0.05, "max": 0.10},
}


def _extract_json(text: str) -> dict:
    """Extrae el primer objeto JSON válido de la respuesta.
    Maneja JSON envuelto en markdown code blocks y JSON truncado."""
    if not text:
        return {}

    cleaned = text.strip()

    code_block = re.search(r"```(?:json)?\s*\n?(.*)", cleaned, re.DOTALL)
    if code_block:
        cleaned = code_block.group(1).strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    repaired = _repair_truncated_json(cleaned)
    if repaired:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

    return {}


def _repair_truncated_json(text: str) -> str | None:
    """Intenta reparar JSON truncado cerrando llaves/corchetes pendientes."""
    open_braces = 0
    open_brackets = 0
    in_string = False
    escape = False

    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            open_braces += 1
        elif ch == "}":
            open_braces = max(0, open_braces - 1)
        elif ch == "[":
            open_brackets += 1
        elif ch == "]":
            open_brackets = max(0, open_brackets - 1)

    if in_string:
        text += '"'
    text += "]" * open_brackets
    text += "}" * open_braces
    return text


def _validate_value(value: Any, key: str) -> float | None:
    """Valida que el valor estimado esté dentro de rangos financieramente razonables."""
    if value is None:
        return None
    try:
        num = float(value)
    except (ValueError, TypeError):
        logger.warning(f"[VALORA AI ESTIMATOR] {key} no es numérico: {value}")
        return None

    limits = RATE_LIMITS.get(key, {})
    min_val = limits.get("min", -1.0)
    max_val = limits.get("max", 1.0)
    if not min_val <= num <= max_val:
        logger.warning(
            f"[VALORA AI ESTIMATOR] {key} fuera de rango [{min_val}, {max_val}]: {num}"
        )
        return None
    return num


async def estimate_valora_rates(context: dict[str, Any]) -> dict[str, Any] | None:
    """
    Llama a Gemini para estimar las tres tasas de Valora.

    Args:
        context: Dict con todo el contexto del cálculo.

    Returns:
        Dict con las tasas estimadas, justificaciones y metadatos; None si falla.
    """
    prompt = SYSTEM_PROMPT.format(
        context=json.dumps(context, ensure_ascii=False, default=str)
    )

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.25,
            "maxOutputTokens": 8192,
            "topP": 0.8,
            "topK": 40,
        },
    }

    raw_text, model_used = await call_gemini(payload)
    if not raw_text:
        return None

    logger.warning("[VALORA AI ESTIMATOR] Raw response len=%d, first 300: %s", len(raw_text), raw_text[:300])

    parsed = _extract_json(raw_text)
    logger.warning("[VALORA AI ESTIMATOR] Parsed keys: %s", list(parsed.keys()) if parsed else "empty")

    rates: dict[str, Any] = {}
    any_valid = False

    for key in ("forecast_ingresos", "forecast_fde", "crecimiento_perpetuo"):
        entry = parsed.get(key) or {}
        value = _validate_value(entry.get("value"), key)
        if value is not None:
            any_valid = True
        rates[key] = {
            "value": value,
            "rationale": str(entry.get("rationale", "")),
            "confidence": str(entry.get("confidence", "low")).lower(),
            "suggested_range": entry.get("suggested_range") or {},
        }

    if not any_valid:
        logger.warning("[VALORA AI ESTIMATOR] Ninguna tasa válida recibida de Gemini.")
        return None

    return {
        "model_used": model_used,
        "rates": rates,
        "raw_response": parsed,
    }
