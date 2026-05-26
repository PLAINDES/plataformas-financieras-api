# app/api/main/calculations_router.py
import base64
import time
from pathlib import Path
from app.models.cms import Page
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import Browser
from app.core.constants import COUNTRY_LOCAL_CURRENCIES

async def _generate_calculation_images(data: dict, browser: Browser) -> list[str]:
    graphs_response = {
        "resultados_generales": None,
        "sensibilidad_general": None,
        "comparaciones": []
    }

    resultados = data.get("resultados", [])
    sensibilizaciones = data.get("sensibilizacion", [])
    inputs = data.get("inputs", [])

    if not resultados:
        return graphs_response

    # Determinar moneda local correcta basada en el país
    pais_input = inputs[0].get("pais", "") if inputs else ""
    moneda_default = inputs[0].get("moneda", "Local") if inputs else "Local"
    moneda_local = COUNTRY_LOCAL_CURRENCIES.get(pais_input, moneda_default)

    current_dir = Path(__file__).resolve().parent

    templates_dir = None
    for parent in [current_dir, *current_dir.parents]:
        candidate = parent / "html_templates"
        if candidate.exists():
            templates_dir = candidate
            break

        candidate = parent / "app" / "html_templates"
        if candidate.exists():
            templates_dir = candidate
            break

    if not templates_dir:
        raise FileNotFoundError(f"El directorio de plantillas no existe: buscado en {current_dir} y sus padres")

    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template_resultados = env.get_template("kapital_report.html")
    template_sens = env.get_template("kapital_sensibilidad.html")
    template_comp = env.get_template("kapital_comparacion.html")

    base_resultado = resultados[0]
    num_sens = len(sensibilizaciones)

    # Extraer el d_empresa base de dolares para usarlo como respaldo en moneda local
    base_d_empresa = base_resultado.get("empresa_dolares", {}).get("d_empresa", "0%")

    # CREAR CONTEXTO Y PÁGINA UNA SOLA VEZ
    context = await browser.new_context()
    page = await context.new_page()

    # ---------- IMAGEN 1: RESULTADOS GENERALES ----------
    cards_gen = []
    if "mercado_desarrollado" in base_resultado and base_resultado["mercado_desarrollado"].get("kd"):
        cards_gen.append(_build_card_dict("Mercado Desarrollado", base_resultado["mercado_desarrollado"]))
    if "mercado_emergente" in base_resultado and base_resultado["mercado_emergente"].get("kd"):
        cards_gen.append(_build_card_dict("Mercado Emergente", base_resultado["mercado_emergente"]))
    if "empresa_soles" in base_resultado and base_resultado["empresa_soles"].get("kd"):
        cards_gen.append(_build_card_dict(f"Tu Empresa ({moneda_local})", base_resultado["empresa_soles"], base_d_empresa))
    if "empresa_dolares" in base_resultado and base_resultado["empresa_dolares"].get("kd"):
        titulo_usd = "Tu Empresa (USD Ext)" if moneda_local == "USD" else "Tu Empresa (USD)"
        cards_gen.append(_build_card_dict(titulo_usd, base_resultado["empresa_dolares"]))

    html_gen = template_resultados.render(report_title="Resultados Generales", cards=cards_gen)
    graphs_response["resultados_generales"] = await _render_html_to_b64(page, html_gen, viewport_height=700, viewport_width=1700)

    # ---------- IMÁGENES DE SENSIBILIZACIÓN Y COMPARACIÓN ----------
    if num_sens > 0:
        # VISTA SENSIBILIZACIÓN
        sens_primera = sensibilizaciones[0]
        cards_sens = []

        # Mercado Desarrollado (Estático)
        if "mercado_desarrollado" in base_resultado and base_resultado["mercado_desarrollado"].get("kd"):
            cards_sens.append(_build_card_dict("Mercado Desarrollado", base_resultado["mercado_desarrollado"]))

        # Datos Sensibilizados
        if "mercado_emergente" in sens_primera and sens_primera["mercado_emergente"].get("kd"):
            cards_sens.append(_build_card_dict("Mercado Emergente (Sens)", sens_primera["mercado_emergente"]))
        if "empresa_soles" in sens_primera and sens_primera["empresa_soles"].get("kd"):
            cards_sens.append(_build_card_dict(f"Tu Empresa {moneda_local} (Sens)", sens_primera["empresa_soles"], base_d_empresa))
        if "empresa_dolares" in sens_primera and sens_primera["empresa_dolares"].get("kd"):
            titulo_usd_sens = "Tu Empresa USD Ext (Sens)" if moneda_local == "USD" else "Tu Empresa USD (Sens)"
            cards_sens.append(_build_card_dict(titulo_usd_sens, sens_primera["empresa_dolares"], base_d_empresa))

        html_sens = template_sens.render(
            report_title=f"Análisis de Sensibilidad (BOA: {sens_primera.get('boa', 'N/A')})",
            cards=cards_sens
        )
        graphs_response["sensibilidad_general"] = await _render_html_to_b64(page, html_sens, viewport_height=700, viewport_width=1700)

        # VISTA COMPARACIÓN
        for i, sens in enumerate(sensibilizaciones):

            # Construir datos para el Mercado Desarrollado estático
            dev_data = _build_card_dict("Mercado Desarrollado", base_resultado.get("mercado_desarrollado", {}))

            # Fila Original
            orig_cards = []
            if "mercado_emergente" in base_resultado and base_resultado["mercado_emergente"].get("kd"):
                orig_cards.append(_build_card_dict("Mercado Emergente", base_resultado["mercado_emergente"]))
            if "empresa_soles" in base_resultado and base_resultado["empresa_soles"].get("kd"):
                orig_cards.append(_build_card_dict(f"Tu Empresa ({moneda_local})", base_resultado["empresa_soles"], base_d_empresa))
            if "empresa_dolares" in base_resultado and base_resultado["empresa_dolares"].get("kd"):
                titulo_usd_sens = "Tu Empresa USD Ext (Sens)" if moneda_local == "USD" else "Tu Empresa USD (Sens)"
                orig_cards.append(_build_card_dict(titulo_usd_sens, base_resultado["empresa_dolares"], base_d_empresa))

            # Fila Sensibilizada
            sens_cards = []
            if "mercado_emergente" in sens and sens["mercado_emergente"].get("kd"):
                sens_cards.append(_build_card_dict("Mercado Emergente", sens["mercado_emergente"]))
            if "empresa_soles" in sens and sens["empresa_soles"].get("kd"):
                sens_cards.append(_build_card_dict(f"Tu Empresa ({moneda_local})", sens["empresa_soles"], base_d_empresa))
            if "empresa_dolares" in sens and sens["empresa_dolares"].get("kd"):
                titulo_usd_sens = "Tu Empresa USD Ext (Sens)" if moneda_local == "USD" else "Tu Empresa USD (Sens)"
                sens_cards.append(_build_card_dict(titulo_usd_sens, sens["empresa_dolares"], base_d_empresa))

            html_comp = template_comp.render(
                report_title=f"Comparación vs Sensibilización {i+1}",
                developed=dev_data["data"],
                boa_original=base_resultado.get("boa", "0.00"),
                original_cards=orig_cards,
                boa_sensibilizado=sens.get("boa", "0.00"),
                sens_cards=sens_cards
            )
            img_comp = await _render_html_to_b64(page, html_comp, viewport_height=950, viewport_width=1700)

            graphs_response["comparaciones"].append({
                "boa": float(sens.get("boa", 0.0)),
                "imagen": img_comp
            })
    return graphs_response

