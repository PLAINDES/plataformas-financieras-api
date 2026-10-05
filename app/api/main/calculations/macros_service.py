# app/api/main/calculations_router.py
import re
import time
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import (
    KAPITAL_DAMODARAN_CELL_MAP,
)
from app.models.main import TemplateComplement
from app.models.templates import MasterTemplate


VALORA_INPUT_ALIASES = {
    "fecha": "date",
    "pais": "country",
    "moneda": "currency",
    "industria": "sector",
    "tasa_libre_riesgo": "instrument",
    "anio_bono": "bono",
    "costo_deuda": "kd",
    "porcentaje_deuda": "debt",
    "tasa_impositiva": "tax",
    "devaluacion": "devaluation",
}


def _apply_valora_input_aliases(input_dict: dict) -> None:
    for target_key, source_key in VALORA_INPUT_ALIASES.items():
        if input_dict.get(target_key) not in (None, ""):
            continue

        source_value = input_dict.get(source_key)
        if source_value not in (None, ""):
            input_dict[target_key] = source_value


def get_default_or_latest_master_template(db: Session) -> MasterTemplate | None:
    t0 = time.perf_counter()
    template = (
        db.execute(
            select(MasterTemplate)
            .where(
                MasterTemplate.deleted_at.is_(None),
                MasterTemplate.is_default.is_(True),
            )
            .order_by(MasterTemplate.updated_at.desc(), MasterTemplate.id.desc())
        )
        .scalars()
        .first()
    )
    if template:
        print(f"[DB] get_default_or_latest_master_template (default): {time.perf_counter() - t0:.3f} seg", flush=True)
        return template

    template = (
        db.execute(
            select(MasterTemplate)
            .where(MasterTemplate.deleted_at.is_(None))
            .order_by(MasterTemplate.created_at.desc(), MasterTemplate.id.desc())
        )
        .scalars()
        .first()
    )
    print(f"[DB] get_default_or_latest_master_template (fallback): {time.perf_counter() - t0:.3f} seg", flush=True)
    return template


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", str(text)) if unicodedata.category(c) != "Mn"
    )


def _parse_es_date(value: object) -> tuple | None:
    """Parsea '31/12/2025' (tolerante a días imposibles como 31/09) a (año, mes, día)."""
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(value or ""))
    if not match:
        return None
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if not 1 <= month <= 12:
        return None
    return (year, month, max(1, min(day, 28)))


def _latest_embi_on_or_before(embi_data: list, date: str) -> dict | None:
    """Fila EMBI más reciente con fecha <= la del cálculo (cubre trimestres
    faltantes, p. ej. cálculo 31/12/2025 sin fila Q4 -> usa 31/09/2025)."""
    target = _parse_es_date(date)
    if not target:
        return None
    best: dict | None = None
    best_key: tuple | None = None
    for item in embi_data:
        if not isinstance(item, dict):
            continue
        key = _parse_es_date(item.get("fecha"))
        if key is None or key > target:
            continue
        if best_key is None or key > best_key:
            best, best_key = item, key
    return best


def get_default_master_template_key(db: Session, user_id=None) -> str | None:
    """S3 key de la plantilla maestra predeterminada.

    1) la marcada por el usuario que calcula; 2) la predeterminada global más
    reciente; 3) None (el web-service usa su fallback histórico: la última
    subida). Sin esto el web-service siempre elegía la última subida e
    ignoraba la selección PREDETERMINADA del admin.
    """
    from app.models.templates import MasterTemplate

    base = select(MasterTemplate).where(
        MasterTemplate.deleted_at.is_(None),
        MasterTemplate.s3_object_key.isnot(None),
    )
    if user_id is not None:
        try:
            own_id = int(user_id)
        except (TypeError, ValueError):
            own_id = None
        if own_id is not None:
            own = (
                db.execute(
                    base.where(
                        MasterTemplate.created_by_user_id == own_id,
                        MasterTemplate.is_default.is_(True),
                    ).order_by(MasterTemplate.updated_at.desc())
                )
                .scalars()
                .first()
            )
            if own is not None and own.s3_object_key:
                return own.s3_object_key
    glob = (
        db.execute(
            base.where(MasterTemplate.is_default.is_(True)).order_by(
                MasterTemplate.updated_at.desc()
            )
        )
        .scalars()
        .first()
    )
    return glob.s3_object_key if glob is not None else None


def _inject_macro_data_into_payload(db: Session, payload_data: dict) -> None:
    """
    Toma el payload proveniente del frontend, extrae los parámetros clave
    y busca en la BD los datos exactos para inyectarlos en el input.
    """
    if "inputs" not in payload_data or not payload_data["inputs"]:
        return

    t0 = time.perf_counter()
    # Trabajamos directamente sobre la referencia del último input para mutarlo
    latest_input = payload_data["inputs"][-1]
    _enrich_input_with_macros(db, latest_input)
    print(f"[DB] _inject_macro_data_into_payload total: {time.perf_counter() - t0:.3f} seg", flush=True)


