import json
import logging
import statistics
from typing import Any

from sqlalchemy.orm import Session

from app.api.main.calculations.formatters import _first_matrix_value
from app.services.onedrive.service import get_onedrive_service
from app.services.valora.ai_estimator import estimate_valora_rates
from app.services.valora.ai_explainer import generate_valora_ai_analysis
from app.services.valora.macro_context import build_valora_macro_context

logger = logging.getLogger(__name__)

# Celdas de contexto del usuario en "Plantilla Usuario"
_VALORA_CONTEXT_INPUTS = {
    "fecha": ("Plantilla Usuario", "C2"),
    "pais": ("Plantilla Usuario", "C3"),
    "sector": ("Plantilla Usuario", "C5"),
}

# Celdas de la plantilla Valora (referencias estáticas)
_VALORA_RATES = {
    "forecast_ingresos": ("Plantilla Usuario", "C13"),
    "forecast_fde": ("Plantilla Usuario", "C14"),
    "crecimiento_perpetuo": ("Plantilla Usuario", "C15"),
}

# Drivers y fuentes del modelo
_DRIVERS = {
    "model_source_ingresos": ("Proyección", "M91"),
    "model_source_fde": ("Integrado", "M10"),
    "inflacion": ("Proyección", "F81"),
    "wacc": ("Conceptos", "C23"),
}

_HISTORICAL_RANGES = {
    "historico_ingresos": ("Proyección", "F91:L91"),
    "historico_fde": ("Integrado", "F10:L10"),
}


async def _read_single_cell(
    service, item_id: str, sheet: str, cell: str, session_id: str | None
) -> tuple[Any, str | None]:
    """Lee una celda y devuelve (valor, fórmula)."""
    try:
        cell_data = await service.read_excel_cell(
            item_id, sheet, cell, session_id=session_id
        )
        return _parse_cell_value(cell_data)
    except Exception as e:
        logger.warning(
            f"[VALORA RECOMMENDER] Failed to read {sheet}!{cell}: {e}", exc_info=True
        )
        return None, None


def _parse_cell_value(cell_data: dict) -> tuple[Any, str | None]:
    """Extrae valor parseado y fórmula cruda de la respuesta de Graph API."""
    text = _first_matrix_value(cell_data.get("text"))
    formula = _first_matrix_value(cell_data.get("formulas"))
    value: Any = None

    if text is not None and str(text).strip() != "":
        raw = str(text).strip()
        if raw.lower() == "true":
            value = True
        elif raw.lower() == "false":
            value = False
        else:
            try:
                value = float(raw)
            except ValueError:
                value = raw
    return value, formula


def _pct(x: Any) -> str | None:
    if x is None or not isinstance(x, (int, float)) or isinstance(x, bool):
        return None
    return f"{x * 100:.2f}%"


