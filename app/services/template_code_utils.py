import re
import unicodedata
from typing import Optional


def normalize_code(original_name: str) -> Optional[str]:
    """Normaliza texto a código $$ALFANUMERICO$$ en mayúsculas."""
    if not original_name:
        return None

    name_str = str(original_name)
    if "<openpyxl" in name_str or "object at" in name_str:
        return None

    normalized = name_str.upper()
    normalized = unicodedata.normalize("NFD", normalized)
    normalized = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    normalized = re.sub(r"[^A-Z0-9]", "", normalized)

    return f"$${normalized}$$" if normalized else None
