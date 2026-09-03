# app/services/valora/ai_explainer.py
"""
Explicación y contexto de las recomendaciones de tasas de Valora usando Gemini.

Solo recibe AGREGADOS (tasas, fuentes, CAGR, medias históricas, inflación).
No envía tablas crudas de estados financieros. Si Gemini falla o no hay
API key, retorna None y el flujo principal continúa con las tasas
calculadas de forma determinista.
"""
import json
import logging
import re

from app.services.valora.gemini_client import call_gemini

logger = logging.getLogger("uvicorn.error")

SYSTEM_PROMPT = """Eres un analista financiero senior especializado en valoración de empresas (DCF).
Recibes un resumen AGREGADO de tasas recomendadas para un modelo de sensibilización de flujo de caja.

DATOS DEL CÁLCULO (agregados, no tablas crudas):
{data}

RESPONDE EXCLUSIVAMENTE EN JSON con esta estructura exacta:
{{
  "rates": {{
    "forecast_ingresos_1er_periodo": {{
      "explanation": "1-2 oraciones en español explicando por qué esa tasa es razonable, citando su fuente (Excel, CAGR, media histórica, default).",
      "suggested_range": {{"min": 0.0, "max": 0.0}},
      "outlier": false,
      "outlier_reason": ""
    }},
    "forecast_fde_1er_periodo": {{...}},
    "crecimiento_perpetuo": {{...}}
  }}
}}

REGLAS:
- suggested_range en decimal (0.10 = 10%), un rango razonable alrededor de la tasa recomendada (ej. recomendación 12% -> min 0.08, max 0.16).
- outlier=true SOLO si la tasa es claramente atípica (CAGR > 40% o < -15%, o fuente "default" o "empty"); explica el motivo en outlier_reason.
- explanations breves, en español, en lenguaje profesional pero claro para un usuario no técnico.
- Si la tasa es None, explanation debe indicar que no hay dato y sugerir revisión manual; usa suggested_range con valores del contexto.
- NO agregues texto fuera del JSON."""


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


async def generate_valora_ai_analysis(result: dict) -> dict | None:
    """Genera explicaciones/rangos/outliers con Gemini para el resultado de Valora."""
    # Solo agregados, sin tablas crudas
    rates_summary = {}
    for key, rate in (result.get("rates") or {}).items():
        if not isinstance(rate, dict):
            continue
        fin = rate.get("financial_data") or {}
        ai_est = rate.get("ai_estimate") or {}
        rates_summary[key] = {
            "label": rate.get("label"),
            "recommendation_pct": rate.get("recommendation_pct"),
            "recommendation_source": rate.get("recommendation_source"),
            "model_source": rate.get("model_source"),
            "calculated_cagr": fin.get("calculated_cagr"),
            "calculated_yoy": fin.get("calculated_yoy"),
            "historical_diagnostics": rate.get("historical_diagnostics"),
            "inflation_value": (rate.get("inflation_driver") or {}).get("value"),
            "ai_rationale": ai_est.get("rationale"),
            "ai_confidence": ai_est.get("confidence"),
        }

    data = {
        "warnings": result.get("warnings", []),
        "rates": rates_summary,
    }   

    prompt = SYSTEM_PROMPT.format(data=json.dumps(data, ensure_ascii=False, default=str))

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 4096,
            "topP": 0.8,
            "topK": 40,
        },
    }

    raw_text, model_used = await call_gemini(payload)
    if not raw_text:
        logger.warning("[VALORA AI] Respuesta Gemini vacía o fallo en llamada.")
        return None

    parsed = _extract_json(raw_text)

    if not parsed.get("rates"):
        logger.warning("[VALORA AI] Respuesta sin bloque 'rates'.")
        return None

    return {
        "model_used": model_used,
        "analysis": parsed,
        "generated_at_note": "Análisis generado por IA (Gemini) sobre datos agregados.",
    }
