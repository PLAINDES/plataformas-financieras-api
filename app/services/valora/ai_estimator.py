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

SYSTEM_PROMPT = """Eres un analista financiero senior especializado en valoración de empresas por DCF.
Tu tarea es estimar tres tasas clave para el primer período de proyección de un modelo de flujo de caja libre en Excel,
utilizando TODO el contexto que se te proporciona.

CONTEXTO COMPLETO DEL CÁLCULO:
{context}

TASAS A ESTIMAR (en formato decimal, ej. 0.10 = 10%):
1. **forecast_ingresos**: tasa de crecimiento de los ingresos/ventas para el primer período de proyección.
2. **forecast_fde**: tasa de crecimiento del flujo de efectivo/libre (FDE/FCF) para el primer período de proyección.
3. **crecimiento_perpetuo**: tasa de crecimiento perpetuo a largo plazo del FDE.

INSTRUCCIONES:
- Usa los datos históricos de la empresa (CAGR, YoY) como punto de partida.
- Ajusta por el sector/industria y el país usando los datos de Damodaran, EMBI, inflación, tasa libre de riesgo y prima de riesgo.
- El crecimiento perpetuo debe ser conservador: típicamente cercano a la inflación o crecimiento del PIB del país, y siempre razonablemente menor al WACC/costo de capital.
- Si el sector es cíclico o volátil, suaviza las tasas de forecast hacia medias sectoriales.
- Justifica cada estimación en 1-2 oraciones en español, citando los datos clave que usaste.
- Proporciona un rango razonable (min, max) alrededor de cada estimación.

REGLAS ESTRICTAS:
- Responde EXCLUSIVAMENTE con un objeto JSON válido. NO agregues texto fuera del JSON.
- suggested_range usa decimales (0.10 = 10%).
- confidence debe ser "high", "medium" o "low".

ESTRUCTURA JSON EXACTA:
{{
  "forecast_ingresos": {{
    "value": 0.12,
    "rationale": "...",
    "confidence": "medium",
    "suggested_range": {{"min": 0.08, "max": 0.16}}
  }},
  "forecast_fde": {{
    "value": 0.10,
    "rationale": "...",
    "confidence": "medium",
    "suggested_range": {{"min": 0.06, "max": 0.14}}
  }},
  "crecimiento_perpetuo": {{
    "value": 0.025,
    "rationale": "...",
    "confidence": "high",
    "suggested_range": {{"min": 0.015, "max": 0.035}}
  }}
}}"""


RATE_LIMITS = {
    "forecast_ingresos": {"min": -0.50, "max": 1.00},
    "forecast_fde": {"min": -0.50, "max": 1.00},
    "crecimiento_perpetuo": {"min": -0.05, "max": 0.10},
}


def _extract_json(text: str) -> dict:
    """Extrae el primer objeto JSON válido de la respuesta."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            logger.warning(
                "[VALORA AI ESTIMATOR] Respuesta no parseable como JSON",
                exc_info=True,
            )
    return {}


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
            "maxOutputTokens": 2048,
            "topP": 0.8,
            "topK": 40,
        },
    }

    raw_text, model_used = await call_gemini(payload)
    if not raw_text:
        return None

    parsed = _extract_json(raw_text)
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
