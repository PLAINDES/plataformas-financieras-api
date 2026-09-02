import json
import logging
import re
import unicodedata
from pathlib import Path

import pypdf

from app.services.valora.gemini_client import call_gemini

logger = logging.getLogger("uvicorn.error")

PROMPT_PATH = Path(__file__).parent / "prompts" / "pdf_to_template_prompt.txt"

# Cuentas exactas plantilla (para transformar respuesta Gemini a balance_table/results_table)
BALANCE_ORDER = [
    "Efectivo y Equivalentes al Efectivo",
    "Cuentas por Cobrar Comerciales",
    "Cuentas por Cobrar a Entidades Relacionadas",
    "Otras Cuentas por Cobrar",
    "Inventarios",
    "Otros activos no financieros",
    "Total Activos Corrientes",
    "Cuentas por Cobrar Comerciales y Otras Cuentas por Cobrar",
    "Inversiones Financieras e inmobiliarias",
    "Propiedades, Planta y Equipo",
    "Depreciación Acumulada*",
    "Activos Intangibles",
    "Otros activos no financieros",
    "Total Activos No Corrientes",
    "TOTAL ACTIVOS",
    "Obligaciones financieras",
    "Cuentas por Pagar Comerciales",
    "Cuentas por Pagar a Entidades Relacionadas",
    "Otras Cuentas por Pagar",
    "Otros pasivos",
    "Total Pasivos Corrientes",
    "Obligaciones financieras",
    "Cuentas por Pagar Comerciales y Otras Cuentas por Pagar",
    "Otros pasivos",
    "Total Pasivos No Corrientes",
    "TOTAL PASIVOS",
    "Capital",
    "Reserva legal y otras reservas",
    "Resultados Acumulados",
    "Otros",
    "TOTAL PATRIMONIO",
    "TOTAL PASIVOS Y PATRIMONIO",
]

RESULTS_ORDER = [
    "Ingresos de Actividades Ordinarias",
    "Costo de Ventas",
    "Utilidad Bruta",
    "Gastos de Ventas y Distribución",
    "Depreciación*",
    "Gastos de Administración",
    "Otros ingresos (gastos) netos",
    "Utilidad Operativa",
    "Ingresos financieros",
    "Gastos financieros",
    "Diferencia en cambio, neta",
    "Utilidad antes de impuesto a la renta",
    "Impuesto a la renta",
    "Utilidad neta",
]

# Mapping posiciones duplicadas (para labels únicos si es necesario)
# Primera Obligaciones financieras = corriente, segunda = no corriente -> mantenemos mismo label pero frontend distingue por posición


def _load_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"[VALORA PDF] No se pudo cargar prompt: {e}")
        return ""


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    from io import BytesIO

    reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    texts = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
            texts.append(f"--- PÁGINA {i+1} ---\n{t}")
        except Exception:
            continue
    full = "\n".join(texts)
    logger.info(f"[VALORA PDF] Texto completo conservado: {len(full)} chars")
    if len(full) > 300_000:
        logger.warning(
            "[VALORA PDF] Texto grande (%s chars); requiere procesamiento por bloques si excede el contexto del modelo",
            len(full),
        )
    return full


def _split_pdf_text(full_text: str, pages_per_chunk: int = 40, overlap: int = 2) -> list[str]:
    pages = re.split(r"(?=--- PÁGINA \d+ ---)", full_text)
    pages = [page for page in pages if page.strip()]
    step = max(1, pages_per_chunk - overlap)
    return ["\n".join(pages[i : i + pages_per_chunk]) for i in range(0, len(pages), step)]


def _filter_relevant_pages(full_text: str) -> str:
    """Keep financial-statement pages plus one neighboring page for continuity."""
    pages = full_text.split("--- PÁGINA")
    if len(pages) <= 2:
        return full_text
    keywords = (
        "balance general", "estado de situación financiera", "situación financiera",
        "estado de resultados", "estado de ganancias", "ingresos de actividades",
        "activos corrientes", "total activos", "total pasivos", "patrimonio",
    )
    relevant = set()
    for index, page in enumerate(pages):
        lowered = page.casefold()
        if any(keyword in lowered for keyword in keywords):
            relevant.update(range(max(0, index - 1), min(len(pages), index + 2)))
    if not relevant:
        return full_text
    selected = [page for index, page in enumerate(pages) if index in relevant]
    return "--- PÁGINA".join(selected)


