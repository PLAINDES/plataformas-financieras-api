import concurrent.futures
import datetime
import json
import logging
import os
import threading
import time
import uuid

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

NOT_FOUND_CSV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "boa_not_found.csv",
)
SUFFIX_FOUND_CSV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "boa_suffix_found.csv",
)
SUFFIX_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "boa_suffix_log.txt",
)

SUFFIX_STATS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "boa_suffix_stats.txt",
)

JOBS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "boa_jobs.json",
)
_jobs_lock = threading.Lock()


def _read_jobs() -> dict:
    if not os.path.exists(JOBS_PATH):
        return {}
    try:
        with open(JOBS_PATH) as f:
            return json.load(f)
    except Exception as exc:
        logger.warning(f"Error leyendo {JOBS_PATH}: {exc}")
        return {}


def _write_jobs(jobs: dict):
    try:
        with open(JOBS_PATH, "w") as f:
            json.dump(jobs, f, indent=2)
    except Exception as exc:
        logger.warning(f"Error escribiendo {JOBS_PATH}: {exc}")


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


def is_cancelled(job_id: str) -> bool:
    job = get_job(job_id)
    if job is None:
        return False
    return job.get("cancel_requested", False)


def delete_job(job_id: str):
    with _jobs_lock:
        jobs = _read_jobs()
        jobs.pop(job_id, None)
        _write_jobs(jobs)


_SUFFIX_CACHE: dict[str, str] = {}
if os.path.exists(SUFFIX_FOUND_CSV_PATH):
    try:
        with open(SUFFIX_FOUND_CSV_PATH) as f:
            for line in f:
                line = line.strip()
                if "," in line:
                    parts = line.split(",", 1)
                    if len(parts) == 2 and parts[0] and parts[1]:
                        _SUFFIX_CACHE[parts[0]] = parts[1]
    except Exception as exc:
        logger.warning(f"No se pudo cargar cache de {SUFFIX_FOUND_CSV_PATH}: {exc}")
logger.info(f"Cargados {len(_SUFFIX_CACHE)} sufijos del cache")

_NOT_FOUND_TICKERS: set[str] = set()
if os.path.exists(NOT_FOUND_CSV_PATH):
    try:
        with open(NOT_FOUND_CSV_PATH) as f:
            for line in f:
                ticker = line.strip()
                if ticker:
                    _NOT_FOUND_TICKERS.add(ticker)
    except Exception as exc:
        logger.warning(f"No se pudo cargar {NOT_FOUND_CSV_PATH}: {exc}")
logger.info(f"Cargados {len(_NOT_FOUND_TICKERS)} tickers no resueltos (skip list)")

_FX_CACHE: dict[str, float] = {"USD": 1.0}
_fx_cache_lock = threading.Lock()

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


def get_fx_rate(currency: str) -> float:
    currency = currency.upper().strip()
    if currency in _FX_CACHE:
        return _FX_CACHE[currency]
    pair = f"{currency}USD=X"
    try:
        hist = yf.Ticker(pair).history(period="5d")
        if hist.empty:
            raise ValueError("Sin datos")
        rate = float(hist["Close"].dropna().iloc[-1])
        if 0.000001 <= rate <= 200.0:
            with _fx_cache_lock:
                _FX_CACHE[currency] = rate
            return rate
    except Exception:
        pass
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


def _process_single_ticker(ticker: str, used_suffix: str = ""):
    full_ticker = ticker + used_suffix if used_suffix else ticker

    try:
        stock = yf.Ticker(full_ticker)
        info = stock.info
    except Exception:
        return None

    if not info or not info.get("shortName"):
        return None

    listing_currency = info.get("currency", "USD")
    reporting_currency = info.get("financialCurrency", listing_currency)
    country = info.get("country", "")

    fx_rate = get_fx_rate(reporting_currency)
    fx_listing = get_fx_rate(listing_currency)

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

    suffix_used = used_suffix if used_suffix else None

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
        "suffix_used": suffix_used,
    }

    return None, api_data


def _load_suffixes_from_stats() -> list[str]:
    defaults = [".L", ".DE", ".MC", ".TO", ".V", ".PA", ".AS", ".MI",
                ".HE", ".ST", ".CO", ".OL", ".VI", ".WA", ".HK", ".TW",
                ".KS", ".SS", ".SZ", ".NS", ".SI", ".SW", ".KL", ".JK"]
    if not os.path.exists(SUFFIX_STATS_PATH):
        logger.warning(f"No se encuentra {SUFFIX_STATS_PATH}, usando defaults")
        return defaults
    import re
    try:
        with open(SUFFIX_STATS_PATH) as f:
            in_used = False
            for line in f:
                stripped = line.strip()
                if "Sufijos USADOS" in stripped:
                    in_used = True
                    continue
                if in_used:
                    if "Total" in stripped:
                        break
                    m = re.match(r'\s*(\S+)\s*→\s*(\d+)', stripped)
                    if m:
                        suffix = m.group(1).strip()
                        count = int(m.group(2))
                        suffixes.append((count, suffix))
        suffixes.sort(key=lambda x: -x[0])
        return [s for _, s in suffixes]
    except Exception as exc:
        logger.warning(f"Error parseando {SUFFIX_STATS_PATH}: {exc}")
        return defaults

