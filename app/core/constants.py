# app/core/constants.py

# AWS Constants
AWS_BASE_PREFIX = "plataformas_financieras"

# Master template sheets
TEMPLATE_SHEET_VALORA = "Plantilla Usuario"
TEMPLATE_SHEET_KAPITAL = "WACC"
# Hoja "Reporte": contiene códigos y gráficos exportados. Se asigna a kapital
# mientras se valida el pipeline; al soportar valora se clasificará por prefijo.
TEMPLATE_SHEET_REPORTE = "Reporte"

TEMPLATE_SHEET_TO_TYPE = {
    TEMPLATE_SHEET_VALORA: "valora",
    TEMPLATE_SHEET_KAPITAL: "kapital",
    TEMPLATE_SHEET_REPORTE: "kapital",
}


# Kapital workbook mapping
KAPITAL_INPUT_SHEET = "Plantilla Usuario"
KAPITAL_RESULTS_SHEET = "WACC"
KAPITAL_RESULTS_BOA_CELL = "F24"
KAPITAL_RESULTS_BOA_SECTOR_CELL = "F22"
KAPITAL_RESULTS_BOA_SUBSECTOR_CELL = "F23"

KAPITAL_EXPECTED_DEVALUATION = "C16"

# KAPITAL_SENSITIVITY_INPUT_CELL_MAP = {
#     "beta_desapalancado": "C12",
# }
KAPITAL_SENSITIVITY_INPUT_CELL_MAP = {}

KAPITAL_CUSTOM_INPUT_CELL_MAP = {
    "beta_subsector": "F24",
    "beta_subsector_alt": "F40",
}

# Hoja PLANTILLA USUARIO
KAPITAL_INPUT_CELL_MAP = {
    "fecha": "C2",
    "pais": "C3",
    "moneda": "C4",
    "industria": "C5",
    "tasa_libre_riesgo": "C6",
    "anio_bono": "C7",
    "costo_deuda": "C9",
    "porcentaje_deuda": "C10",
}

# Hoja WACC
KAPITAL_INPUT_WACC = {
    "tasa_impositiva": "F13",
    "devaluacion": "F14",
    "industria": "B18",
    "subsector": "B19",
    "porcentaje_deuda": "F12"
}

# Hoja WACC
KAPITAL_RESULTS_CELL_MAP = {
    "mercado_desarrollado": {
        "ke": "D47",
        "koa": "D48",
        "kd": "D49",
        "cppc": "D50",
        "kd(1-t)": "D51",
        "d_empresa": "D52",
    },
    "mercado_emergente_dolares": {
        "ke": "E47",
        "koa": "E48",
        "kd": "E49",
        "cppc": "E50",
        "kd(1-t)": "E51",
        "d_empresa": "E52",
    },
    "mercado_emergente_moneda_local": {
        "ke": "F47",
        "koa": "F48",
        "kd": "F49",
        "cppc": "F50",
        "kd(1-t)": "F51",
        "d_empresa": "F52",
    },
    "empresa_dolares": {
        "ke": "G47",
        "koa": "G48",
        "kd": "G49",
        "cppc": "G50",
        "kd(1-t)": "G51",
        "d_empresa": "G52",
    },
    "empresa_moneda_local": {
        "ke": "H47",
        "koa": "H48",
        "kd": "H49",
        "cppc": "H50",
        "kd(1-t)": "H51",
        "d_empresa": "H52",
    },
}
# Hoja WACC
KAPITAL_SENSITIVITY_CELL_MAP = {
    "mercado_desarrollado": {
        "ke": "D67",
        "koa": "D68",
        "kd": "D69",
        "cppc": "D70",
        "kd(1-t)": "D71",
        "d_empresa": "D72",
    },
    "mercado_emergente_dolares": {
        "ke": "E67",
        "koa": "E68",
        "kd": "E69",
        "cppc": "E70",
        "kd(1-t)": "E71",
        "d_empresa": "E72",
    },
    "mercado_emergente_moneda_local": {
        "ke": "F67",
        "koa": "F68",
        "kd": "F69",
        "cppc": "F70",
        "kd(1-t)": "F71",
        "d_empresa": "F72",
    },
    "empresa_dolares": {
        "ke": "G67",
        "koa": "G68",
        "kd": "G69",
        "cppc": "G70",
        "kd(1-t)": "G71",
        "d_empresa": "G72",
    },
    "empresa_moneda_local": {
        "ke": "H67",
        "koa": "H68",
        "kd": "H69",
        "cppc": "H70",
        "kd(1-t)": "H71",
        "d_empresa": "H72",
    },
}



# Hoja WACC
KAPITAL_DAMODARAN_CELL_MAP = {
    "number_of_firms": "D18",
    "beta": "E18",
    "cost_of_equity": "F18",
    "e_sobre_de": "G18",
    "std_dev_stock": "H18",
    #"cost_of_debt": "H36",
    #"tax_rate": "I36",
    #"after_tax_cost_of_debt": "J36",
    #"d_sobre_def": "K36",
    #"cost_of_capital": "L36",
    #"cost_of_capital_local": "M36",
}