def _enrich_input_with_macros(db: Session, input_dict: dict) -> None:
    """
    Enriquece un diccionario de input individual con datos de complementos de la BD.
    """
    t0 = time.perf_counter()
    _apply_valora_input_aliases(input_dict)

    date = str(input_dict.get("fecha", "")).strip()

    year = ""
    match = re.search(r"\d{4}", date)
    if match:
        year = match.group(0)

    country = input_dict.get("pais")
    industry = input_dict.get("industria")
    anio_bono = input_dict.get("anio_bono")

    # Helper interno para buscar en la BD
    def _fetch_complement_data(name: str) -> list:
        t_comp = time.perf_counter()
        comp = (
            db.execute(
                select(TemplateComplement)
                .where(
                    TemplateComplement.nombre == name,
                    TemplateComplement.deleted_at.is_(None),
                )
                .order_by(TemplateComplement.created_at.desc())
            )
            .scalars()
            .first()
        )
        print(f"[DB] _fetch_complement_data '{name}': {time.perf_counter() - t_comp:.3f} seg", flush=True)
        return comp.data if comp and isinstance(comp.data, list) else []

    if date:
        rf_data = _fetch_complement_data("rf")
        rf_match = next((item for item in rf_data if item.get("fecha") == date), None)

        if rf_match and anio_bono is not None:
            # Formateamos a 2 decimales
            try:
                formatted_anio = f"{float(anio_bono):.2f}"
            except ValueError:
                formatted_anio = str(anio_bono)

            valor_rf = rf_match.get(formatted_anio)
            if valor_rf is not None:
                input_dict["rf"] = {"fecha": rf_match.get("fecha"), "year": valor_rf}
            else:
                input_dict["rf"] = {}
        else:
            input_dict["rf"] = {}

        # EMBI: Extraemos solo la fecha y el país seleccionado.
        # La tabla es trimestral y puede no tener la fecha exacta del cálculo
        # (p. ej. 31/12/2025 sin fila Q4): se usa la fila más reciente
        # anterior o igual. Sin esto F11 conservaba el valor por defecto.
        embi_data = _fetch_complement_data("embi")
        embi_match = next(
            (item for item in embi_data if item.get("fecha") == date), None
        )
        if embi_match is None:
            embi_match = _latest_embi_on_or_before(embi_data, date)
        if embi_match is None and year:
            embi_match = next(
                (item for item in embi_data if str(item.get("fecha")) == year),
                None,
            )
        if embi_match and country:
            filtered_embi = {"fecha": embi_match.get("fecha")}
            country_norm = _strip_accents(country).lower()
            country_key = next(
                (
                    k
                    for k in embi_match.keys()
                    if _strip_accents(k).lower() == country_norm
                ),
                None,
            )
            if country_key:
                raw = embi_match.get(country_key)
                try:
                    num = float(str(raw).replace(",", "."))
                    # La tabla EMBI se carga en puntos básicos (p. ej. 132.68);
                    # la plantilla espera tanto por uno (0.013268).
                    value = num / 10000 if abs(num) > 1 else num
                except (TypeError, ValueError):
                    value = raw
                filtered_embi["country"] = value
            input_dict["embi"] = filtered_embi
        else:
            input_dict["embi"] = {}

    if year:
        riesgo_data = _fetch_complement_data("riesgo")
        riesgo_matches = [
            item for item in riesgo_data if str(item.get("fecha")) == year
        ]

        prima_data = _fetch_complement_data("prima")
        prima_match = next(
            (item for item in prima_data if str(item.get("fecha")) == year), None
        )
        input_dict["prima"] = prima_match if prima_match else {}

        tax_data = _fetch_complement_data("tax")
        tax_match = next(
            (item for item in tax_data if str(item.get("fecha")) == year), None
        )
        input_dict["tax"] = tax_match if tax_match else {}

        if industry:
            damo_data = _fetch_complement_data("damodaran")
            damo_match = next(
                (
                    item
                    for item in damo_data
                    if str(item.get("fecha")) == year
                    and item.get("industria") == industry
                ),
                None,
            )
            if damo_match:
                # Retenemos solo las llaves activas en el mapa
                allowed_keys = KAPITAL_DAMODARAN_CELL_MAP.keys()
                input_dict["damodaran"] = {
                    k: v for k, v in damo_match.items() if k in allowed_keys
                }
            else:
                input_dict["damodaran"] = {}

        if country:
            ir_data = _fetch_complement_data("ir")
            ir_payload = {"pais": country}  # Inicializamos con el nombre del país

            for item in ir_data:
                if (
                    str(item.get("pais")).lower() == country.lower()
                    and str(item.get("fecha")) == year
                ):
                    ir_payload["year"] = item.get("valor")
                    break
            input_dict["ir"] = ir_payload

        flattened_riesgo = {}
        if riesgo_matches:
            flattened_riesgo["fecha"] = year
            for idx, r_item in enumerate(riesgo_matches, start=1):
                flattened_riesgo[f"num{idx}_basis_spread"] = r_item.get("basis_spread")
                flattened_riesgo[f"num{idx}_max_deviation"] = r_item.get(
                    "max_deviation"
                )
                flattened_riesgo[f"num{idx}_min_deviation"] = r_item.get(
                    "min_deviation"
                )

        input_dict["riesgo"] = flattened_riesgo
    print(f"[DB] _enrich_input_with_macros total: {time.perf_counter() - t0:.3f} seg", flush=True)

