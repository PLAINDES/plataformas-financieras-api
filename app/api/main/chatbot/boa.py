# app/api/chatbot/boa.py
"""
──────────────────────────────────────────────────────────────────────────────
Beta Industry Calculator — Ponderado por Activos Totales (USD)
──────────────────────────────────────────────────────────────────────────────
Mejoras v3:
  • Tasa impositiva robusta: detecta años anómalos por unusual items
    y busca automáticamente el año más reciente sin distorsión.
  • Override manual TAX_OVERRIDES para casos irrecuperables.
  • Tabla final con columnas: Deuda, Equity, Activos, Peso, D/E, IR, B_L, B_U, %D, %C
  • HRK eliminada (Croacia adoptó EUR en 2023).

Ajustes post-pruebas (v3.1):
  • FX: rango mínimo bajado a 0.000001 para cubrir IDR, VND y similares.
  • HK agregado a STATUTORY_TAX_RATES (16.5%).
  • f-string del resumen final corregido (B_U no formateaba si era None).
  • fmt() definida una sola vez fuera del loop (evita redefinición en cada iter).
  • de_ratio: guard contra equity_value == 0 para evitar división por cero.
  • Ponderación: wpond() excluye filas con NaN en la columna a ponderar
    usando los activos solo de las filas válidas (sin sesgo de denominador).
──────────────────────────────────────────────────────────────────────────────
"""

import concurrent.futures, random, logging, time
import yfinance as yf
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# CONSTANTES
# Solo para casos irrecuperables - Formato: "TICKER": (tasa, "razón")

TAX_OVERRIDES: dict[str, tuple[float, str]] = {
    # "1742.HK": (0.165, "statutory HK — todos los años con unusual alto"),
}

# Tasas statutory por país (último recurso)
STATUTORY_TAX_RATES: dict[str, float] = {
    "SE": 0.206, "NO": 0.22,  "DK": 0.22,  "FI": 0.20,
    "DE": 0.30,  "FR": 0.25,  "NL": 0.258, "GB": 0.25,
    "CA": 0.265, "AU": 0.30,  "MY": 0.24,  "HK": 0.165,
    "SG": 0.17,  "PL": 0.19,  "US": 0.21,  "BE": 0.25,
    "JP": 0.304, "CN": 0.25,  "IN": 0.258, "KR": 0.22,
    "ID": 0.22,  "TH": 0.20,  "PH": 0.25,  "TW": 0.20,
}

CURRENCY_PAIRS_INIT = [
    "CAD", "MXN", "BRL", "ARS", "CLP", "COP", "PEN", "UYU",
    "EUR", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK",
    "HUF", "RON", "TRY",                          # HRK eliminada (EUR desde 2023)
    "JPY", "CNY", "HKD", "SGD", "KRW", "TWD", "INR", "MYR",
    "THB", "IDR", "PHP", "VND", "AUD", "NZD",
    "AED", "SAR", "ILS", "ZAR", "EGP", "NGN", "KWD", "QAR",
]

UNUSUAL_THRESHOLD = 0.30   # unusual/pretax > 30% → año sospechoso
TAX_MAX           = 0.60   # tasa > 60% → anómala

EQUITY_LABELS = [
    "Stockholders Equity",
    "Total Stockholder Equity",
    "Total Equity Gross Minority Interest",
    "Common Stock Equity",
]
DEBT_LABELS = [
    "Long Term Debt",
    "Long Term Debt And Capital Lease Obligation",
    "Debt Long Term Total",
]
TOTAL_ASSETS_LABELS = [
    "Total Assets",
    "Total Assets As Reported",
]

# HELPERS
# 1. FUNCIÓN DE TIPO DE CAMBIO

def get_fx_rate(currency: str, fx_cache: dict) -> float:
    currency = currency.upper().strip()
    if currency in fx_cache:
        return fx_cache[currency]
    pair = f"{currency}USD=X"
    try:
        hist = yf.Ticker(pair).history(period="5d")
        if hist.empty:
            raise ValueError("Sin datos")
        rate = float(hist["Close"].dropna().iloc[-1])
        # Rango ampliado a 0.000001 para cubrir IDR (~0.000061), VND (~0.000040), etc.
        if 0.000001 <= rate <= 200.0:
            fx_cache[currency] = rate
            return rate
        else:
            fx_cache[currency] = 1.0
            return 1.0
    except Exception:
        fx_cache[currency] = 1.0
        return 1.0

def first_valid(df: pd.DataFrame, labels: list) -> float | None:
    """Devuelve el primer valor no-NaN encontrado entre los labels dados."""
    for lbl in labels:
        if lbl in df.index:
            val = df.loc[lbl].iloc[0]
            if pd.notna(val):
                return float(val)
    return None



