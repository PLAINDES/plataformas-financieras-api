# app/api/main/reports/utils.py

def flatten_dict(d: dict, parent_key: str = '', sep: str = '.') -> dict:
    """
    Aplana un diccionario anidado para usar sus rutas como llaves.
    Si encuentra una lista (como 'inputs' o 'resultados'), toma el primer elemento (índice 0).
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k

        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
            # Asume que el primer elemento es el último estado válido para el reporte
            items.extend(flatten_dict(v[0], new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def _sanitize_text(text: str) -> str:
    """Reemplaza caracteres Unicode comunes no soportados por latin-1"""
    if not text:
        return ""
    replacements = {
        '—': '-',    # em-dash a guion normal
        '–': '-',    # en-dash a guion normal
        '“': '"',    # comillas curvas
        '”': '"',
        '‘': "'",
        '’': "'",
        '€': 'EUR',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Ignora cualquier otro caracter que falle en latin-1
    return text.encode('latin-1', 'ignore').decode('latin-1')