# Función para no repetir el código de captura
async def _render_html_to_b64(page: Page, html_content: str, viewport_height: int, viewport_width: int = 1200) -> str:
    # Solo cambiamos el tamaño del viewport, no recreamos la pestaña
    await page.set_viewport_size({"width": viewport_width, "height": viewport_height})

    # Inyectamos el HTML. La primera vez tomará ~1.7s, las siguientes será casi instantáneo
    await page.set_content(html_content, wait_until="load")

    screenshot_bytes = await page.screenshot(type="png", full_page=True)
    base64_encoded = base64.b64encode(screenshot_bytes).decode("utf-8")

    return f"data:image/png;base64,{base64_encoded}"

def _build_card_dict(title: str, raw_data: dict, fallback_d_empresa: str = "0%") -> dict:
    d_empresa_str = raw_data.get("d_empresa")

    # Aplicar valor de respaldo si d_empresa es nulo o está vacío
    if not d_empresa_str or str(d_empresa_str).strip() == "":
        d_empresa_str = fallback_d_empresa

    raw_pasivo = float(str(d_empresa_str).replace(",", ".").replace("%", "")) if d_empresa_str else 0
    raw_patrimonio = 100 - raw_pasivo

    min_perc = 25
    visual_pasivo = max(raw_pasivo, min_perc)
    visual_patrimonio = 100 - min_perc if raw_pasivo < min_perc else raw_patrimonio

    if raw_patrimonio < min_perc:
        visual_patrimonio = min_perc
        visual_pasivo = 100 - min_perc

    return {
        "title": title,
        "data": {
            "cppc": raw_data.get("cppc", "0%"),
            "kd": raw_data.get("kd", "0%"),
            "koa": raw_data.get("koa", "0%"),
            "kd_1_minus_t": raw_data.get("kd(1-t)", "0%"),
            "ke": raw_data.get("ke", "0%"),
            "visualPasivoPerc": visual_pasivo,
            "visualPatrimonioPerc": visual_patrimonio
        }
    }
