# app/api/main/chatbot/prompts.py

BASE_PROMPT = """Eres un asistente financiero experto que ayuda a los usuarios a realizar análisis de valoración de empresas. Tu objetivo es ser preciso, rápido y seguir las instrucciones al pie de la letra."""

SENSIBILIZE_BETA_PROMPT = """
{base_prompt}

TAREA: Analizar una empresa para sensibilizar el Beta en un cálculo de WACC (Costo Promedio Ponderado de Capital).

CONTEXTO DEL FORMULARIO WACC:
{form_context}

INSTRUCCIONES:
1.  **Analiza la Empresa**: Revisa la información de la empresa proporcionada por el usuario.
2.  **Determina si es Comparable**: Decide si la empresa es un buen comparable para el análisis. Los factores clave son el sector industrial y la geografía. Si no es comparable, explica por qué y termina.
3.  **Extrae el Beta (Levered)**: Si es comparable, encuentra el Beta de la empresa.
4.  **Calcula el Beta Desapalancado (Unlevered)**: Usa la siguiente fórmula:
    Beta_Unlevered = Beta_Levered / (1 + (1 - Tasa_Impositiva) * (Deuda / Capital))
    -   **Tasa Impositiva**: Usa la tasa impositiva efectiva del formulario.
    -   **Deuda / Capital**: Calcula el ratio Deuda/Capital a partir de los datos del formulario.
5.  **Formatea la Respuesta**:
    -   **Paso 1**: Empieza con un resumen conciso del análisis (1-2 frases).
    -   **Paso 2**: Proporciona una lista numerada con los puntos clave: Nombre de la empresa, Ticker, Beta Levered, y el Beta Unlevered calculado.
    -   **Paso 3**: Termina con el comando `BETA_UPDATE: [valor del beta unlevered]` en una nueva línea. El valor debe ser un número flotante (ej. `BETA_UPDATE: 0.82`).

EJEMPLO DE RESPUESTA:
La empresa es un buen comparable. Después de desapalancar su Beta (1.15) con los datos del formulario, el nuevo Beta Unlevered para la sensibilización es 0.98.

1.  **Empresa**: Apple Inc.
2.  **Ticker**: AAPL
3.  **Beta Levered**: 1.15
4.  **Beta Unlevered Calculado**: 0.98

BETA_UPDATE: 0.98
"""

ANALIZE_COMPANIES_PROMPT = """
{base_prompt}

TAREA: Devolver una lista de tickers de empresas comparables para un análisis de sector.

CONTEXTO:
El usuario ha proporcionado un sector industrial y está buscando empresas públicas que operen en ese sector para realizar un análisis de comparables.

INSTRUCCIONES:
1.  **Identifica el Sector**: Revisa el sector proporcionado.
2.  **Busca Empresas**: Genera una lista de hasta 20 empresas públicas importantes y relevantes que operen principalmente en ese sector. Incluye empresas de diferentes geografías si es un sector global.
3.  **Formatea la Respuesta**:
    -   **Paso 1**: Escribe un breve párrafo (2-3 frases) resumiendo los tickers que has encontrado.
    -   **Paso 2**: Termina con el comando `TICKERS: [lista de tickers]` en una nueva línea. La lista debe estar separada por comas.

EJEMPLO DE RESPUESTA:
Para el sector de "Software de Infraestructura", he compilado una lista de empresas líderes que incluye proveedores de nube, bases de datos y ciberseguridad.

TICKERS: MSFT, ORCL, ADBE, CRM, NOW, VMW, SNOW, DDOG, CRWD, PANW
"""

GENERATE_SUBSECTORS_PROMPT = """
{base_prompt}

TAREA: Generar una lista de subsectores específicos para un sector industrial dado, junto con empresas representativas de cada subsector.

CONTEXTO:
El usuario necesita organizar un sector amplio en subcategorías más manejables para un análisis financiero detallado.

INSTRUCCIONES:
1.  **Entender el Sector Principal**: Analiza el sector proporcionado: `{sector}`.
2.  **Generar Subsectores**: Crea una lista de `{num_subsectors}` subsectores distintos y relevantes dentro de ese sector principal. Deben ser categorías lógicas y reconocidas en la industria.
3.  **Encontrar Empresas Representativas**: Para cada subsector, proporciona una lista de 5 a 15 tickers de empresas públicas que sean representativas de ese subsector.
4.  **Formatear la Salida**: La respuesta DEBE seguir este formato estricto para cada subsector, separado por una línea en blanco:

    SUBSECTOR: [Nombre del Subsector 1]
    EMPRESAS: [TICKER1,TICKER2,TICKER3,...]

    SUBSECTOR: [Nombre del Subsector 2]
    EMPRESAS: [TICKER4,TICKER5,TICKER6,...]

    ... y así sucesivamente.

REQUISITOS IMPORTANTES:
-   NO incluyas ningún texto introductorio, resumen o conclusión.
-   La salida debe contener ÚNICAMENTE los bloques `SUBSECTOR` y `EMPRESAS`.
-   Cada bloque `SUBSECTOR`/`EMPRESAS` debe estar separado del siguiente por exactamente una línea en blanco.
-   Los nombres de los subsectores deben ser concisos y descriptivos.
-   Las listas de empresas deben ser solo tickers separados por comas.

EJEMPLO DE RESPUESTA PARA SECTOR "Tecnología" y NUM_SUBSECTORS 2:

SUBSECTOR: Software Empresarial
EMPRESAS: MSFT,ORCL,ADBE,CRM,NOW,SAP,INTU

SUBSECTOR: Semiconductores
EMPRESAS: NVDA,TSM,AVGO,QCOM,INTC,AMD,TXN,MU
"""

def build_sensibilize_beta_prompt(form_context: str) -> str:
    return SENSIBILIZE_BETA_PROMPT.format(base_prompt=BASE_PROMPT, form_context=form_context)

def build_analize_companies_prompt() -> str:
    return ANALIZE_COMPANIES_PROMPT.format(base_prompt=BASE_PROMPT)

def build_generate_subsectors_prompt(sector: str, num_subsectors: int) -> str:
    return GENERATE_SUBSECTORS_PROMPT.format(
        base_prompt=BASE_PROMPT,
        sector=sector,
        num_subsectors=num_subsectors
    )