# Hoja WACC
KAPITAL_PRIMA_CELL_MAP = {
    #"fecha": "B52",
    "PRM Kroll": "F7",
}

# Hoja WACC
KAPITAL_EMBI_CELL_MAP = {
    "country": "F11",
}

# Hoja WACC
KAPITAL_RF_CELL_MAP = {
    "year": "F6"
}

# Hoja WACC
KAPITAL_TAX_CELL_MAP = {
    "global_default_spread": "F8",
    "tax_rate": "F9"
}

# Hoja WACC
KAPITAL_RIESGO_CELL_MAP = {
    "num1_basis_spread": "J8",
    "num2_basis_spread": "J9",
    "num3_basis_spread": "J10",
    "num4_basis_spread": "J11",
    "num5_basis_spread": "J12",
    "num6_basis_spread": "J13",
    "num7_basis_spread": "J14",
    "num1_max_deviation": "I8",
    "num1_min_deviation": "H8",
    "num2_max_deviation": "I9",
    "num2_min_deviation": "H9",
    "num3_max_deviation": "I10",
    "num3_min_deviation": "H10",
    "num4_max_deviation": "I11",
    "num4_min_deviation": "H11",
    "num5_max_deviation": "I12",
    "num5_min_deviation": "H12",
    "num6_max_deviation": "I13",
    "num6_min_deviation": "H13",
    "num7_max_deviation": "I14",
    "num7_min_deviation": "H14",
}

COUNTRY_LOCAL_CURRENCIES = {
    "Argentina": "ARS",
    "Brazil": "BRL",
    "Mexico": "MXN",
    "Chile": "CLP",
    "Colombia": "COP",
    "Ecuador": "USD",
    "Peru": "PEN",
}

VALORA_INPUT_CELL_MAP = {
    "fecha": "C2",
    "pais": "C3",
    "moneda": "C4",
    "industria": "C5",
    "tasa_libre_riesgo": "C6",
    "anio_bono": "C7",
    "shares": "C8",
    "costo_deuda": "C9",
    "porcentaje_deuda": "C10",
}

VALORA_PROJECTION_INPUT_CELL_MAP = {
    # M91 contiene fórmulas de la plantilla; no se sobreescribe.
    # "revenue_forecast_rate": "M91",
    "perpetual_growth_rate": "F81",
}

VALORA_INTEGRATED_INPUT_CELL_MAP = {
    # M7 y M10 contienen fórmulas de la plantilla; no se sobreescriben.
    # "fdc_forecast_rate": "M10",
}

VALORA_RESULTS_CELL_MAP = {
    "wacc": ("Conceptos", "C23"),
    "wacc_emergente": ("Conceptos", "D23"),
    "balance": {
        "activo": ("Proyección", "L18"),
        "pasivo": ("Proyección", "L29"),
        "patrimonio": ("Proyección", "L34"),
    },
    "conceptos": {
        "activo": ("Conceptos", "Q24"),
        "pasivo": ("Conceptos", "Q26"),
        "empresa": ("Conceptos", "Q25"),
        "patrimonio": ("Conceptos", "Q27"),
        "precio_accion": ("Conceptos", "Q28"),
        "tasa_forecast": ("Conceptos", "T31"),
        "tasa_perpetua": ("Conceptos", "T32"),
    },
    "integrado": {
        "activo": ("Integrado", "P34"),
        "pasivo": ("Integrado", "P36"),
        "empresa": ("Integrado", "P35"),
        "patrimonio": ("Integrado", "P37"),
        "precio_accion": ("Integrado", "P38"),
        "tasa_forecast": ("Integrado", "S40"),
        "tasa_perpetua": ("Integrado", "S41"),
    },
    "conceptos_emergente": {
        "activo": ("Conceptos", "S25"),
        "pasivo": ("Conceptos", "S27"),
        "empresa": ("Conceptos", "S26"),
        "patrimonio": ("Conceptos", "S28"),
        "precio_accion": ("Conceptos", "S29"),
    },
    "integrado_emergente": {
        "activo": ("Integrado", "R34"),
        "pasivo": ("Integrado", "R36"),
        "empresa": ("Integrado", "R35"),
        "patrimonio": ("Integrado", "R37"),
        "precio_accion": ("Integrado", "R38"),
    },
}

# Valora sensitivity inputs
# Estructura: {campo: (hoja, celda)}
# NOTA: Solo crecimiento_perpetuo tiene celda de entrada real en la plantilla actual.
# forecast_ingresos y forecast_fde se calculan via LINEST (no hay override directo).
VALORA_SENSITIVITY_INPUT_CELL_MAP = {
    "crecimiento_perpetuo": ("Proyección", "F81"),
}

