# app/api/chatbot/utils.py
import re

def format_api_response(text: str) -> str:
    """Limpia la respuesta de Markdown a texto plano para el frontend."""
    if not text:
        return ""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'`(.*?)`', r'\1', text)
    text = re.sub(r'^\s*\d+\.\s+\*\*(.*?)\*\*:\s*', r'\1: ', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-•]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\*\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    text = re.sub(r':\s*\n\n', ':\n', text)
    return text

def extract_tickers(text: str) -> list[str]:
    """Extrae la lista de tickers si la IA los provee en el formato TICKERS:[...]"""

    tickers = []

    # Busca "TICKERS:" seguido opcionalmente por "[" y captura todo hasta el "]" o el final de la línea
    match = re.search(r'TICKERS:\s*\[?(.*?)\]?(?:\n|$)', text, re.IGNORECASE)
    if match:
        raw_list = match.group(1)
        tickers = [t.strip().upper() for t in raw_list.split(',') if t.strip()]
    
    # Extracción alternativa 1: viñetas estructuradas como "* Ticker: AAPL" o "**Ticker:** AAPL"
    if not tickers:
        fallback_matches = re.findall(r'Ticker\s*:?\**\s*([A-Z0-9.\-]+)', text, re.IGNORECASE)
        if fallback_matches:
            tickers = [t.strip().upper() for t in fallback_matches if t.strip()]

    # Extracción alternativa 2: valores en mayúsculas dentro de paréntesis (ej: "Apple Inc. (AAPL)")
    if not tickers and "TICKERS" not in text.upper():
        parenthesis_matches = re.findall(r'\(([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\)', text)
        if parenthesis_matches:
            tickers = [t.strip().upper() for t in parenthesis_matches]

    # Eliminar duplicados preservando el orden original
    seen = set()
    result = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result[:20]

def extract_beta_update(text: str) -> float | None:
    """Extrae la actualización de Beta si la IA lo provee en el formato BETA_UPDATE: x.x"""
    match = re.search(r'BETA_UPDATE:\s*([\d.]+)', text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None

def build_form_context(form_data: dict) -> str:
    if not form_data:
        return "No hay datos del formulario"
    return "FORMULARIO WACC:\n" + "\n".join([f"- {k}: {v}" for k, v in form_data.items()])
