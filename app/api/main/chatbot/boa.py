import datetime
import difflib
import json
import logging
import os
import random
import re
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
BOA_DEBUG_DEFAULT_LIMIT = 5
BOA_DEBUG_RANDOM_SEED = None
BOA_LOG_TICKER_STEPS = True

# Aliases confirmed by an authoritative source. Search results are useful for
# discovery, but only verified aliases or identity-matched companies are used
# automatically to avoid calculating a different company after a 404.
VERIFIED_TICKER_ALIASES: dict[str, dict] = {
    "VSCO": {
        "ticker": "VSXY",
        "company_name": "Victoria's Secret & Co.",
        "reason": "symbol_changed",
        "source": "SEC",
        "source_url": "https://www.sec.gov/Archives/edgar/data/1856437/000185643726000007/ex991vscomay212026pressrel.htm",
        "effective_date": "2026-06-02",
    },
}

_ticker_resolution_cache: dict[tuple[str, str], dict] = {}
_ticker_resolution_lock = threading.Lock()


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
    "LongTermDebt",
    "Long-Term Debt",
    "Debt Long Term Total",
    "Total Long Term Debt",
    "Non Current Portion Of Long Term Debt",
    "LongTermDebtNoncurrent",
]

DEBT_LABELS_ST = [
    "Current Debt And Capital Lease Obligation",
    "Current Debt",
    "Short Term Debt",
    "ShortTermDebt",
    "Current Portion Of Long Term Debt",
    "CurrentPortionOfLongTermDebt",
    "Debt Current",
    "Short-Term Debt",
    "Other Current Borrowings",
]

