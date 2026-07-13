import datetime
import json
import logging
import os
import random
import threading
import time
import uuid

import pandas as pd
import requests

os.environ["YF_USER_AGENT"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

_YF_SESSION = requests.Session()
_YF_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
})

import yfinance as yf
yf.set_tz_cache_location("/tmp/yfinance_cache")

from app.db.database import SessionLocal
from app.models.main import TemplateComplement

logger = logging.getLogger(__name__)

def _delay(seconds: float = 1.0):
    time.sleep(seconds + random.uniform(0, 0.5))

JOBS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "boa_jobs.json",
)
_jobs_lock = threading.Lock()
_jobs_cache: dict = {}
_running_jobs: dict[str, threading.Event] = {}


def _read_jobs() -> dict:
    if not os.path.exists(JOBS_PATH):
        return {}
    try:
        with open(JOBS_PATH) as f:
            data = json.load(f)
        _jobs_cache.clear()
        _jobs_cache.update(data)
        return data
    except Exception as exc:
        logger.warning(f"Error leyendo {JOBS_PATH}: {exc}")
        if _jobs_cache:
            logger.info("Restaurando desde caché en memoria")
            _write_jobs(_jobs_cache)
            return dict(_jobs_cache)
        return {}


def _write_jobs(jobs: dict):
    """Escribe jobs de forma atómica: temp file + rename para evitar corrupción."""
    tmp_path = JOBS_PATH + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(jobs, f, indent=2)
        os.replace(tmp_path, JOBS_PATH)
        _jobs_cache.clear()
        _jobs_cache.update(jobs)
    except Exception as exc:
        logger.warning(f"Error escribiendo {JOBS_PATH}: {exc}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _cleanup_old_jobs(jobs: dict, keep_running: bool = True) -> dict:
    """Elimina jobs completados/error antiguos para mantener el archivo pequeño."""
    now = datetime.datetime.now()
    cleaned = {}
    # Siempre mantener los running
    for jid, j in jobs.items():
        if j.get("status") in ("running",):
            cleaned[jid] = j

    # Mantener hasta 3 jobs recientes (completados o con error) para depuración
    completed = [
        (jid, j) for jid, j in jobs.items()
        if j.get("status") in ("completed", "error")
    ]
    completed.sort(key=lambda x: x[1].get("updated_at", ""), reverse=True)
    for jid, j in completed[:3]:
        cleaned[jid] = j

    return cleaned


def create_job(total: int) -> str:
    job_id = str(uuid.uuid4())
    now = datetime.datetime.now().isoformat()
    job = {
        "id": job_id,
        "status": "running",
        "total": total,
        "processed": 0,
        "failed": 0,
        "errors": [],
        "result": None,
        "error_message": None,
        "created_at": now,
        "updated_at": now,
        "cancel_requested": False,
    }
    with _jobs_lock:
        jobs = _read_jobs()
        jobs = _cleanup_old_jobs(jobs)
        jobs[job_id] = job
        _write_jobs(jobs)
    return job_id


def get_active_jobs() -> list[dict]:
    with _jobs_lock:
        jobs = _read_jobs()
        return [j for j in jobs.values() if j.get("status") == "running"]


def get_job(job_id: str) -> dict | None:
    with _jobs_lock:
        jobs = _read_jobs()
        return jobs.get(job_id)


def _update_job(job_id: str, **kwargs):
    with _jobs_lock:
        jobs = _read_jobs()
        if job_id not in jobs:
            return
        jobs[job_id].update(kwargs)
        jobs[job_id]["updated_at"] = datetime.datetime.now().isoformat()
        _write_jobs(jobs)


def update_job_progress(job_id: str, processed: int, failed: int, errors: list):
    _update_job(job_id, processed=processed, failed=failed, errors=errors)


def complete_job(job_id: str, result: dict):
    _update_job(job_id, status="completed", result=result)


def fail_job(job_id: str, error: str):
    _update_job(job_id, status="error", error_message=error)


def cancel_job(job_id: str):
    _update_job(job_id, cancel_requested=True)
    event = _running_jobs.get(job_id)
    if event:
        event.set()


def is_cancelled(job_id: str) -> bool:
    event = _running_jobs.get(job_id)
    if event and event.is_set():
        return True
    job = get_job(job_id)
    if job is None:
        return False
    return job.get("cancel_requested", False)


def delete_job(job_id: str):
    with _jobs_lock:
        jobs = _read_jobs()
        jobs.pop(job_id, None)
        _write_jobs(jobs)


_DAMODARAN_FALLBACK = 0.2549

STATUTORY_TAX_RATES: dict[str, float] = {
    "SE": 0.206, "NO": 0.22, "DK": 0.22, "FI": 0.20, "DE": 0.30,
    "FR": 0.25, "NL": 0.258, "GB": 0.25, "CA": 0.265, "AU": 0.30,
    "MY": 0.24, "HK": 0.165, "SG": 0.17, "PL": 0.19, "US": 0.21,
    "BE": 0.25, "JP": 0.304, "CN": 0.25, "IN": 0.258, "KR": 0.22,
    "ID": 0.22, "TH": 0.20, "PH": 0.25, "TW": 0.20,
}

UNUSUAL_THRESHOLD = 0.30
TAX_MAX = 0.60

EQUITY_LABELS = [
    "Stockholders Equity",
    "Total Stockholder Equity",
    "Total Equity Gross Minority Interest",
    "Common Stock Equity",
]

DEBT_LABELS_LT = [
    "Long Term Debt And Capital Lease Obligation",
    "Long Term Debt",
    "Debt Long Term Total",
]

DEBT_LABELS_ST = [
    "Current Debt And Capital Lease Obligation",
    "Current Debt",
    "Short Term Debt",
]

TOTAL_ASSETS_LABELS = [
    "Total Assets",
    "Total Assets As Reported",
]

_FX_CACHE: dict[str, float] = {"USD": 1.0}
_fx_cache_lock = threading.Lock()


def get_fx_rate(currency: str, cancel_event: threading.Event = None) -> float:
    currency = currency.upper().strip()
    if currency in _FX_CACHE:
        return _FX_CACHE[currency]
    pair = f"{currency}USD=X"
    for attempt in range(3):
        if cancel_event and cancel_event.is_set():
            return 1.0
        _delay(1.5)
        try:
            hist = yf.Ticker(pair, session=_YF_SESSION).history(period="5d")
            if hist.empty:
                raise ValueError("Sin datos")
            rate = float(hist["Close"].dropna().iloc[-1])
            if 0.000001 <= rate <= 200.0:
                with _fx_cache_lock:
                    _FX_CACHE[currency] = rate
                return rate
        except Exception:
            if attempt < 2:
                time.sleep(1)
    with _fx_cache_lock:
        _FX_CACHE[currency] = 1.0
    return 1.0


def first_valid(df: pd.DataFrame, labels: list) -> float | None:
    for lbl in labels:
        if lbl in df.index:
            val = df.loc[lbl].iloc[0]
            if pd.notna(val):
                return float(val)
    return None


def get_clean_tax_rate(inc: pd.DataFrame, country: str) -> tuple[float, str]:
    pretax_label = (
        "Pretax Income"
        if "Pretax Income" in inc.index
        else "Income Before Tax"
        if "Income Before Tax" in inc.index
        else None
    )
    tax_label = (
        "Tax Provision"
        if "Tax Provision" in inc.index
        else "Income Tax Expense"
        if "Income Tax Expense" in inc.index
        else None
    )
    unusual_label = (
        "Total Unusual Items" if "Total Unusual Items" in inc.index else None
    )

    if pretax_label is None or tax_label is None:
        statutory = STATUTORY_TAX_RATES.get(country, _DAMODARAN_FALLBACK)
        return statutory, f"statutory {country} (sin labels IS)"

    for col in inc.columns:
        year = str(col)[:10]
        pre = float(inc.loc[pretax_label, col]) if pd.notna(inc.loc[pretax_label, col]) else None
        tax = float(inc.loc[tax_label, col]) if pd.notna(inc.loc[tax_label, col]) else None
        unu = float(inc.loc[unusual_label, col]) if (unusual_label and pd.notna(inc.loc[unusual_label, col])) else 0.0

        if pre is None or pre <= 0:
            continue
        if abs(unu / pre) > UNUSUAL_THRESHOLD:
            continue
        if tax is None:
            continue
        tasa = tax / pre
        if tasa < 0 or tasa > TAX_MAX:
            continue
        return tasa, f"año {year} (unusual={abs(unu / pre):.1%})"

    statutory = STATUTORY_TAX_RATES.get(country, _DAMODARAN_FALLBACK)
    return statutory, f"statutory {country} (todos los años descartados)"


def _process_single_ticker(ticker: str, cancel_event: threading.Event = None):
    if cancel_event and cancel_event.is_set():
        return None

    _delay(1.5)
    try:
        stock = yf.Ticker(ticker, session=_YF_SESSION)
        info = stock.info
    except Exception as e:
        logger.warning(f"yfinance error for {ticker}: {e}")
        return None

    if not info:
        logger.warning(f"yfinance returned empty info for {ticker}")
        return None
    if not info.get("shortName"):
        logger.warning(f"yfinance info missing shortName for {ticker}: keys={list(info.keys())[:10]}")
        return None

    if cancel_event and cancel_event.is_set():
        return None

    listing_currency = info.get("currency", "USD")
    reporting_currency = info.get("financialCurrency", listing_currency)
    country = info.get("country", "")

    fx_rate = get_fx_rate(reporting_currency, cancel_event)
    fx_listing = get_fx_rate(listing_currency, cancel_event)

    bs = stock.balance_sheet
    debt_value = None
    debt_lt = 0.0
    debt_st = 0.0
    total_assets = None

    if bs is not None and not bs.empty:
        raw_debt_lt = first_valid(bs, DEBT_LABELS_LT)
        raw_debt_st = first_valid(bs, DEBT_LABELS_ST)
        debt_lt = (raw_debt_lt * fx_rate) if raw_debt_lt is not None else 0.0
        debt_st = (raw_debt_st * fx_rate) if raw_debt_st is not None else 0.0
        if raw_debt_lt is not None or raw_debt_st is not None:
            debt_value = debt_lt + debt_st

    inc = stock.financials
    if inc is not None and not inc.empty:
        tax_rate_val, tax_source = get_clean_tax_rate(inc, country)
    else:
        tax_rate_val = STATUTORY_TAX_RATES.get(country, _DAMODARAN_FALLBACK)
        tax_source = f"statutory {country} (IS vacío)"

    beta_levered = info.get("beta", None)
    market_cap = info.get("marketCap", None)
    market_cap_usd = market_cap * fx_listing if market_cap is not None else None

    if market_cap_usd is not None and debt_value is not None:
        total_assets = market_cap_usd + debt_value
    elif market_cap_usd is not None:
        total_assets = market_cap_usd

    de_ratio = None
    if debt_value is not None and market_cap_usd is not None and market_cap_usd != 0:
        de_ratio = debt_value / market_cap_usd

    beta_unlevered = None
    if beta_levered is not None and de_ratio is not None:
        denom = 1 + (1 - tax_rate_val) * de_ratio
        if denom != 0:
            beta_unlevered = beta_levered / denom

    if beta_unlevered is not None and beta_unlevered < 0:
        return None

    api_data = {
        "ticker": ticker,
        "company_name": info.get("shortName", ticker),
        "sector": info.get("sector", "Unknown"),
        "country": country,
        "listing_currency": listing_currency,
        "reporting_currency": reporting_currency,
        "fx_rate": fx_rate,
        "debt_value": debt_value,
        "equity_value": market_cap_usd,
        "total_assets": total_assets,
        "dc_ratio": round(de_ratio, 4) if de_ratio is not None else None,
        "effective_tax_rate": round(tax_rate_val, 4),
        "tax_source": tax_source,
        "beta_levered": round(beta_levered, 4) if beta_levered is not None else None,
        "beta_unlevered": round(beta_unlevered, 4) if beta_unlevered else 0.0,
        "pct_debt": round(debt_value / (debt_value + market_cap_usd), 4) if debt_value is not None and market_cap_usd is not None and (debt_value + market_cap_usd) != 0 else None,
        "pct_equity": round(market_cap_usd / (debt_value + market_cap_usd), 4) if debt_value is not None and market_cap_usd is not None and (debt_value + market_cap_usd) != 0 else None,
        "market_cap": market_cap,
    }

    return None, api_data


def get_existing_tickers_with_values() -> set[str]:
    """
    Consulta la base de datos para obtener un conjunto de tickers que ya existen
    y tienen valores considerados como válidos (ej. beta_unlevered no es 0).
    """
    db = SessionLocal()
    existing_tickers = set()
    try:
        existing_records_query = db.query(TemplateComplement).filter(
            TemplateComplement.nombre.like('boa_batch_%')
        )
        for record in existing_records_query:
            for company_data in record.data.get("companies", []):
                ticker = company_data.get("ticker")
                if ticker:
                    if company_data.get("beta_unlevered") != 0.0 and company_data.get("total_assets") is not None:
                        existing_tickers.add(ticker)
    finally:
        db.close()
    return existing_tickers
def _upsert_companies_to_db(companies: list[dict], job_id: str = "", batch_idx: int = 0):
    """Save batch companies as a TemplateComplement record."""
    if not companies:
        return

    db = SessionLocal()
    try:
        # Extraer todos los tickers del lote actual
        tickers_in_batch = {c['ticker'] for c in companies}

        # Consultar la base de datos para ver cuáles de estos tickers ya existen
        existing_records_query = db.query(TemplateComplement).filter(
            TemplateComplement.nombre.like('boa_batch_%')
        )
        
        existing_tickers_with_values = set()
        
        for record in existing_records_query:
            for company_data in record.data.get("companies", []):
                ticker = company_data.get("ticker")
                if ticker in tickers_in_batch:
                    # Comprobar si el ticker tiene un valor válido (p. ej., beta_unlevered no es 0)
                    if company_data.get("beta_unlevered") != 0.0 and company_data.get("total_assets") is not None:
                        existing_tickers_with_values.add(ticker)

        # Filtrar la lista de `companies` para excluir los que ya existen y tienen valores
        companies_to_upsert = [
            c for c in companies if c['ticker'] not in existing_tickers_with_values
        ]

        if not companies_to_upsert:
            logger.info(f"Lote {batch_idx}: Todos los tickers ya existen con valores válidos, no se necesita inserción.")
            return

        # Si aún quedan empresas por insertar/actualizar, proceder
        record_name = f"boa_batch_{job_id}_{batch_idx}"
        
        # Intentar encontrar un registro existente para actualizarlo
        record = db.query(TemplateComplement).filter(TemplateComplement.nombre == record_name).first()
        
        if record:
            # Si existe, actualiza los datos
            existing_data = record.data.get("companies", [])
            
            # Crear un diccionario para facilitar la búsqueda de empresas existentes
            existing_dict = {c['ticker']: c for c in existing_data}
            
            # Actualizar o agregar las nuevas empresas
            for company in companies_to_upsert:
                existing_dict[company['ticker']] = company
            
            record.data = {"batch": batch_idx, "companies": list(existing_dict.values())}
            
        else:
            # Si no existe, crea un nuevo registro
            record = TemplateComplement(
                nombre=record_name,
                fecha=datetime.datetime.now(),
                data={"batch": batch_idx, "companies": companies_to_upsert},
            )
            db.add(record)

        db.commit()
        logger.info(f"Guardado/actualizado lote {batch_idx} ({len(companies_to_upsert)} empresas) en main_template_complements")

    except Exception as exc:
        db.rollback()
        logger.warning(f"Error guardando lote {batch_idx} en DB: {exc}")
    finally:
        db.close()


def _rate_limit_delay(attempt: int, base: float = 2.0) -> None:
    delay = base * (2 ** attempt) + random.uniform(0, 1)
    logger.info(f"  Rate limiting detectado, esperando {delay:.1f}s (intento {attempt + 1})...")
    time.sleep(delay)


def calculate_subsectores_boa(tickers: list[str], job_id: str | None = None) -> dict:
    BATCH_SIZE = 50
    companies = []
    errors = []
    processed_ok = 0
    failed_count = 0
    cancel_event = threading.Event()

    consecutive_empty_batches = 0
    max_empty_batches_before_abort = 5

    if job_id:
        _running_jobs[job_id] = cancel_event

    t_start = time.perf_counter()
    logger.info(f"Procesando {len(tickers)} tickers en lotes de {BATCH_SIZE}...")

    total_batches = (len(tickers) + BATCH_SIZE - 1) // BATCH_SIZE
    last_batch = -1
    if job_id:
        job = get_job(job_id)
        if job and "last_batch" in job:
            last_batch = job["last_batch"]
            logger.info(f"Reanudando desde lote {last_batch + 1}")

    for batch_idx in range(total_batches):
        if cancel_event.is_set() or (job_id and is_cancelled(job_id)):
            logger.info(f"Job {job_id} cancelado")
            cancel_event.set()
            break

        if batch_idx <= last_batch:
            logger.info(f"Lote {batch_idx + 1} ya procesado, saltando...")
            continue

        if consecutive_empty_batches > max_empty_batches_before_abort:
            logger.warning(
                f"Demasiados lotes vacíos consecutivos ({consecutive_empty_batches}). "
                "Posible rate limiting definitivo, abortando."
            )
            break

        batch_start = batch_idx * BATCH_SIZE
        batch_end = min(batch_start + BATCH_SIZE, len(tickers))
        batch_tickers = tickers[batch_start:batch_end]
        batch_companies = []

        logger.info(f"Lote {batch_idx + 1}/{total_batches} (tickers {batch_start + 1}-{batch_end})")

        for i, ticker in enumerate(batch_tickers):
            if cancel_event.is_set() or (job_id and is_cancelled(job_id)):
                cancel_event.set()
                break

            logger.info(f"  Ticker {i + 1}/{len(batch_tickers)}: {ticker}")
            api_data = None
            last_error = None

            for attempt in range(3):
                if cancel_event.is_set() or (job_id and is_cancelled(job_id)):
                    cancel_event.set()
                    break

                try:
                    res = _process_single_ticker(ticker, cancel_event)
                    if res is not None:
                        _, api_data = res
                        break
                except Exception as exc:
                    err_msg = str(exc).lower()
                    last_error = {
                        "ticker": ticker,
                        "mensaje": f"Intento {attempt + 1}/3: Error - {str(exc)}",
                    }
                    if "rate" in err_msg or "limit" in err_msg or "429" in err_msg or "too many" in err_msg:
                        _rate_limit_delay(attempt)
                    elif attempt < 2:
                        _delay(1.0)
                    continue

                last_error = {
                    "ticker": ticker,
                    "mensaje": f"Intento {attempt + 1}/3: No se pudo resolver",
                }
                if attempt < 2:
                    _delay(1.0)

            if api_data:
                companies.append(api_data)
                batch_companies.append(api_data)
                processed_ok += 1
            elif last_error:
                failed_count += 1
                errors.append(last_error)

            if job_id:
                update_job_progress(
                    job_id,
                    processed=processed_ok,
                    failed=failed_count,
                    errors=errors,
                )

        if batch_companies:
            _upsert_companies_to_db(batch_companies, job_id=job_id or "", batch_idx=batch_idx)
            consecutive_empty_batches = 0
        else:
            consecutive_empty_batches += 1

        if job_id:
            _update_job(job_id, result={
                "valid_companies": companies,
                "errors": errors,
            }, last_batch=batch_idx)

        if batch_idx < total_batches - 1 and not cancel_event.is_set():
            batch_delay = 5
            if consecutive_empty_batches > 0:
                batch_delay = 15 * (2 ** (consecutive_empty_batches - 1))
                batch_delay = min(batch_delay, 180)
            logger.info(f"Esperando {batch_delay}s antes del siguiente lote...")
            time.sleep(batch_delay)

    t_end = time.perf_counter()
    logger.info(f"BOA completado en {t_end - t_start:.2f}s (job={job_id}) - {processed_ok} ok, {failed_count} failed")

    result = {
        "success": True,
        "valid_companies": companies,
        "errors": errors,
        "total": len(tickers),
        "processed": processed_ok,
        "failed": failed_count,
    }

    if job_id:
        if cancel_event.is_set() or is_cancelled(job_id):
            fail_job(job_id, "Cancelado por el usuario")
        else:
            complete_job(job_id, result)
        _running_jobs.pop(job_id, None)

    return result


def import_boa_jobs_to_db() -> dict:
    """Read all completed jobs from boa_jobs.json and upsert companies into DB."""
    jobs = _read_jobs()
    imported = 0
    errors = []

    for job_id, job in jobs.items():
        if job.get("status") != "completed":
            continue
        result = job.get("result")
        if not result:
            continue
        companies = result.get("valid_companies", [])
        if not companies:
            continue

        try:
            _upsert_companies_to_db(companies, job_id=job_id, batch_idx=-1)
            imported += len(companies)
        except Exception as exc:
            errors.append({"job_id": job_id, "error": str(exc)})

    return {"imported": imported, "errors": errors}