def _stats(points: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [p["value"] for p in points]
    if not vals:
        return {"count": 0}
    result: dict[str, Any] = {
        "count": len(vals),
        "mean": sum(vals) / len(vals),
        "median": statistics.median(vals),
        "min": min(vals),
        "max": max(vals),
    }
    result["stdev"] = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return result


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


async def _read_range(
    service, item_id: str, sheet: str, cell_range: str, session_id: str | None
) -> list[dict[str, Any]]:
    """Lee un rango de celdas y extrae solo los valores numéricos."""
    try:
        cell_data = await service.read_excel_cell(
            item_id, sheet, cell_range, session_id=session_id
        )
        values = cell_data.get("values")
        out: list[dict[str, Any]] = []
        if isinstance(values, list):
            for row in values:
                if isinstance(row, list):
                    for val in row:
                        if val is not None:
                            try:
                                num = float(val)
                                out.append({"cell": f"{sheet}!{cell_range}", "value": num})
                            except (ValueError, TypeError):
                                pass
        logger.info(
            f"[VALORA RECOMMENDER] Range {sheet}!{cell_range} read: {len(out)} numeric values"
        )
        return out
    except Exception as e:
        logger.warning(
            f"[VALORA RECOMMENDER] Failed to read range {sheet}!{cell_range}: {e}",
            exc_info=True,
        )
        return []


async def _write_rate_to_excel(
    service,
    item_id: str,
    sheet: str,
    cell: str,
    value: float,
    session_id: str | None,
) -> bool:
    """Escribe un valor en una celda de Excel, intentando con y sin sesión."""
    try:
        await service.update_excel_cell(
            item_id, sheet, cell, value, session_id=session_id
        )
        logger.info(f"[VALORA RECOMMENDER] Escrito {sheet}!{cell} = {value}")
        return True
    except Exception as e:
        logger.warning(
            f"[VALORA RECOMMENDER] Fallo escritura con session={session_id}: {e}"
        )
        try:
            await service.update_excel_cell(
                item_id, sheet, cell, value, session_id=None
            )
            logger.info(f"[VALORA RECOMMENDER] Escrito {sheet}!{cell} = {value} (sin sesión)")
            return True
        except Exception as e2:
            logger.error(
                f"[VALORA RECOMMENDER] Fallo escritura sin sesión {sheet}!{cell}: {e2}",
                exc_info=True,
            )
            return False


def _recommend_or_fallback(
    key: str, cell_value: Any, hist_stats: dict[str, Any], calc_growth: float | None
) -> tuple[Any, str]:
    if cell_value is not None:
        return cell_value, "excel_cache"
    if calc_growth is not None:
        return calc_growth, "financial_data_cagr"
    mean = hist_stats.get("mean")
    if mean is not None:
        return mean, "historical_mean"
    return None, "empty"


def _normalize_rate_for_context(value: Any) -> float | None:
    """
    Normaliza una tasa leída del Excel a escala decimal.
    Si el valor es > 1 (escala directa tipo 12 para 12%), lo divide por 100.
    """
    if value is None:
        return None
    try:
        num = float(value)
    except (ValueError, TypeError):
        return None
    if abs(num) > 1:
        return num / 100
    return num


async def read_valora_recommendations(
    item_id: str,
    session_id: str | None = None,
    calculation_data: dict[str, Any] | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """
    Lee la plantilla Valora activa, estima las tasas con IA usando todo el contexto
    (sector, país, históricos, datos macro/Damodaran) y escribe los valores en el Excel.

    Si la IA falla, mantiene el fallback determinista anterior.
    """
    service = get_onedrive_service()
    logger.info(
        f"[VALORA RECOMMENDER] Starting for item={item_id} session={session_id}"
    )

    # Extraer inputs del cálculo como fallback ante lecturas de Excel
    calc_inputs = (calculation_data or {}).get("inputs", [{}])[0] if calculation_data else {}
    if not isinstance(calc_inputs, dict):
        calc_inputs = {}

    def _context_fallback(key: str, excel_value: Any, aliases: list[str] | None = None) -> Any:
        if excel_value not in (None, ""):
            return excel_value
        for alias in [key] + (aliases or []):
            val = calc_inputs.get(alias)
            if val not in (None, ""):
                return val
        return None

    # 1. Leer contexto del usuario (fecha, país, sector)
    context_inputs: dict[str, Any] = {}
    for key, (sheet, cell) in _VALORA_CONTEXT_INPUTS.items():
        value, formula = await _read_single_cell(service, item_id, sheet, cell, session_id)
        context_inputs[key] = {
            "value": value,
            "formula": formula,
            "cell": f"{sheet}!{cell}",
        }
        logger.info(f"[VALORA RECOMMENDER] Context {key} = {value}")

    fecha = _context_fallback(
        "fecha", context_inputs.get("fecha", {}).get("value"), ["date"]
    )
    pais = _context_fallback(
        "pais", context_inputs.get("pais", {}).get("value"), ["country"]
    )
    sector = _context_fallback(
        "sector", context_inputs.get("sector", {}).get("value"), ["industria", "industry"]
    )

    # 2. Tasas principales actuales
    rates_data: dict[str, dict[str, Any]] = {}
    fallback_sources = {
        "forecast_ingresos": ("Proyección", "M91"),
        "forecast_fde": ("Integrado", "M10"),
        "crecimiento_perpetuo": ("Proyección", "F81"),
    }
    for key, (sheet, cell) in _VALORA_RATES.items():
        try:
            cell_data = await service.read_excel_cell(
                item_id, sheet, cell, session_id=session_id
            )
            value, formula = _parse_cell_value(cell_data)
            # Si la celda de salida está vacía, leer la celda fuente del modelo
            if value is None and key in fallback_sources:
                fb_sheet, fb_cell = fallback_sources[key]
                logger.info(
                    f"[VALORA RECOMMENDER] {key} vacío en {sheet}!{cell}, "
                    f"intentando fallback {fb_sheet}!{fb_cell}"
                )
                try:
                    fb_data = await service.read_excel_cell(
                        item_id, fb_sheet, fb_cell, session_id=session_id
                    )
                    fb_value, fb_formula = _parse_cell_value(fb_data)
                    if fb_value is not None:
                        value = fb_value
                        formula = fb_formula
                        logger.info(
                            f"[VALORA RECOMMENDER] {key} fallback exitoso: {value}"
                        )
                except Exception as fb_e:
                    logger.warning(
                        f"[VALORA RECOMMENDER] Fallback fallido para {key}: {fb_e}"
                    )
            rates_data[key] = {
                "value": value,
                "formula": formula,
                "cell": f"{sheet}!{cell}",
            }
            logger.info(f"[VALORA RECOMMENDER] {key} = {value} (formula={formula})")
        except Exception as e:
            logger.warning(
                f"[VALORA RECOMMENDER] Failed to read {key} ({sheet}!{cell}): {e}",
                exc_info=True,
            )
            rates_data[key] = {"value": None, "formula": None, "cell": f"{sheet}!{cell}"}

    # 3. Drivers de fórmula (celdas fuente)
    drivers_data: dict[str, dict[str, Any]] = {}
    for key, (sheet, cell) in _DRIVERS.items():
        try:
            cell_data = await service.read_excel_cell(
                item_id, sheet, cell, session_id=session_id
            )
            value, formula = _parse_cell_value(cell_data)
            drivers_data[key] = {
                "value": value,
                "formula": formula,
                "cell": f"{sheet}!{cell}",
            }
            logger.info(
                f"[VALORA RECOMMENDER] Driver {key} = {value} (formula={formula})"
            )
        except Exception as e:
            logger.warning(
                f"[VALORA RECOMMENDER] Failed to read driver {key}: {e}",
                exc_info=True,
            )
            drivers_data[key] = {"value": None, "formula": None, "cell": f"{sheet}!{cell}"}

    # 4. Históricos desde Excel
    hist_ing = await _read_range(
        service, item_id, *_HISTORICAL_RANGES["historico_ingresos"], session_id
    )
    hist_fde = await _read_range(
        service, item_id, *_HISTORICAL_RANGES["historico_fde"], session_id
    )

    stats_ing = _stats(hist_ing)
    stats_fde = _stats(hist_fde)
    logger.info(f"[VALORA RECOMMENDER] Ingresos stats: {stats_ing}")
    logger.info(f"[VALORA RECOMMENDER] FDE stats: {stats_fde}")

    # 5. Fallback a datos financieros del usuario
    balance_table = calc_inputs.get("balance_table")
    results_table = calc_inputs.get("results_table")

    revenue_values = _find_row_values(
        results_table, {"ventas", "ingresos", "ingreso", "revenue", "sales"}
    )

    fde_labels = {
        "fce", "fcf", "flujo libre", "flujo de efectivo", "flujo de caja",
        "flujo de caja operativo", "flujo caja operativo", "free cash", "cash flow",
        "fco", "operating cash flow", "cash flow operativo", "fco"
    }
    fde_values = _find_row_values(results_table, fde_labels) or _find_row_values(balance_table, fde_labels)

    fde_proxy_source = "direct"
    if not fde_values:
        net_income = _find_row_values(
            results_table,
            {"utilidad neta", "beneficio neto", "ganancia neta", "resultado del ejercicio", "net income", "net profit"},
        )
        if net_income:
            fde_values = [v * 0.7 for v in net_income]
            fde_proxy_source = "net_income_proxy_70%"
            logger.info(
                f"[VALORA RECOMMENDER] FDE no encontrado directamente. "
                f"Usando proxy desde Utilidad Neta (70%): {fde_values}"
            )

    calc_revenue_growth = _calculate_growth_rate(revenue_values)
    calc_revenue_yoy = _calculate_yoy_growth(revenue_values)
    calc_fde_growth = _calculate_growth_rate(fde_values)
    calc_fde_yoy = _calculate_yoy_growth(fde_values)

    logger.info(
        f"[VALORA RECOMMENDER] Datos financieros calculados: "
        f"revenue_cagr={calc_revenue_growth}, revenue_yoy={calc_revenue_yoy}, "
        f"fde_cagr={calc_fde_growth}, fde_yoy={calc_fde_yoy}, "
        f"fde_source={fde_proxy_source}"
    )

    # 6. Contexto macro/sectorial desde la configuración del sistema
    macro_context: dict[str, Any] = {}
    if db is not None:
        try:
            macro_context = build_valora_macro_context(
                db,
                date_str=str(fecha) if fecha else None,
                country=str(pais) if pais else None,
                industry=str(sector) if sector else None,
            )
        except Exception as e:
            logger.warning(
                f"[VALORA RECOMMENDER] Error construyendo macro context: {e}",
                exc_info=True,
            )

    # 7. Estimación con IA usando TODO el contexto
    ai_estimate_result: dict[str, Any] | None = None
    ai_rates: dict[str, dict[str, Any]] = {}
    ai_error: str | None = None

    ai_context = {
        "company_context": {
            "fecha": fecha,
            "pais": pais,
            "sector": sector,
        },
        "current_excel_rates": {
            k: {
                "raw_value": v.get("value"),
                "normalized_value": _normalize_rate_for_context(v.get("value")),
                "cell": v.get("cell"),
                "formula": v.get("formula"),
            }
            for k, v in rates_data.items()
        },
        "historical_excel": {
            "ingresos": {"values": hist_ing, "stats": stats_ing},
            "fde": {"values": hist_fde, "stats": stats_fde},
        },
        "financial_data": {
            "revenue_values": revenue_values,
            "revenue_cagr": calc_revenue_growth,
            "revenue_yoy": calc_revenue_yoy,
            "fde_values": fde_values,
            "fde_cagr": calc_fde_growth,
            "fde_yoy": calc_fde_yoy,
            "fde_source": fde_proxy_source,
        },
        "inflation_driver": drivers_data.get("inflacion"),
        "wacc_driver": drivers_data.get("wacc"),
        "macro_context": macro_context,
    }

    try:
        ai_estimate_result = await estimate_valora_rates(ai_context)
        if ai_estimate_result:
            ai_rates = ai_estimate_result.get("rates", {})
            logger.info(f"[VALORA RECOMMENDER] IA estimó tasas: {ai_rates}")
        else:
            ai_error = "La IA no devolvió una estimación válida."
    except Exception as e:
        ai_error = str(e)
        logger.warning(
            f"[VALORA RECOMMENDER] Error en estimación IA: {e}", exc_info=True
        )

    # 8. Escribir estimaciones IA en el Excel
    written_rates: dict[str, bool] = {}
    if ai_estimate_result:
        for key, (sheet, cell) in _VALORA_RATES.items():
            ai_entry = ai_rates.get(key) or {}
            ai_value = ai_entry.get("value")
            if ai_value is not None:
                # La plantilla Valora espera las tasas en escala directa
                # (ej. 12 para 12%), mientras que la IA devuelve decimales (0.12).
                excel_value = ai_value * 100
                success = await _write_rate_to_excel(
                    service, item_id, sheet, cell, excel_value, session_id
                )
                written_rates[key] = success
            else:
                written_rates[key] = False

        # Forzar recálculo para que el modelo use las nuevas tasas
        try:
            await service.force_calculate_excel(item_id, session_id=session_id)
            logger.info("[VALORA RECOMMENDER] Recálculo forzado después de escritura IA")
        except Exception as e:
            logger.warning(
                f"[VALORA RECOMMENDER] Error forzando recálculo: {e}", exc_info=True
            )

        # Re-leer las celdas para confirmar valores finales
        for key, (sheet, cell) in _VALORA_RATES.items():
            try:
                value, formula = await _read_single_cell(
                    service, item_id, sheet, cell, session_id
                )
                if value is not None:
                    rates_data[key]["value"] = value
                    rates_data[key]["formula"] = formula
                    logger.info(
                        f"[VALORA RECOMMENDER] {key} re-leído tras escritura: {value}"
                    )
            except Exception as e:
                logger.warning(
                    f"[VALORA RECOMMENDER] No se pudo re-leer {key} tras escritura: {e}"
                )

    # 9. Determinar recomendaciones finales
    rec_ing, source_ing = _recommend_or_fallback(
        "forecast_ingresos",
        rates_data.get("forecast_ingresos", {}).get("value"),
        stats_ing,
        calc_revenue_growth,
    )
    rec_fde, source_fde = _recommend_or_fallback(
        "forecast_fde",
        rates_data.get("forecast_fde", {}).get("value"),
        stats_fde,
        calc_fde_growth,
    )

    rec_perp = rates_data.get("crecimiento_perpetuo", {}).get("value")
    source_perp = "excel_cache" if rec_perp is not None else "empty"
    if rec_perp is None:
        inflacion = drivers_data.get("inflacion", {}).get("value")
        if inflacion is not None and isinstance(inflacion, (int, float)):
            rec_perp = inflacion
            source_perp = "inflation_driver"
        else:
            rec_perp = 0.025
            source_perp = "default_2.5%"

    # Si la IA escribió valores, actualizar la fuente a ai_estimation
    ai_metadata: dict[str, Any] = {
        "used": ai_estimate_result is not None,
        "model_used": ai_estimate_result.get("model_used") if ai_estimate_result else None,
        "error": ai_error,
        "written_rates": written_rates,
    }

    if ai_estimate_result:
        for key in ("forecast_ingresos", "forecast_fde", "crecimiento_perpetuo"):
            if written_rates.get(key) and ai_rates.get(key, {}).get("value") is not None:
                if key == "forecast_ingresos":
                    rec_ing = ai_rates[key]["value"]
                    source_ing = "ai_estimation"
                elif key == "forecast_fde":
                    rec_fde = ai_rates[key]["value"]
                    source_fde = "ai_estimation"
                elif key == "crecimiento_perpetuo":
                    rec_perp = ai_rates[key]["value"]
                    source_perp = "ai_estimation"

    # 10. Armar resultado
    result: dict[str, Any] = {
        "file": item_id,
        "context": {
            "fecha": context_inputs.get("fecha"),
            "pais": context_inputs.get("pais"),
            "sector": context_inputs.get("sector"),
        },
        "macro_context": macro_context,
        "ai_estimation": ai_metadata,
        "rates": {
            "forecast_ingresos_1er_periodo": {
                "label": "Tasa Forecast Ingresos 1er Periodo",
                "recommendation": rec_ing,
                "recommendation_source": source_ing,
                "recommendation_pct": _pct(rec_ing),
                "output_cell": "Plantilla Usuario!C13",
                "output_formula": rates_data.get("forecast_ingresos", {}).get("formula"),
                "model_source": "Proyección!M91",
                "historical_driver": hist_ing,
                "historical_diagnostics": stats_ing,
                "ai_estimate": ai_rates.get("forecast_ingresos"),
                "financial_data": {
                    "revenue_values": revenue_values,
                    "calculated_cagr": calc_revenue_growth,
                    "calculated_yoy": calc_revenue_yoy,
                },
            },
            "forecast_fde_1er_periodo": {
                "label": "Tasa Forecast FDE 1er Periodo",
                "recommendation": rec_fde,
                "recommendation_source": source_fde,
                "recommendation_pct": _pct(rec_fde),
                "output_cell": "Plantilla Usuario!C14",
                "output_formula": rates_data.get("forecast_fde", {}).get("formula"),
                "model_source": "Integrado!M10",
                "historical_driver": hist_fde,
                "historical_diagnostics": stats_fde,
                "ai_estimate": ai_rates.get("forecast_fde"),
                "financial_data": {
                    "fde_values": fde_values,
                    "calculated_cagr": calc_fde_growth,
                    "calculated_yoy": calc_fde_yoy,
                    "fde_source": fde_proxy_source,
                },
            },
            "crecimiento_perpetuo": {
                "label": "Tasa de Crecimiento Perpetuo",
                "recommendation": rec_perp,
                "recommendation_source": source_perp,
                "recommendation_pct": _pct(rec_perp),
                "output_cell": "Plantilla Usuario!C15",
                "output_formula": rates_data.get("crecimiento_perpetuo", {}).get("formula"),
                "model_source": "Proyección!F81",
                "inflation_driver": drivers_data.get("inflacion"),
                "ai_estimate": ai_rates.get("crecimiento_perpetuo"),
            },
        },
        "warnings": [],
        "note": (
            "Las tasas fueron estimadas por IA usando el contexto completo del cálculo "
            "(sector, país, históricos y datos macro de configuración) y escritas directamente "
            "en el Excel. Si la IA no estuvo disponible, se usó el fallback determinista."
        ),
    }

    # 11. Validaciones / warnings
    if rec_ing is None:
        result["warnings"].append(
            "No se pudo obtener ni calcular la tasa de forecast de ingresos. "
            "Verifica que los estados financieros tengan datos de ventas/ingresos."
        )
    if rec_fde is None:
        result["warnings"].append(
            "No se pudo obtener ni calcular la tasa de forecast de FDE. "
            "Verifica que los estados financieros tengan datos de flujo de efectivo."
        )
    if source_perp == "default_2.5%":
        result["warnings"].append(
            "Se usó un valor default de 2.5% para crecimiento perpetuo. "
            "Considera ajustarlo según la inflación de tu país."
        )
    if ai_error:
        result["warnings"].append(f"Estimación IA omitida: {ai_error}")

    # 12. Análisis IA explicador (opcional)
    try:
        ai_analysis = await generate_valora_ai_analysis(result)
        if ai_analysis:
            result["ai_analysis"] = ai_analysis
    except Exception as e:
        logger.warning(
            f"[VALORA RECOMMENDER] Análisis IA omitido: {e}", exc_info=True
        )

    logger.info(f"[VALORA RECOMMENDER] Completed. Warnings: {result['warnings']}")
    return result