SHARE_LABELS = [
    "Share Issued",
    "Ordinary Shares Number",
    "Common Stock Shares Outstanding",
    "CommonStockSharesOutstanding",
    "Shares Issued",
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
    """Return the newest non-null value found across all available columns."""
    for lbl in labels:
        if lbl in df.index:
            row = df.loc[lbl]
            if isinstance(row, pd.DataFrame):
                values = row.stack().dropna()
            else:
                values = row.dropna()
            if not values.empty:
                return float(values.iloc[0])
    return None


def get_deuda(
    stock: yf.Ticker,
) -> tuple[float | None, float | None, dict[str, str]]:
    """Read each debt component independently, with quarterly fallback."""
    raw_lt = None
    raw_st = None
    sources = {"debt_lt": "no_disponible", "debt_st": "no_disponible"}
    for attr in ("balance_sheet", "quarterly_balance_sheet"):
        try:
            bs = getattr(stock, attr)
        except Exception as exc:
            logger.info("No se pudo leer %s para deuda: %s", attr, exc)
            continue
        if bs is None or bs.empty:
            continue
        if raw_lt is None:
            raw_lt = first_valid(bs, DEBT_LABELS_LT)
            if raw_lt is not None:
                sources["debt_lt"] = attr
        if raw_st is None:
            raw_st = first_valid(bs, DEBT_LABELS_ST)
            if raw_st is not None:
                sources["debt_st"] = attr
        if raw_lt is not None and raw_st is not None:
            break
    return raw_lt, raw_st, sources


def _fmt_log_value(value):
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _log_ticker_step(ticker: str, step: str, **values):
    if not BOA_LOG_TICKER_STEPS:
        return
    payload = ", ".join(f"{k}={_fmt_log_value(v)}" for k, v in values.items())
    line = f"[BOA][{ticker}] {step}" + (f" | {payload}" if payload else "")
    logger.info(line)
    print(line, flush=True)


def _normalize_company_name(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    ignored = {"inc", "incorporated", "corp", "corporation", "company", "co", "ltd", "limited", "plc", "sa"}
    return " ".join(part for part in normalized.split() if part not in ignored)


def _ticker_resolution_result(
    original: str,
    *,
    resolved: str | None = None,
    status: str = "not_found",
    reason: str = "ticker_not_found",
    source: str = "none",
    confidence: float = 0.0,
    candidates: list[dict] | None = None,
    details: dict | None = None,
) -> dict:
    return {
        "ticker_original": original,
        "ticker_resolved": resolved,
        "ticker_resolution_status": status,
        "ticker_resolution_reason": reason,
        "ticker_resolution_source": source,
        "ticker_resolution_confidence": round(confidence, 4),
        "ticker_resolution_candidates": candidates or [],
        "ticker_resolution_details": details or {},
    }


def resolve_ticker_symbol(
    ticker: str,
    company_name: str | None = None,
    *,
    search_candidates: bool = True,
) -> dict:
    """Resolve obsolete symbols without silently substituting another company."""
    original = ticker.strip().upper()
    alias = VERIFIED_TICKER_ALIASES.get(original)
    if alias:
        return _ticker_resolution_result(
            original,
            resolved=alias["ticker"],
            status="resolved",
            reason=alias["reason"],
            source=alias["source"],
            confidence=1.0,
            details={
                "company_name": alias["company_name"],
                "source_url": alias["source_url"],
                "effective_date": alias["effective_date"],
            },
        )

    if not search_candidates:
        return _ticker_resolution_result(original, status="not_checked")

    normalized_name = _normalize_company_name(company_name)
    cache_key = (original, normalized_name)
    with _ticker_resolution_lock:
        cached = _ticker_resolution_cache.get(cache_key)
    if cached is not None:
        return dict(cached)

    candidates: list[dict] = []
    try:
        search = yf.Search(company_name or original, max_results=8, news_count=0)
        for quote in search.quotes or []:
            symbol = str(quote.get("symbol") or "").strip().upper()
            quote_type = str(quote.get("quoteType") or quote.get("typeDisp") or "").upper()
            if not symbol or symbol == original or (quote_type and "EQUITY" not in quote_type):
                continue
            candidate_name = quote.get("longname") or quote.get("shortname") or ""
            score = (
                difflib.SequenceMatcher(
                    None,
                    normalized_name,
                    _normalize_company_name(candidate_name),
                ).ratio()
                if normalized_name
                else 0.0
            )
            candidates.append({
                "ticker": symbol,
                "company_name": candidate_name,
                "exchange": quote.get("exchDisp") or quote.get("exchange"),
                "quote_type": quote_type or None,
                "confidence": round(score, 4),
            })
    except Exception as exc:
        result = _ticker_resolution_result(
            original,
            status="search_failed",
            reason="ticker_search_failed",
            source="yfinance.Search",
            details={"error": str(exc)},
        )
    else:
        candidates.sort(key=lambda item: item["confidence"], reverse=True)
        best = candidates[0] if candidates else None
        second_score = candidates[1]["confidence"] if len(candidates) > 1 else 0.0
        if normalized_name and best and best["confidence"] >= 0.9 and best["confidence"] - second_score >= 0.08:
            result = _ticker_resolution_result(
                original,
                resolved=best["ticker"],
                status="resolved",
                reason="symbol_changed_identity_match",
                source="yfinance.Search",
                confidence=best["confidence"],
                candidates=candidates,
                details={"matched_company_name": best["company_name"]},
            )
        else:
            result = _ticker_resolution_result(
                original,
                status="requires_review" if candidates else "not_found",
                reason="ambiguous_symbol_candidates" if candidates else "no_symbol_candidates",
                source="yfinance.Search",
                confidence=best["confidence"] if best else 0.0,
                candidates=candidates,
            )

    with _ticker_resolution_lock:
        _ticker_resolution_cache[cache_key] = dict(result)
    return result


def _find_info_key(info: dict, candidates: list[str]) -> str | None:
    for key in candidates:
        if key in info:
            return key
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
        return None, None, {"reason": "cancelled"}

    _log_ticker_step(ticker, "inicio")
    _delay(1.5)
    try:
        stock = yf.Ticker(ticker, session=_YF_SESSION)
        info = stock.info
    except Exception as e:
        logger.warning(f"yfinance error for {ticker}: {e}")
        _log_ticker_step(ticker, "error_info", error=str(e))
        return None, None, {"reason": _classify_error(e), "error": str(e)}

    if not info:
        logger.warning(f"yfinance returned empty info for {ticker}")
        _log_ticker_step(ticker, "info_vacio")
        return None, None, {"reason": "empty_info"}
    if not info.get("shortName") and not info.get("longName"):
        logger.warning(f"yfinance info missing shortName and longName for {ticker}: keys={list(info.keys())[:10]}")
        _log_ticker_step(ticker, "sin_nombre", keys=list(info.keys())[:10])
        info["shortName"] = ticker

    if cancel_event and cancel_event.is_set():
        return None, None, {"reason": "cancelled"}

    listing_currency = info.get("currency", "USD")
    reporting_currency = info.get("financialCurrency", listing_currency)
    country = info.get("country", "")
    beta_levered = info.get("beta", None)
    market_cap = info.get("marketCap", None)

    _log_ticker_step(
        ticker,
        "info_base",
        listing_currency=listing_currency,
        reporting_currency=reporting_currency,
        country=country,
        beta_levered=beta_levered,
        market_cap=market_cap,
    )

    fx_rate = get_fx_rate(reporting_currency, cancel_event)
    fx_listing = get_fx_rate(listing_currency, cancel_event)
    _log_ticker_step(ticker, "fx", fx_rate=fx_rate, fx_listing=fx_listing)

    bs = stock.balance_sheet
    debt_value = None
    debt_lt = None
    debt_st = None
    total_assets = None

    if bs is not None and not bs.empty:
        bs_indices = [str(idx) for idx in bs.index.tolist()]
        _log_ticker_step(
            ticker,
            "balance_sheet_indices",
            count=len(bs_indices),
            sample="|".join(bs_indices[:25]),
        )
    else:
        _log_ticker_step(ticker, "balance_sheet_vacio")

    raw_debt_lt, raw_debt_st, debt_sources = get_deuda(stock)
    if raw_debt_lt is not None or raw_debt_st is not None:
        debt_lt = (raw_debt_lt * fx_rate) if raw_debt_lt is not None else 0.0
        debt_st = (raw_debt_st * fx_rate) if raw_debt_st is not None else 0.0
        debt_value = debt_lt + debt_st
        _log_ticker_step(ticker, "deuda_bruta", raw_debt_lt=raw_debt_lt, raw_debt_st=raw_debt_st, debt_lt=debt_lt, debt_st=debt_st)
        if raw_debt_lt is None or raw_debt_st is None:
            _log_ticker_step(
                ticker,
                "deuda_componente_no_reportado",
                debt_lt_status="ok" if raw_debt_lt is not None else "missing_normalized_to_zero",
                debt_st_status="ok" if raw_debt_st is not None else "missing_normalized_to_zero",
                debt_lt_source=debt_sources["debt_lt"],
                debt_st_source=debt_sources["debt_st"],
            )
        _log_ticker_step(ticker, "deuda_total", debt_value=debt_value)
    else:
        cp_candidates = [idx for idx in bs_indices] if bs is not None and not bs.empty else []
        _log_ticker_step(
            ticker,
            "deuda_no_encontrada",
            cp_candidates="|".join(cp_candidates[:20]) if cp_candidates else "none",
            lt_labels="|".join(DEBT_LABELS_LT),
            st_labels="|".join(DEBT_LABELS_ST),
        )

    inc = stock.financials
    if inc is not None and not inc.empty:
        tax_rate_val, tax_source = get_clean_tax_rate(inc, country)
    else:
        tax_rate_val = STATUTORY_TAX_RATES.get(country, _DAMODARAN_FALLBACK)
        tax_source = f"statutory {country} (IS vacío)"

    beta_levered, beta_source = get_beta(ticker, info)
    market_cap, market_cap_source, market_cap_failure_reason = get_market_cap(info, stock, fx_listing)
    market_cap_key = _find_info_key(info, ["marketCap", "market_cap", "marketcapitalization", "capitalization", "mktCap"])
    if market_cap is None:
        _log_ticker_step(
            ticker,
            "market_cap_missing",
            key_found=market_cap_key,
            sharesOutstanding=info.get("sharesOutstanding"),
            currentPrice=info.get("currentPrice"),
            regularMarketPrice=info.get("regularMarketPrice"),
            previousClose=info.get("previousClose"),
            info_keys_sample="|".join(list(info.keys())[:30]),
        )
    else:
        _log_ticker_step(ticker, "market_cap_raw", key_found=market_cap_key, market_cap=market_cap)

    market_cap_usd = market_cap
    _log_ticker_step(ticker, "market_cap", market_cap=market_cap, market_cap_usd=market_cap_usd, market_cap_source=market_cap_source)

    if market_cap_usd is not None and debt_value is not None:
        total_assets = market_cap_usd + debt_value
    elif market_cap_usd is not None:
        total_assets = market_cap_usd
    _log_ticker_step(ticker, "activo_mercado", total_assets=total_assets)

    de_ratio = None
    if debt_value is not None and market_cap_usd is not None and market_cap_usd != 0:
        de_ratio = debt_value / market_cap_usd
    _log_ticker_step(ticker, "ratio_dc", dc_ratio=de_ratio)

    beta_unlevered = None
    if beta_levered is not None and de_ratio is not None:
        denom = 1 + (1 - tax_rate_val) * de_ratio
        if denom != 0:
            beta_unlevered = beta_levered / denom
            _log_ticker_step(ticker, "beta_unlevered", beta_unlevered=beta_unlevered, denom=denom)
        else:
            _log_ticker_step(ticker, "beta_denom_cero")
    else:
        missing = []
        if beta_levered is None:
            missing.append("beta_levered")
        if de_ratio is None:
            missing.append("dc_ratio")
        _log_ticker_step(ticker, "beta_no_calculado", missing="|".join(missing) if missing else "unknown")

    beta_warning = None
    if beta_unlevered is not None and beta_unlevered < 0:
        beta_warning = "negative_beta_validated"
        _log_ticker_step(
            ticker,
            "beta_negativo_valido",
            beta_levered=beta_levered,
            beta_unlevered=beta_unlevered,
        )

    missing_fields = []
    # Una empresa puede reportar toda su deuda en un solo plazo. Si al menos un
    # componente existe, el ausente ya fue normalizado a cero y no invalida BOA.
    if raw_debt_lt is None and raw_debt_st is None:
        missing_fields.extend(("debt_lt", "debt_st"))
    if debt_value is None:
        missing_fields.append("debt_value")
    if market_cap is None and market_cap_usd is None:
        missing_fields.append("market_cap")
    if beta_levered is None:
        missing_fields.append("beta_levered")
    if de_ratio is None:
        missing_fields.append("dc_ratio")
    if beta_unlevered is None:
        missing_fields.append("beta_unlevered")

    source_diagnostics = {
        "market_cap_source": market_cap_source or market_cap_key or "no_disponible",
        "market_cap_status": "ok" if market_cap is not None else "missing",
        "market_cap_fallback_used": market_cap_source not in ("info.marketCap", "fast_info.market_cap") and market_cap is not None,
        "market_cap_failure_reason": market_cap_failure_reason if market_cap is None else "none",
        "debt_source": (
            f"lt:{debt_sources['debt_lt']}|st:{debt_sources['debt_st']}"
            if debt_value is not None
            else "no_disponible"
        ),
        "debt_status": "ok" if debt_value is not None else "missing",
        "debt_lt_source": debt_sources["debt_lt"],
        "debt_st_source": debt_sources["debt_st"],
        "debt_lt_status": "ok" if raw_debt_lt is not None else "missing_normalized_to_zero",
        "debt_st_status": "ok" if raw_debt_st is not None else "missing_normalized_to_zero",
        "debt_lt_failure_reason": (
            "none"
            if raw_debt_lt is not None
            else "sin_etiqueta_o_valor_en_balance_anual_y_trimestral"
        ),
        "debt_st_failure_reason": (
            "none"
            if raw_debt_st is not None
            else "sin_etiqueta_o_valor_en_balance_anual_y_trimestral"
        ),
        "beta_source": beta_source if beta_levered is not None else "no_disponible",
        "beta_status": "ok" if beta_levered is not None else "missing",
        "beta_warning": beta_warning,
        "financials_source": "financials" if inc is not None and not inc.empty else "financials_vacio",
        "financials_status": "ok" if inc is not None and not inc.empty else "missing",
        "balance_sheet_source": "balance_sheet" if bs is not None and not bs.empty else "balance_sheet_vacio",
        "balance_sheet_status": "ok" if bs is not None and not bs.empty else "missing",
    }

    api_data = {
        "ticker": ticker,
        "company_name": info.get("shortName") or info.get("longName") or ticker,
        "sector": info.get("sector", "Unknown"),
        "country": country,
        "subsector": info.get("industry", info.get("industryDisp", "Unknown")),
        "listing_currency": listing_currency,
        "reporting_currency": reporting_currency,
        "fx_rate": fx_rate,
        "debt_lt": debt_lt if debt_value is not None else None,
        "debt_st": debt_st if debt_value is not None else None,
        "debt_value": debt_value,
        "equity_value": market_cap_usd,
        "total_assets": total_assets,
        "dc_ratio": round(de_ratio, 4) if de_ratio is not None else None,
        "effective_tax_rate": round(tax_rate_val, 4),
        "tax_source": tax_source,
        "beta_levered": round(beta_levered, 4) if beta_levered is not None else None,
        "beta_unlevered": round(beta_unlevered, 4) if beta_unlevered is not None else None,
        "pct_debt": round(debt_value / (debt_value + market_cap_usd), 4) if debt_value is not None and market_cap_usd is not None and (debt_value + market_cap_usd) != 0 else None,
        "pct_equity": round(market_cap_usd / (debt_value + market_cap_usd), 4) if debt_value is not None and market_cap_usd is not None and (debt_value + market_cap_usd) != 0 else None,
        "market_cap": market_cap,
        "missing_fields": missing_fields,
        "diagnostic_reason": "ok" if not missing_fields else "datos_incompletos",
        **source_diagnostics,
    }

    _log_ticker_step(
        ticker,
        "resultado",
        beta_unlevered=api_data["beta_unlevered"],
        dc_ratio=api_data["dc_ratio"],
        total_assets=api_data["total_assets"],
    )

    return None, api_data, {"reason": "ok"}


def _has_complete_values(company: dict) -> bool:
    required_fields = (
        "debt_lt",
        "debt_st",
        "debt_value",
        "equity_value",
        "total_assets",
        "dc_ratio",
        "beta_levered",
        "beta_unlevered",
        "market_cap",
    )
    return not company.get("missing_fields") and all(
        company.get(field) is not None for field in required_fields
    )


def _count_missing_fields(companies: list[dict]) -> dict[str, int]:
    fields = (
        "market_cap",
        "beta_levered",
        "debt_lt",
        "debt_st",
        "debt_value",
        "equity_value",
        "total_assets",
        "dc_ratio",
        "beta_unlevered",
    )
    counts = {field: 0 for field in fields}
    for company in companies:
        for field in fields:
            if company.get(field) is None:
                counts[field] += 1
    return counts


def calcular_boa_ponderado_por_subsector(companies: list[dict]) -> dict:
    """Calcula BOA Ponderado estricto Excel: SUMPRODUCT(Wi, BOA).

    Wi% = activo_mercado_i / Σ(activo_mercado) solo activas.
    Solo empresas con activo_mercado>0 y beta_unlevered válido. Σ Wi =100%.
    toFixed solo display, cálculo intermedio sin redondeo.
    """
    subsectores: dict[str, list[dict]] = {}
    for c in companies:
        sub = c.get("subsector") or "Unknown"
        subsectores.setdefault(sub, []).append(c)

    result = {}
    for sub, empresas in subsectores.items():
        # filtra solo válidas como Excel: activo>0 y beta válido
        validas = [
            e for e in empresas
            if (e.get("total_assets", 0) or 0) > 0
            and e.get("beta_unlevered") is not None
            and str(e.get("beta_unlevered")) != ""
        ]
        if not validas:
            # fallback si ninguna válida, usa todas con activo>0
            validas = [e for e in empresas if (e.get("total_assets", 0) or 0) > 0]
        activos_total = sum(e.get("total_assets", 0) or 0 for e in validas)
        if activos_total == 0:
            result[sub] = {"boa_ponderado": 0.0, "wi_por_empresa": {}}
            continue

        boa_ponderado = 0.0
        wi_map: dict[str, dict] = {}
        for e in validas:
            activos = e.get("total_assets", 0) or 0
            boa = e.get("beta_unlevered", 0) or 0
            wi = activos / activos_total if activos_total > 0 else 0
            boa_ponderado += wi * float(boa)
            wi_map[e.get("ticker", "")] = {
                "wi": round(wi, 6),
                "activo_mercado": activos,
                "beta_unlevered": float(boa),
            }
        result[sub] = {
            "boa_ponderado": round(boa_ponderado, 6),
            "activos_total": activos_total,
            "wi_por_empresa": wi_map,
        }
    return result


def _build_summary_payload(companies: list[dict], total: int, processed_ok: int, failed_count: int) -> dict:
    completed_companies = [company for company in companies if _has_complete_values(company)]
    incomplete_companies = [company for company in companies if not _has_complete_values(company)]
    missing_field_counts = _count_missing_fields(incomplete_companies)
    market_cap_failures = [
        {
            "ticker": company.get("ticker"),
            "reason": company.get("market_cap_failure_reason", "no_disponible"),
            "source": company.get("market_cap_source", "no_disponible"),
        }
        for company in incomplete_companies
        if company.get("market_cap") is None
    ]
    return {
        "total": total,
        "processed": processed_ok,
        "failed": failed_count,
        "complete_count": len(completed_companies),
        "incomplete_count": len(incomplete_companies),
        "complete_tickers": [company["ticker"] for company in completed_companies],
        "incomplete_tickers": [company["ticker"] for company in incomplete_companies],
        "missing_field_counts": missing_field_counts,
        "market_cap_failures": market_cap_failures,
    }


def _detect_stop_reason(
    *,
    total: int,
    processed_ok: int,
    failed_count: int,
    cancel_event: threading.Event,
    job_id: str | None,
) -> str:
    if cancel_event.is_set() or (job_id and is_cancelled(job_id)):
        return "cancelado"
    if processed_ok + failed_count >= total:
        return "finalizado"
    return "interrumpido"


def _log_summary_block(prefix: str, summary: dict):
    missing_field_counts = summary.get("missing_field_counts", {})
    missing_lines = ", ".join(
        f"{key}: {value}" for key, value in missing_field_counts.items() if value
    )
    if not missing_lines:
        missing_lines = "sin faltantes"
    market_cap_failures = summary.get("market_cap_failures", [])
    market_cap_lines = ", ".join(
        f"{item.get('ticker')}: {item.get('reason')}" for item in market_cap_failures if item.get("ticker")
    ) or "sin fallos de market_cap"
    logger.info(
        "%s | TICKERS COMPLETOS: %s | TICKERS CON VALORES FALTANTES: %s | CONTEO DE DATOS NO REGISTRADOS: %s | MARKET CAP FALLAS: %s",
        prefix,
        summary.get("complete_count", 0),
        summary.get("incomplete_count", 0),
        missing_lines,
        market_cap_lines,
    )
    print(
        f"{prefix} | TICKERS COMPLETOS: {summary.get('complete_count', 0)} | "
        f"TICKERS CON VALORES FALTANTES: {summary.get('incomplete_count', 0)} | "
        f"CONTEO DE DATOS NO REGISTRADOS: {missing_lines} | "
        f"MARKET CAP FALLAS: {market_cap_lines}",
        flush=True,
    )


def _log_final_status(job_id: str | None, summary: dict, stop_reason: str):
    payload = {
        "stop_reason": stop_reason,
        "processed": summary.get("processed", 0),
        "failed": summary.get("failed", 0),
        "total": summary.get("total", 0),
        "complete_count": summary.get("complete_count", 0),
        "incomplete_count": summary.get("incomplete_count", 0),
        "missing_field_counts": summary.get("missing_field_counts", {}),
        "complete_tickers": summary.get("complete_tickers", []),
        "incomplete_tickers": summary.get("incomplete_tickers", []),
    }
    logger.info("[BOA][RESULTADO FINAL][%s] %s", job_id, json.dumps(payload, ensure_ascii=False))
    print(f"[BOA][RESULTADO FINAL][{job_id}] {json.dumps(payload, ensure_ascii=False)}", flush=True)


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


def _classify_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "429" in msg or "too many requests" in msg or "rate limit" in msg or "ratelimit" in msg:
        return "rate_limit"
    if "404" in msg or "not found" in msg or "no timezone found" in msg or "possibly delisted" in msg:
        return "ticker_not_found"
    if "502" in msg or "503" in msg or "504" in msg:
        return "upstream_unavailable"
    return "other_error"


def get_shares_from_bs(stock: yf.Ticker) -> float | None:
    for attr in ("balance_sheet", "quarterly_balance_sheet"):
        try:
            bs = getattr(stock, attr)
        except Exception:
            bs = None
        if bs is None or bs.empty:
            continue
        val = first_valid(bs, SHARE_LABELS)
        if val is not None and val > 0:
            return val
    return None


def get_market_cap(info: dict, stock: yf.Ticker, fx_listing: float) -> tuple[float | None, str, str]:
    mc = info.get("marketCap")
    if mc:
        return mc * fx_listing, "info.marketCap", "info.marketCap"

    try:
        fi = stock.fast_info
        mc = getattr(fi, "market_cap", None)
        if mc and mc > 0:
            return mc * fx_listing, "fast_info.market_cap", "fast_info.market_cap"
    except Exception as exc:
        logger.info("fast_info falló para marketCap: %s", exc)

    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or info.get("floatShares")
    if shares is None:
        shares = get_shares_from_bs(stock)
    if price and shares:
        return price * shares * fx_listing, "precio_x_shares", "precio_x_shares"
    if price is None and shares is None:
        reason = "sin_price_y_shares"
    elif price is None:
        reason = "sin_price"
    elif shares is None:
        reason = "sin_shares"
    else:
        reason = "no_disponible"
    return None, "no_disponible", reason


def get_beta_historico(ticker_symbol: str, periodo: str = "36mo") -> float | None:
    try:
        raw = yf.download(
            [ticker_symbol, "^GSPC"],
            period=periodo,
            interval="1mo",
            auto_adjust=True,
            progress=False,
        )["Close"]
        if isinstance(raw, pd.Series):
            raw = raw.to_frame(ticker_symbol)
        ret = raw.pct_change().dropna()
        if ticker_symbol not in ret.columns or "^GSPC" not in ret.columns:
            return None
        cov = ret[[ticker_symbol, "^GSPC"]].cov()
        beta = cov.loc[ticker_symbol, "^GSPC"] / cov.loc["^GSPC", "^GSPC"]
        if pd.notna(beta):
            return float(beta)
    except Exception as exc:
        logger.info("Beta OLS fallido para %s: %s", ticker_symbol, exc)
    return None


def get_beta(ticker_symbol: str, info: dict) -> tuple[float | None, str]:
    beta = info.get("beta")
    if beta is not None:
        return float(beta), "yfinance"

    base = ticker_symbol.split(".")[0]
    if base != ticker_symbol:
        try:
            alt_info = yf.Ticker(base).info
            beta = alt_info.get("beta")
            if beta is not None:
                return float(beta), f"yfinance ({base})"
        except Exception as exc:
            logger.info("beta fallback ticker base falló para %s: %s", ticker_symbol, exc)

    beta = get_beta_historico(ticker_symbol)
    if beta is not None:
        return beta, "regresion OLS 36m"

    if base != ticker_symbol:
        beta = get_beta_historico(base)
        if beta is not None:
            return beta, f"regresion OLS 36m ({base})"

    return None, "no disponible"


def extract_company_rows_from_xlsx(file_content: bytes) -> list[dict]:
    if not file_content:
        return []

    df = pd.read_excel(pd.io.common.BytesIO(file_content))
    ticker_col = next((c for c in df.columns if str(c).strip().lower() == "empresa"), None)
    if ticker_col is None:
        raise ValueError("El archivo no contiene la columna 'Empresa'.")

    sector_col = next((c for c in df.columns if str(c).strip().lower() == "sector"), None)
    subsector_col = next((c for c in df.columns if str(c).strip().lower() == "subsector"), None)
    company_name_col = next(
        (
            c for c in df.columns
            if str(c).strip().lower() in ("nombre empresa", "nombre de empresa", "razón social", "razon social", "company name")
        ),
        None,
    )

    rows: list[dict] = []
    for _, row in df.iterrows():
        raw_ticker = row.get(ticker_col)
        if pd.isna(raw_ticker):
            continue
        ticker = str(raw_ticker).strip().upper()
        if not ticker:
            continue
        rows.append({
            "ticker": ticker,
            "sector": str(row.get(sector_col)).strip() if sector_col and not pd.isna(row.get(sector_col)) else None,
            "subsector": str(row.get(subsector_col)).strip() if subsector_col and not pd.isna(row.get(subsector_col)) else None,
            "company_name": str(row.get(company_name_col)).strip() if company_name_col and not pd.isna(row.get(company_name_col)) else None,
        })
    return rows


def extract_first_companies_from_xlsx(file_content: bytes, limit: int | None = BOA_DEBUG_DEFAULT_LIMIT) -> list[str]:
    """
    Lee el XLSX de subsectores y extrae empresas únicas de forma aleatoria.
    Si `BOA_DEBUG_RANDOM_SEED` se define, la selección es reproducible.
    """
    if not file_content:
        return []

    df = pd.read_excel(pd.io.common.BytesIO(file_content))
    if "Empresa" not in df.columns:
        raise ValueError("El archivo no contiene la columna 'Empresa'.")

    tickers: list[str] = []
    seen: set[str] = set()
    for raw_value in df["Empresa"].tolist():
        if pd.isna(raw_value):
            continue
        ticker = str(raw_value).strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)

    if not tickers:
        return []

    if limit is None:
        return tickers

    rng = random.Random(BOA_DEBUG_RANDOM_SEED)
    if len(tickers) <= limit:
        rng.shuffle(tickers)
        return tickers

    return rng.sample(tickers, limit)


def calculate_subsectores_boa(
    tickers: list[str] | list[dict],
    job_id: str | None = None,
    batch_size: int = 50,
    max_companies: int | None = None,
    save_to_db: bool = True,
    emit_ticker_logs: bool = False,
) -> dict:
    global BOA_LOG_TICKER_STEPS
    if tickers and isinstance(tickers[0], dict):
        ticker_rows = tickers  # type: ignore[assignment]
        ticker_symbols = [str(item.get("ticker", "")).strip().upper() for item in ticker_rows if item.get("ticker")]
    else:
        ticker_rows = [{"ticker": t, "sector": None, "subsector": None} for t in tickers]  # type: ignore[list-item]
        ticker_symbols = [str(t).strip().upper() for t in tickers]  # type: ignore[list-item]
    companies = []
    errors = []
    ticker_table_rows = []
    processed_ok = 0
    failed_count = 0
    rate_limit_hits = 0
    last_error_reason = None
    empty_batch_tickers: list[str] = []
    cancel_event = threading.Event()

    if job_id:
        _running_jobs[job_id] = cancel_event

    if max_companies is not None:
        ticker_rows = ticker_rows[:max_companies]
        ticker_symbols = ticker_symbols[:max_companies]

    t_start = time.perf_counter()
    previous_log_state = BOA_LOG_TICKER_STEPS
    BOA_LOG_TICKER_STEPS = emit_ticker_logs
    logger.info(
        f"Procesando {len(ticker_rows)} tickers en lotes de {batch_size} "
        f"(save_to_db={save_to_db}, emit_ticker_logs={emit_ticker_logs})..."
    )

    total_batches = (len(ticker_rows) + batch_size - 1) // batch_size
    last_batch = -1
    last_summary_log = time.perf_counter()
    requests_since_pause = 0
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

        batch_start = batch_idx * batch_size
        batch_end = min(batch_start + batch_size, len(ticker_rows))
        batch_tickers = ticker_rows[batch_start:batch_end]
        batch_companies = []

        logger.info(f"Lote {batch_idx + 1}/{total_batches} (tickers {batch_start + 1}-{batch_end})")

        for i, ticker_row in enumerate(batch_tickers):
            ticker = ticker_row["ticker"]
            company_name_hint = ticker_row.get("company_name") or ticker_row.get("nombre_empresa")
            ticker_resolution = resolve_ticker_symbol(
                ticker,
                company_name_hint,
                search_candidates=False,
            )
            processing_ticker = ticker_resolution.get("ticker_resolved") or ticker
            if processing_ticker != ticker:
                logger.info(
                    "[BOA][TICKER RESUELTO] original=%s actual=%s motivo=%s fuente=%s",
                    ticker,
                    processing_ticker,
                    ticker_resolution["ticker_resolution_reason"],
                    ticker_resolution["ticker_resolution_source"],
                )
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
                    res = _process_single_ticker(processing_ticker, cancel_event)
                    if res is not None:
                        _, api_data, diag = res
                        last_error_reason = diag.get("reason") if isinstance(diag, dict) else None
                        if api_data is not None:
                            api_data["ticker"] = ticker
                            api_data.update(ticker_resolution)
                            break

                        diagnostic_error = (
                            diag.get("error")
                            if isinstance(diag, dict)
                            else None
                        )
                        last_error = {
                            "ticker": ticker,
                            "mensaje": (
                                f"Intento {attempt + 1}/3: "
                                f"{diagnostic_error or last_error_reason or 'No se pudo resolver'}"
                            ),
                        }
                        if last_error_reason == "ticker_not_found":
                            if ticker_resolution.get("ticker_resolution_status") != "resolved":
                                ticker_resolution = resolve_ticker_symbol(
                                    ticker,
                                    company_name_hint,
                                    search_candidates=True,
                                )
                                resolved_ticker = ticker_resolution.get("ticker_resolved")
                                if resolved_ticker:
                                    processing_ticker = resolved_ticker
                                    logger.info(
                                        "[BOA][TICKER RESUELTO] original=%s actual=%s motivo=%s fuente=%s candidatos=%s",
                                        ticker,
                                        processing_ticker,
                                        ticker_resolution["ticker_resolution_reason"],
                                        ticker_resolution["ticker_resolution_source"],
                                        json.dumps(ticker_resolution["ticker_resolution_candidates"], ensure_ascii=False),
                                    )
                                    continue
                            last_error.update(ticker_resolution)
                            last_error["mensaje"] = (
                                f"Intento {attempt + 1}/3: ticker no vigente o no encontrado; "
                                f"resolución={ticker_resolution['ticker_resolution_status']}"
                            )
                            break
                        if last_error_reason == "cancelled":
                            cancel_event.set()
                            break
                        if last_error_reason == "rate_limit":
                            rate_limit_hits += 1
                            break
                        if attempt < 2:
                            _delay(1.0)
                            continue
                        break
                except Exception as exc:
                    err_msg = str(exc).lower()
                    last_error_reason = _classify_error(exc)
                    last_error = {
                        "ticker": ticker,
                        "mensaje": f"Intento {attempt + 1}/3: Error - {str(exc)}",
                    }
                    if "rate" in err_msg or "limit" in err_msg or "429" in err_msg or "too many" in err_msg:
                        rate_limit_hits += 1
                        _rate_limit_delay(attempt)
                    elif attempt < 2:
                        _delay(1.0)
                    continue

            row_payload = {
                "ticker": ticker,
                "sector": ticker_row.get("sector"),
                "subsector": ticker_row.get("subsector"),
                "status": "ok" if api_data else "missing",
                "missing_fields": [],
                "diagnostic_reason": "ok" if api_data else "missing",
                **ticker_resolution,
            }
            if api_data:
                row_payload.update(api_data)
                companies.append(api_data)
                batch_companies.append(api_data)
                processed_ok += 1
                if emit_ticker_logs:
                    logger.info("RESULTADO_EMPRESA=%s", json.dumps(api_data, ensure_ascii=False))
            elif last_error:
                failed_count += 1
                errors.append(last_error)
                if emit_ticker_logs:
                    logger.info("ERROR_EMPRESA=%s", json.dumps(last_error, ensure_ascii=False))
                if last_error_reason == "rate_limit":
                    logger.warning(
                        "Rate limit confirmado en ticker %s. Abortando para evitar saturación.", ticker
                    )
                    cancel_event.set()
                row_payload["status"] = last_error_reason or "error"
                row_payload["diagnostic_reason"] = last_error_reason or "error"
                row_payload["error_message"] = last_error.get("mensaje")
                row_payload["error_reason"] = last_error_reason or "error"
                row_payload["missing_fields"] = [
                    "market_cap",
                    "beta_levered",
                    "debt_lt",
                    "debt_st",
                    "debt_value",
                    "equity_value",
                    "total_assets",
                    "dc_ratio",
                    "beta_unlevered",
                ]
                if last_error_reason == "unknown":
                    row_payload["diagnostic_reason"] = "error_respuesta_o_datos"

            ticker_table_rows.append(row_payload)

            if job_id:
                update_job_progress(
                    job_id,
                    processed=processed_ok,
                    failed=failed_count,
                    errors=errors,
                )

            if api_data or last_error:
                requests_since_pause += 1
                if requests_since_pause >= 25 and batch_idx < total_batches - 1 and not cancel_event.is_set():
                    logger.info("Pausa preventiva: 25 solicitudes completadas. Esperando 15s antes de continuar...")
                    time.sleep(15)
                    requests_since_pause = 0

        if save_to_db and batch_companies:
            _upsert_companies_to_db(batch_companies, job_id=job_id or "", batch_idx=batch_idx)
        elif batch_tickers and not batch_companies:
            empty_batch_tickers.extend(
                [
                    str(item.get("ticker", "")).strip().upper()
                    for item in batch_tickers
                    if isinstance(item, dict) and item.get("ticker")
                ]
            )

        if job_id:
            progress_missing_counts = _count_missing_fields(companies)
            progress_summary = _build_summary_payload(companies, len(tickers), processed_ok, failed_count)
            progress_summary["missing_field_counts"] = progress_missing_counts
            progress_summary["empty_batch_tickers"] = empty_batch_tickers
            progress_summary["ticker_rows"] = ticker_table_rows
            _update_job(job_id, result={
                "valid_companies": companies,
                "errors": errors,
                **progress_summary,
            }, last_batch=batch_idx)
            now = time.perf_counter()
            if now - last_summary_log >= 300:
                _log_summary_block(f"[BOA][RESUMEN 5MIN][{job_id}]", progress_summary)
                last_summary_log = now

        if batch_idx < total_batches - 1 and not cancel_event.is_set() and requests_since_pause < 25:
            batch_delay = 5
            logger.info(f"Esperando {batch_delay}s antes del siguiente lote...")
            time.sleep(batch_delay)

    t_end = time.perf_counter()
    logger.info(f"BOA completado en {t_end - t_start:.2f}s (job={job_id}) - {processed_ok} ok, {failed_count} failed")
    BOA_LOG_TICKER_STEPS = previous_log_state

    stop_reason = _detect_stop_reason(
        total=len(tickers),
        processed_ok=processed_ok,
        failed_count=failed_count,
        cancel_event=cancel_event,
        job_id=job_id,
    )
    if stop_reason == "interrumpido" and rate_limit_hits > 0:
        stop_reason = "rate_limit"
    boa_ponderado_data = calcular_boa_ponderado_por_subsector(companies) if companies else {}
    result = {
        "success": True,
        "valid_companies": [],
        "errors": errors,
        "total": len(tickers),
        "processed": processed_ok,
        "failed": failed_count,
        "stop_reason": stop_reason,
        "empty_batch_tickers": empty_batch_tickers,
        **_build_summary_payload(companies, len(ticker_rows), processed_ok, failed_count),
        "ticker_rows": ticker_table_rows,
        "boa_ponderado_por_subsector": boa_ponderado_data,
    }
    _log_summary_block(f"[BOA][RESULTADO FINAL][{job_id}]", result)
    _log_final_status(job_id, result, stop_reason)

    if job_id:
        if stop_reason == "finalizado":
            complete_job(job_id, result)
        else:
            fail_job(job_id, f"Proceso no completado ({stop_reason})")
            _update_job(job_id, result=result)
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