def get_clean_tax_rate(inc: pd.DataFrame, ticker: str, country: str) -> tuple[float, str]:
    """
    Busca la tasa impositiva más limpia disponible:
      1. Recorre columnas de más reciente a más antigua.
      2. Descarta años con pretax <= 0 o unusual/pretax > UNUSUAL_THRESHOLD.
      3. Descarta años con tasa calculada fuera de [0, TAX_MAX].
      4. Devuelve (tasa, fuente) describiendo qué año/método se usó.
    """
    pretax_label = "Pretax Income" if "Pretax Income" in inc.index else "Income Before Tax" if "Income Before Tax" in inc.index else None
    tax_label = "Tax Provision" if "Tax Provision" in inc.index else "Income Tax Expense" if "Income Tax Expense" in inc.index else None
    unusual_label = "Total Unusual Items" if "Total Unusual Items" in inc.index else None

    if pretax_label is None or tax_label is None:
        statutory = STATUTORY_TAX_RATES.get(country, 0.27)
        return statutory, f"statutory {country} (sin labels IS)"

    for col in inc.columns:
        year = str(col)[:10]

        pre = inc.loc[pretax_label, col]
        tax = inc.loc[tax_label,    col]
        unu = inc.loc[unusual_label, col] if unusual_label else None

        pre = float(pre) if pd.notna(pre) else None
        tax = float(tax) if pd.notna(tax) else None
        unu = float(unu) if (unu is not None and pd.notna(unu)) else 0.0

        if pre is None or pre <= 0:
            continue

        unusual_ratio = abs(unu / pre)
        if unusual_ratio > UNUSUAL_THRESHOLD:
            continue

        if tax is None:
            continue

        tasa = tax / pre
        if tasa < 0 or tasa > TAX_MAX:
            continue

        return tasa, f"año {year} (unusual={unusual_ratio:.1%})"

    statutory = STATUTORY_TAX_RATES.get(country, 0.27)
    return statutory, f"statutory {country} (todos los años descartados)"


# PRE-CARGA DE MONEDAS

global_fx_pairs = {"USD": 1.0}
for _cur in CURRENCY_PAIRS_INIT:
    try:
        _hist = yf.Ticker(f"{_cur}USD=X").history(period="5d")
        if not _hist.empty:
            global_fx_pairs[_cur] = float(_hist["Close"].dropna().iloc[-1])
        else:
            global_fx_pairs[_cur] = 1.0
    except Exception:
        global_fx_pairs[_cur] = 1.0


# ════════════════════════════════════
# 5. HELPERS
# ════════════════════════════════════


def fmt(v, fmt_str: str) -> str:
    """Formatea v con fmt_str si no es None, de lo contrario devuelve 'N/D'."""
    return format(v, fmt_str) if v is not None else "N/D"