def _merge_chunk_json(results: list[dict]) -> dict:
    merged: dict = {"status": "OK", "metadata": {}, "template": {}, "number_of_shares": {}}
    for result in results:
        metadata = result.get("metadata") or {}
        for key, value in metadata.items():
            if value not in (None, "", [], {}):
                if key == "periodos":
                    merged["metadata"][key] = sorted(
                        {*(merged["metadata"].get(key) or []), *value},
                        key=lambda year: int(year) if str(year).isdigit() else str(year),
                    )
                else:
                    merged["metadata"].setdefault(key, value)

        for section in ("balance_general", "estado_resultados"):
            target = merged["template"].setdefault(section, {})
            for account, values in (result.get("template", {}).get(section, {}) or {}).items():
                if isinstance(values, dict):
                    target.setdefault(account, {}).update(
                        {period: value for period, value in values.items() if value is not None}
                    )
                elif account not in target:
                    target[account] = values

        shares = result.get("number_of_shares") or {}
        if isinstance(shares, dict) and merged["number_of_shares"].get("value") is None:
            if shares.get("value") is not None:
                merged["number_of_shares"] = shares

        for key in ("mapping_detail", "unmapped_accounts", "warnings", "missing_information"):
            merged.setdefault(key, []).extend(result.get(key) or [])
        for period, validation in (result.get("validation") or {}).items():
            merged.setdefault("validation", {})[period] = validation

        if result.get("status") in {"REQUIERE_REVISION", "DOCUMENTO_INCOMPLETO"}:
            merged["status"] = result["status"]
    return merged


def _validate_tables(balance_table: dict, results_table: dict) -> dict:
    def number(value):
        try:
            return float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def checks(table: dict, definitions: list[tuple[str, list[int], int]]) -> dict:
        rows = table.get("rows", [])
        years = table.get("years", [])
        def value_at(row, index):
            values = row.get("values", [])
            return values[index] if index < len(values) else None
        output = {}
        for year_index, year in enumerate(years):
            year_checks = {}
            for name, source_indexes, total_index in definitions:
                if total_index >= len(rows) or any(i >= len(rows) for i in source_indexes):
                    continue
                expected = number(value_at(rows[total_index], year_index))
                actual = sum(number(value_at(rows[i], year_index)) for i in source_indexes)
                difference = actual - expected
                year_checks[name] = {
                    "actual": actual,
                    "expected": expected,
                    "difference": difference,
                    "balanced": abs(difference) <= max(0.01, abs(expected) * 0.01),
                }
            output[str(year)] = year_checks
        return output

    balance = checks(balance_table, [
        ("current_assets", [0, 1, 2, 3, 4, 5], 6),
        ("noncurrent_assets", [7, 8, 9, 11, 12], 13),
        ("total_assets", [6, 13], 14),
        ("current_liabilities", [15, 16, 17, 18, 19], 20),
        ("noncurrent_liabilities", [21, 22, 23], 24),
        ("total_liabilities", [20, 24], 25),
        ("equity", [26, 27, 28, 29], 30),
        ("liabilities_equity", [25, 30], 31),
        ("balance", [14], 31),
    ])
    results = checks(results_table, [
        ("gross_profit", [0, 1], 2),
        ("operating_profit", [2, 3, 5, 6], 7),
        ("pre_tax_profit", [7, 8, 9, 10], 11),
        ("net_profit", [11, 12], 13),
    ])
    failed = any(not check["balanced"] for group in (balance, results) for year in group.values() for check in year.values())
    return {"balance": balance, "results": results, "passed": not failed}


