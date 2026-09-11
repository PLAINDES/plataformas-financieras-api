import logging
from typing import Any

from sqlalchemy.orm import Session

from app.services.valora.ai_estimator import estimate_valora_rates
from app.services.valora.ai_explainer import generate_valora_ai_analysis
from app.services.valora.macro_context import build_valora_macro_context

logger = logging.getLogger(__name__)

def _pct(x: Any) -> str | None:
    if x is None or not isinstance(x, (int, float)) or isinstance(x, bool):
        return None
    return f"{x * 100:.2f}%"


def _find_row_values(table: dict | None, target_labels: set[str]) -> list[float]:
    """Busca una fila por label (insensible a acentos/case) y extrae valores numéricos."""
    if not table or not isinstance(table, dict):
        return []
    rows = table.get("rows", [])
    if not isinstance(rows, list):
        return []

    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label", "")).strip()
        norm = (
            label.lower()
            .replace("á", "a")
            .replace("é", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ú", "u")
            .replace("ñ", "n")
        )
        if any(t in norm for t in target_labels):
            values = row.get("values", [])
            nums = []
            for v in values:
                if v is None:
                    continue
                try:
                    nums.append(float(v))
                except (ValueError, TypeError):
                    pass
            return nums
    return []


def _calculate_growth_rate(values: list[float]) -> float | None:
    """Calcula tasa de crecimiento promedio (CAGR) de una serie de valores."""
    clean = [v for v in values if v is not None and v != 0]
    if len(clean) < 2:
        return None
    first = clean[0]
    last = clean[-1]
    n = len(clean) - 1
    if first <= 0 or last <= 0 or n <= 0:
        return None
    try:
        cagr = (last / first) ** (1 / n) - 1
        return round(cagr, 4)
    except Exception:
        return None


def _calculate_yoy_growth(values: list[float]) -> float | None:
    """Calcula crecimiento año-a-año del último período."""
    clean = [v for v in values if v is not None and v != 0]
    if len(clean) < 2:
        return None
    last = clean[-1]
    prev = clean[-2]
    if prev <= 0:
        return None
    return round((last - prev) / prev, 4)


async def recommend_valora_from_payload(
    calculation_data: dict[str, Any], db: Session | None = None
) -> dict[str, Any]:
    """Recomienda tasas desde el cálculo nativo, sin leer ni escribir Excel."""
    inputs = calculation_data.get("inputs") or [calculation_data]
    source = inputs[0] if isinstance(inputs, list) and inputs else {}
    if not isinstance(source, dict):
        source = {}

    def values(table: Any, labels: set[str]) -> list[float]:
        return _find_row_values(table if isinstance(table, dict) else None, labels)

    revenue = values(source.get("results_table"), {"ventas", "ingresos", "ingreso", "revenue", "sales"})
    fde = values(source.get("results_table"), {"fce", "fcf", "flujo libre", "flujo de efectivo", "flujo de caja", "free cash"})
    if not fde:
        fde = values(source.get("balance_table"), {"fce", "fcf", "flujo libre", "flujo de efectivo", "flujo de caja", "free cash"})

    revenue_cagr = _calculate_growth_rate(revenue)
    fde_cagr = _calculate_growth_rate(fde)
    context = {
        "company_context": {
            "fecha": source.get("fecha") or source.get("date"),
            "pais": source.get("pais") or source.get("country"),
            "sector": source.get("sector") or source.get("industria") or source.get("industry"),
        },
        "financial_data": {
            "revenue_values": revenue,
            "revenue_cagr": revenue_cagr,
            "fde_values": fde,
            "fde_cagr": fde_cagr,
        },
    }
    if db is not None:
        context["macro_context"] = build_valora_macro_context(
            db, str(context["company_context"]["fecha"] or ""),
            str(context["company_context"]["pais"] or ""),
            str(context["company_context"]["sector"] or ""),
        )

    ai_result = await estimate_valora_rates(context)
    ai_rates = (ai_result or {}).get("rates", {})

    def recommendation(key: str, fallback: float | None) -> tuple[Any, str]:
        value = (ai_rates.get(key) or {}).get("value")
        return (value, "ai_estimation") if value is not None else (fallback, "financial_data_cagr" if fallback is not None else "empty")

    ing, ing_source = recommendation("forecast_ingresos", revenue_cagr)
    fde_rate, fde_source = recommendation("forecast_fde", fde_cagr)
    perp, perp_source = recommendation("crecimiento_perpetuo", 0.025)

    def rate(label: str, value: Any, source_name: str, key: str) -> dict[str, Any]:
        return {
            "label": label, "recommendation": value,
            "recommendation_source": source_name, "recommendation_pct": _pct(value),
            "ai_estimate": ai_rates.get(key),
        }

    result = {"file": None, "context": context["company_context"], "macro_context": context.get("macro_context", {}),
              "ai_estimation": {"used": ai_result is not None, "model_used": (ai_result or {}).get("model_used")},
              "rates": {
                  "forecast_ingresos_1er_periodo": rate("Tasa Forecast Ingresos 1er Periodo", ing, ing_source, "forecast_ingresos"),
                  "forecast_fde_1er_periodo": rate("Tasa Forecast FDE 1er Periodo", fde_rate, fde_source, "forecast_fde"),
                  "crecimiento_perpetuo": rate("Tasa de Crecimiento Perpetuo", perp, perp_source, "crecimiento_perpetuo"),
              }, "warnings": []}
    try:
        analysis = await generate_valora_ai_analysis(result)
        if analysis:
            result["ai_analysis"] = analysis
    except Exception:
        logger.warning("[VALORA RECOMMENDER] AI explanation skipped", exc_info=True)
    return result