SUFFIXES_TO_TRY = _load_suffixes_from_stats()
logger.info(f"Cargados {len(SUFFIXES_TO_TRY)} sufijos desde stats: {SUFFIXES_TO_TRY}")

def _try_suffixes(ticker: str) -> tuple:
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)
    fut_map = {executor.submit(_process_single_ticker, ticker, s): s for s in SUFFIXES_TO_TRY}
    try:
        for fut in concurrent.futures.as_completed(fut_map):
            res = fut.result()
            if res is not None:
                for f in fut_map:
                    f.cancel()
                _, api_data = res
                suffix = fut_map[fut]
                _save_suffix(ticker, suffix)
                _log_suffix_execution(ticker, suffix, "ok (descubierto)")
                error_info = {
                    "ticker": ticker,
                    "suffix_usado": suffix,
                    "mensaje": f"Resuelto con sufijo {suffix} (descubierto)",
                }
                return None, api_data, error_info, False
    finally:
        executor.shutdown(wait=False)
    return None, None, None, None


def _save_suffix(ticker: str, suffix: str):
    if not suffix:
        return
    _SUFFIX_CACHE[ticker] = suffix
    try:
        with open(SUFFIX_FOUND_CSV_PATH, "a") as f:
            f.write(f"{ticker},{suffix}\n")
    except Exception as exc:
        logger.warning(f"No se pudo guardar sufijo en {SUFFIX_FOUND_CSV_PATH}: {exc}")


def _process_single_ticker_with_fallback(ticker: str):
    if ticker in _NOT_FOUND_TICKERS:
        _log_suffix_execution(ticker, None, "ignorado — no resoluble")
        return None, None, None, True

    cached_suffix = _SUFFIX_CACHE.get(ticker)
    if cached_suffix:
        res = _process_single_ticker(ticker, cached_suffix)
        if res is not None:
            _, api_data = res
            _log_suffix_execution(ticker, cached_suffix, "ok")
            error_info = {
                "ticker": ticker,
                "suffix_usado": cached_suffix,
                "mensaje": f"Usó sufijo {cached_suffix} (cache)",
            }
            return None, api_data, error_info, False
        _log_suffix_execution(ticker, cached_suffix, "falló — sufijo cacheado no funciona")
        error_info = {
            "ticker": ticker,
            "suffix_usado": cached_suffix,
            "mensaje": "No se pudo resolver ni con sufijo conocido",
        }
        return None, None, error_info, False

    res = _process_single_ticker(ticker)
    if res is not None:
        _, api_data = res
        _log_suffix_execution(ticker, None, "ok (raw)")
        return None, api_data, None, False

    suffix_res = _try_suffixes(ticker)
    if suffix_res[1] is not None:
        return suffix_res

    _log_suffix_execution(ticker, None, "no encontrado — sin sufijo conocido")
    error_info = {
        "ticker": ticker,
        "suffix_usado": None,
        "mensaje": "No se pudo resolver el ticker",
    }
    return None, None, error_info, False


def _log_suffix_execution(ticker: str, suffix: str | None, status: str):
    timestamp = datetime.datetime.now().isoformat()
    suffix_str = suffix or "—"
    line = f"[{timestamp}] {ticker} | sufijo: {suffix_str} | {status}\n"
    try:
        with open(SUFFIX_LOG_PATH, "a") as f:
            f.write(line)
    except Exception as exc:
        logger.warning(f"No se pudo escribir el log de sufijos: {exc}")


def calculate_subsectores_boa(tickers: list[str], job_id: str | None = None) -> dict:
    companies = []
    errors = []
    processed_ok = 0
    failed_count = 0

    t_start = time.perf_counter()
    logger.info(f"Procesando {len(tickers)} tickers...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures_map = {
            executor.submit(_process_single_ticker_with_fallback, ticker): ticker
            for ticker in tickers
        }

        for future in concurrent.futures.as_completed(futures_map):
            if job_id and is_cancelled(job_id):
                logger.info(f"Job {job_id} cancelado por el usuario")
                for f in futures_map:
                    f.cancel()
                break

            _, api_data, error_info, skip_silently = future.result()
            if api_data:
                companies.append(api_data)
                processed_ok += 1
            elif not skip_silently:
                failed_count += 1
            if error_info:
                errors.append(error_info)

            if job_id:
                update_job_progress(
                    job_id,
                    processed=processed_ok,
                    failed=failed_count,
                    errors=errors,
                )

    t_end = time.perf_counter()
    logger.info(f"BOA completado en {t_end - t_start:.2f}s (job={job_id})")

    result = {
        "success": True,
        "valid_companies": companies,
        "errors": errors,
        "total": len(tickers),
        "processed": processed_ok,
        "failed": len(tickers) - processed_ok,
    }

    if job_id:
        if is_cancelled(job_id):
            fail_job(job_id, "Cancelado por el usuario")
        else:
            complete_job(job_id, result)

    return result