def _process_single_ticker(ticker: str):
    """Procesa un único ticker. Retorna (raw_data_pandas, api_data_frontend)."""
    time.sleep(random.uniform(0.1, 0.5))

    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
    except Exception:
        return None

    listing_currency = info.get("currency", "USD")
    reporting_currency = info.get("financialCurrency", listing_currency)
    
    fx_rate = get_fx_rate(reporting_currency, global_fx_pairs)
    # Se añade la tasa de conversion especifica para la capitalizacion de mercado
    fx_listing = get_fx_rate(listing_currency, global_fx_pairs)

    country = info.get("country", "")

    bs = stock.balance_sheet
    equity_value, debt_value, total_assets = None, None, None

    if bs is not None and not bs.empty:
        raw_eq = first_valid(bs, EQUITY_LABELS)
        if raw_eq is not None:
            equity_value = raw_eq * fx_rate

        raw_debt = first_valid(bs, DEBT_LABELS)
        if raw_debt is not None:
            debt_value = raw_debt * fx_rate

        raw_ta = first_valid(bs, TOTAL_ASSETS_LABELS)
        if raw_ta is not None:
            total_assets = raw_ta * fx_rate
        elif equity_value is not None and debt_value is not None:
            total_assets = equity_value + debt_value


    # Tasa Impositiva robusta
    inc = stock.financials

    if ticker in TAX_OVERRIDES:
        tax_rate_val, tax_source = TAX_OVERRIDES[ticker]
    elif inc is not None and not inc.empty:
        tax_rate_val, tax_source = get_clean_tax_rate(inc, ticker, country)
    else:
        tax_rate_val = STATUTORY_TAX_RATES.get(country, 0.27)
        tax_source = f"statutory {country} (IS vacío)"

    # Beta y D/E
    beta_levered = info.get("beta", None)
    market_cap = info.get("marketCap", None)

    # Conversion de Market Cap a USD usando la moneda de cotizacion
    market_cap_usd = market_cap * fx_listing if market_cap is not None else None

    # Calculo de D/E ratio basado en Market Cap
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

    print(f"Ticker {ticker}: Boa: beta_unlevered={fmt(beta_unlevered, '.4f')}")

    # PORCENTAJES DE ESTRUCTURA DE CAPITAL ORIGINALES
    pct_debt   = None
    pct_equity = None
    if debt_value is not None and market_cap_usd is not None:
        total_cap  = debt_value + market_cap_usd
        if total_cap != 0:
            pct_debt   = debt_value   / total_cap
            pct_equity = market_cap_usd / total_cap

    # GUARDAMOS PARA PANDAS
    raw_data = ({
        "Ticker": ticker,
        "Moneda cotización": listing_currency,
        "Moneda EE.FF": reporting_currency,
        "FX (→ USD)": fx_rate,
        "Deuda LP (USD)": debt_value,
        "Equity (USD)": market_cap_usd,
        "Total Activos (USD)": total_assets,
        "D/E Ratio": de_ratio,
        "Tasa Impositiva": tax_rate_val,
        "Fuente Tasa": tax_source,
        "Beta Levered": beta_levered,
        "Beta Unlevered": beta_unlevered,
        "%Deuda": pct_debt,
        "%Equity": pct_equity,
        "Market Cap": market_cap,
        "País": country,
    })

    api_data = None
    if beta_levered is not None and de_ratio is not None:
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
            "dc_ratio": round(de_ratio, 4),
            "effective_tax_rate": round(tax_rate_val, 4),
            "tax_source": tax_source,
            "beta_levered": round(beta_levered, 4),
            "beta_unlevered": round(beta_unlevered, 4) if beta_unlevered else 0.0,
            "pct_debt": pct_debt,
            "pct_equity": pct_equity,
            "market_cap": market_cap
        }

    return raw_data, api_data

def calculate_sector_beta(target_tickers: list[str]) -> dict:
    results = []
    api_companies = []

    t_start_batch = time.perf_counter()
    print(f"Procesando {len(target_tickers)} tickers concurrentemente...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # Enviamos las tareas al pool
        futures_map = {executor.submit(_process_single_ticker, ticker): ticker for ticker in target_tickers}

        # Recogemos los resultados conforme vayan terminando
        for future in concurrent.futures.as_completed(futures_map):
            res = future.result()
            if res:
                raw_data, api_data = res
                results.append(raw_data)
                if api_data:
                    api_companies.append(api_data)

    t_end_batch = time.perf_counter()
    print(f"Operacion concurrente completada en {t_end_batch - t_start_batch:.2f}s")

    # PONDERACIÓN
    df = pd.DataFrame(results)
    if df.empty:
        return {"success": False, "valid_companies": [], "group_statistics": None}

    df_valid = df.dropna(subset=["Total Activos (USD)", "Beta Levered"]).copy()
    total_assets_sum = df_valid["Total Activos (USD)"].sum()

    w_bl, w_de, w_tx, w_bu = 0.0, 0.0, 0.0, 0.0
    if total_assets_sum > 0 and not df_valid.empty:
        df_valid["Peso (%)"] = df_valid["Total Activos (USD)"] / total_assets_sum

        def wpond(col: str) -> float:
            """
            Promedio ponderado de `col` usando solo filas donde `col` no es NaN.
            Los pesos se renormalizan sobre esas filas para evitar sesgo de denominador.
            """
            mask = df_valid[col].notna()
            if not mask.any():
                return float("nan")
            activos_validos = df_valid.loc[mask, "Total Activos (USD)"]
            pesos = activos_validos / activos_validos.sum()
            return (df_valid.loc[mask, col] * pesos).sum()

        w_bl = wpond("Beta Levered")
        w_de = wpond("D/E Ratio")
        w_tx = wpond("Tasa Impositiva")

        denom_bu = 1 + (1 - w_tx) * w_de
        w_bu = w_bl / denom_bu if denom_bu != 0 else 0.0

    return {
        "success": True,
        "valid_companies": api_companies,
        "group_statistics": {
            "avg_beta_unlevered": round(w_bu, 4) if not np.isnan(w_bu) else 0.0,
            "avg_dc_ratio": round(w_de, 4) if not np.isnan(w_de) else 0.0,
            "avg_tax_rate": round(w_tx, 4) if not np.isnan(w_tx) else 0.0
        }
    }