def _parse_gemini_json(raw_text: str) -> dict:
    text = raw_text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    try:
        Path("/tmp/gemini_valora_pdf_last.json").write_text(raw_text, encoding="utf-8")
    except Exception:
        pass
    def try_parse(t: str):
        return json.loads(t)
    try:
        return try_parse(text)
    except Exception as e:
        logger.warning(f"[VALORA PDF] JSON try 1 falló {e} | len={len(text)} preview 1300-1450: {text[1300:1450]!r}")
    # Algunos modelos devuelven años como claves sin comillas (2022: ...).
    # Normalizarlos mantiene recuperable el JSON sin alterar valores.
    normalized_keys = re.sub(r"([\{,]\s*)(\d{4})(\s*:)", r'\1"\2"\3', text)
    cleaned = re.sub(r",\s*([}\]])", r"\1", normalized_keys)
    try:
        return json.loads(cleaned)
    except Exception as e:
        logger.warning(f"[VALORA PDF] JSON try 2 falló {e}")
    cleaned2 = re.sub(r'"\s*\n\s*"', '",\n"', cleaned)
    try:
        return json.loads(cleaned2)
    except Exception as e:
        logger.warning(f"[VALORA PDF] JSON try 3 falló {e}")
    # Reparación truncamiento: intenta cerrar llaves/corchetes faltantes
    for attempt in [text, cleaned, cleaned2]:
        start = attempt.find("{")
        end = attempt.rfind("}")
        if start != -1 and end != -1:
            snippet = attempt[start : end + 1]
            # Si truncado sin cierre, intenta cerrar
            open_braces = snippet.count("{") - snippet.count("}")
            open_brackets = snippet.count("[") - snippet.count("]")
            if open_braces > 0 or open_brackets > 0:
                snippet += "}" * open_braces + "]" * open_brackets
                # Limpia coma final antes de cierre añadido
                snippet = re.sub(r",\s*([}\]])", r"\1", snippet)
            try:
                return json.loads(snippet)
            except Exception:
                continue
    logger.error(f"[VALORA PDF] JSON parse falló final | len={len(raw_text)} | around 1372: {text[1250:1550]!r}")
    raise ValueError(f"JSON de Gemini incompleto/truncado (len {len(raw_text)}). Reintenta o reduce PDF.")


def _transform_to_tables(gemini_data: dict) -> dict:
    """
    Transforma salida Gemini (spec 40) a formato FinancialTable que espera el frontend
    Soporta dos orientaciones: {label: {periodo: val}} y {periodo: {label: val}}
    """
    template = gemini_data.get("template", {})
    balance_src = template.get("balance_general", {})
    results_src = template.get("estado_resultados", {})

    metadata = gemini_data.get("metadata", {})
    periodos = metadata.get("periodos") or []
    if not periodos:
        # Intenta inferir
        for v in balance_src.values():
            if isinstance(v, dict):
                periodos = sorted([k for k in v.keys() if str(k).isdigit()])
                if periodos:
                    break
        if not periodos and balance_src and all(str(k).isdigit() for k in balance_src.keys()):
            periodos = sorted(balance_src.keys(), key=lambda x: int(str(x)))

    periodos = sorted({str(p) for p in periodos}, key=lambda p: int(p) if p.isdigit() else p)

    # Detecta orientación periodo->cuenta y transpone si necesario
    def normalize_src(src: dict) -> dict:
        if not src:
            return {}
        # Si keys son años
        if src and all(str(k).isdigit() for k in src.keys()):
            transposed: dict = {}
            for periodo, accounts in src.items():
                if isinstance(accounts, dict):
                    for label, val in accounts.items():
                        transposed.setdefault(label, {})[str(periodo)] = val
            return transposed
        return src

    balance_src = normalize_src(balance_src)
    results_src = normalize_src(results_src)

    def build_table(order: list[str], src: dict, title: str):
        aliases = {
            "Ingresos de Actividades Ordinarias": ("ventas netas", "ingresos netos", "ingresos operativos", "ingresos de actividades ordinarias", "ventas"),
            "Cuentas por Cobrar Comerciales": ("cuentas por cobrar comerciales neto", "cuentas por cobrar comerciales"),
            "Otras Cuentas por Cobrar": ("otras cuentas por cobrar neto", "otras cuentas por cobrar"),
            "Efectivo y Equivalentes al Efectivo": ("efectivo y equivalentes de efectivo", "efectivo y equivalentes al efectivo"),
            "Obligaciones financieras": ("obligaciones financieras", "pasivos financieros", "deuda financiera", "prestamos y pagares bancarios"),
            "Cuentas por Pagar Comerciales": ("cuentas por pagar comerciales", "cxp comerciales"),
            "Otras Cuentas por Pagar": ("otras cuentas por pagar", "otras cxp"),
            "Gastos de Administración": ("gastos administrativos", "gastos de administracion", "gastos generales"),
            "Gastos de Ventas y Distribución": ("gastos de ventas", "gastos de comercializacion", "gastos de distribucion"),
            "Cuentas por Cobrar a Entidades Relacionadas": ("cuentas por cobrar a partes relacionadas", "cuentas por cobrar entidades relacionadas"),
        }

        def key(value):
            value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().casefold()
            return re.sub(r"[^a-z0-9]+", " ", value).strip()

        rows = []
        for label in order:
            val = src.get(label)
            if val is None:
                for k, v in src.items():
                    if key(k) == key(label):
                        val = v
                        break
            if val is None:
                candidates = aliases.get(label, (key(label),))
                for k, v in src.items():
                    source_key = key(k)
                    if any(alias in source_key or source_key in alias for alias in candidates):
                        val = v
                        break
            if val is None:
                values = [None] * len(periodos) if periodos else [None]
            elif isinstance(val, dict):
                values = [val.get(p) if val.get(p) is not None else val.get(str(p)) for p in periodos]
                values = [v if v is not None else None for v in values]
            else:
                values = [None] * (len(periodos) - 1) + [val] if periodos else [val]
            rows.append({"label": label, "values": values})
        return {"title": title, "years": periodos, "rows": rows}

    balance_table = build_table(BALANCE_ORDER, balance_src, "BALANCE GENERAL")
    results_table = build_table(RESULTS_ORDER, results_src, "ESTADO DE RESULTADOS")

    number_of_shares = gemini_data.get("number_of_shares", {})
    # Si solo hay metadata, intenta derivar

    return {
        "balance_table": balance_table,
        "results_table": results_table,
        "number_of_shares": number_of_shares,
        "gemini_raw": gemini_data,
    }


async def pdf_to_template(pdf_bytes: bytes) -> dict:
    import asyncio

    pdf_text = extract_text_from_pdf(pdf_bytes)
    logger.info(f"[VALORA PDF] Texto extraído: {len(pdf_text)} chars, páginas aprox {pdf_text.count('--- PÁGINA')}")
    if not pdf_text.strip():
        raise ValueError("PDF sin texto extraíble")

    prompt = _load_prompt()
    logger.info(f"[VALORA PDF] Prompt cargado: {len(prompt)} chars")
    system_instruction = prompt + "\n\nIMPORTANTE: Responde ÚNICAMENTE con el JSON de la regla 40, sin texto adicional, sin markdown."
    logger.info("[VALORA PDF] Enviando a Gemini... (puede tardar 40-80s)")
    # Heartbeat cada 20s mientras Gemini procesa
    heartbeat_task = None
    async def heartbeat():
        for i in range(1, 10):
            await asyncio.sleep(20)
            logger.info(f"[VALORA PDF] ... IA procesando ({i*20}s) - esperando Gemini")

    heartbeat_task = asyncio.create_task(heartbeat())

    # Si el output es muy grande, prioriza template sobre mapping_detail
    compact_instruction = system_instruction + "\n\nPRIORIDAD OUTPUT: Si debes recortar por tokens, asegura template.balance_general y template.estado_resultados COMPLETOS para todos los periodos, y number_of_shares. mapping_detail puede resumirse a 5 ejemplos representativos."
    chunk_instruction = (
        "Extrae únicamente datos financieros encontrados en este bloque. "
        "Responde SOLO un JSON válido, sin markdown, usando exactamente esta estructura: "
        '{"metadata":{"empresa":""},"number_of_shares":null,"template":'
        '{"balance_general":{},"estado_resultados":{}}}. '
        "Las claves de año deben estar entre comillas. Omite mapping_detail, warnings, "
        "missing_information, validaciones y explicaciones. No inventes datos."
    )
    gemini_payload = {
        "contents": [
            {"role": "user", "parts": [{"text": compact_instruction + "\n\n--- PDF A ANALIZAR ---\n" + pdf_text}]}
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 30000,
            "topP": 0.8,
            "topK": 40,
        },
    }

    # Conserva todas las páginas: los años pueden aparecer en páginas
    # continuas sin repetir el título del estado financiero.
    chunks = _split_pdf_text(pdf_text) if len(pdf_text) > 300_000 else [pdf_text]
    chunk_results = []
    model_used = None

    async def process_chunk(index: int, chunk: str) -> tuple[int, dict | None, str | None]:
        logger.info("[VALORA PDF] Procesando bloque %s/%s", index, len(chunks))
        chunk_payload = {
            **gemini_payload,
            "contents": [{
                "role": "user",
                "parts": [{"text": compact_instruction + "\n\n--- PDF A ANALIZAR ---\n" + chunk}],
            }],
        }
        chunk_raw, chunk_model = await call_gemini(chunk_payload)
        if chunk_raw:
            try:
                return index, _parse_gemini_json(chunk_raw), chunk_model
            except ValueError:
                logger.warning(
                    "[VALORA PDF] Bloque %s inválido; reintentando en formato compacto",
                    index,
                )
                retry_instruction = (
                    "Extrae SOLO datos financieros presentes en este bloque. "
                    "Responde un único JSON válido, sin markdown, con esta forma: "
                    '{"metadata":{"empresa":""},"number_of_shares":null,'
                    '"template":{"balance_general":{},"estado_resultados":{}}}. '
                    "Usa claves de año entre comillas. Omite mapping_detail, warnings, "
                    "missing_information, validaciones y cuentas no financieras. "
                    "No inventes datos ni incluyas explicaciones."
                )
                retry_payload = {
                    "contents": [{
                        "role": "user",
                        "parts": [{"text": retry_instruction + "\n\n--- BLOQUE ---\n" + chunk}],
                    }],
                    "generationConfig": {
                        "temperature": 0,
                        "maxOutputTokens": 50000,
                        "topP": 0.8,
                        "topK": 40,
                    },
                }
                retry_raw, retry_model = await call_gemini(retry_payload)
                if retry_raw:
                    try:
                        return index, _parse_gemini_json(retry_raw), retry_model
                    except ValueError:
                        logger.error("[VALORA PDF] Reintento inválido para bloque %s", index)
        return index, None, chunk_model

    if len(chunks) > 1:
        # Concurrencia conservadora para evitar respuestas truncadas y límites de API.
        semaphore = asyncio.Semaphore(4)

        async def limited(index: int, chunk: str):
            async with semaphore:
                return await process_chunk(index, chunk)

        results = await asyncio.gather(
            *(limited(index, chunk) for index, chunk in enumerate(chunks, start=1))
        )
        for _, result, chunk_model in sorted(results, key=lambda item: item[0]):
            if result:
                chunk_results.append(result)
            model_used = model_used or chunk_model

    if len(chunks) > 1:
        if not chunk_results:
            heartbeat_task.cancel()
            raise RuntimeError("Gemini no procesó ningún bloque del PDF")
        parsed = _merge_chunk_json(chunk_results)
        transformed = _transform_to_tables(parsed)
        validation = _validate_tables(transformed["balance_table"], transformed["results_table"])
        if not validation["passed"]:
            parsed["status"] = "REQUIERE_REVISION"
        heartbeat_task.cancel()
        return {
            "status": parsed.get("status", "OK"),
            "metadata": parsed.get("metadata", {}),
            "number_of_shares": transformed["number_of_shares"],
            "balance_table": transformed["balance_table"],
            "results_table": transformed["results_table"],
            "mapping_detail": parsed.get("mapping_detail", []),
            "unmapped_accounts": parsed.get("unmapped_accounts", []),
            "warnings": parsed.get("warnings", []),
            "missing_information": parsed.get("missing_information", []),
            "validation": validation,
            "model_used": model_used,
        }

    raw_text, model_used = await call_gemini(gemini_payload)
    # Detecta truncamiento por MAX_TOKENS y reintenta con prompt ultra-compacto
    # gemini_client ya loguea finishReason, pero revisamos len vs esperado
    if raw_text and len(raw_text) < 3000:
        # Muy corto para template completo → probablemente truncado/malformado, reintenta una vez
        logger.warning(f"[VALORA PDF] Respuesta corta ({len(raw_text)}), reintentando con prompt compacto...")
        compact2 = "Responde SOLO JSON regla 40 con template completo, metadata y number_of_shares. Omite mapping_detail/unmapped/warnings/validation para ahorrar tokens."
        retry_payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt[:5000] + "\n" + compact2 + "\n\nPDF:\n" + pdf_text}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 30000,
                "topP": 0.8,
                "topK": 40,
            },
        }
        raw2, model2 = await call_gemini(retry_payload)
        if raw2 and len(raw2) > len(raw_text):
            logger.info(f"[VALORA PDF] Retry éxito len={len(raw2)} vs {len(raw_text)}")
            raw_text, model_used = raw2, model2

    if heartbeat_task:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
    logger.info(f"[VALORA PDF] Gemini respondió: model={model_used} len={len(raw_text) if raw_text else 0}")
    if not raw_text:
        raise RuntimeError("Gemini no respondió")

    parsed = _parse_gemini_json(raw_text)
    transformed = _transform_to_tables(parsed)
    validation = _validate_tables(transformed["balance_table"], transformed["results_table"])
    if not validation["passed"]:
        parsed["status"] = "REQUIERE_REVISION"

    return {
        "status": parsed.get("status", "OK"),
        "metadata": parsed.get("metadata", {}),
        "number_of_shares": transformed["number_of_shares"],
        "balance_table": transformed["balance_table"],
        "results_table": transformed["results_table"],
        "mapping_detail": parsed.get("mapping_detail", []),
        "unmapped_accounts": parsed.get("unmapped_accounts", []),
        "warnings": parsed.get("warnings", []),
        "missing_information": parsed.get("missing_information", []),
        "validation": validation,
        "model_used": model_used,
    }
