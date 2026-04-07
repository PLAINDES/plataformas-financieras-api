from typing import Any, Dict, List, Optional
from sqlalchemy.sql import Select
from sqlalchemy import or_


def apply_filters(
    query: Select,
    model: Any,
    params: Dict[str, Any],
    *,
    search_fields: Optional[List[str]] = None,
    enum_fields: Optional[Dict[str, Any]] = None,
    eager_loads: Optional[Any] = None,
) -> Select:
    """
    Apply common filters and pagination to a SQLAlchemy Select query.

    params keys supported: limit, page, search, activo, and any field names present on the model.
    - `search` will perform an ilike match against `search_fields`.
    - `enum_fields` maps param name -> Enum class to coerce string values.
    - `eager_loads` can be an SQLAlchemy loader option to apply via `query.options(...)`.
    """
    # basic where: ignore deleted_at if present on model
    if hasattr(model, "deleted_at"):
        query = query.where(getattr(model, "deleted_at") == None)

    # search
    search = params.get("search")
    if search and search_fields:
        like = f"%{search}%"
        clauses = []
        for f in search_fields:
            if hasattr(model, f):
                clauses.append(getattr(model, f).ilike(like))
        if clauses:
            query = query.where(or_(*clauses))

    # activo
    if "activo" in params and hasattr(model, "activo"):
        activo = params.get("activo")
        if isinstance(activo, str):
            activo = activo.lower() in ("1", "true", "yes", "y")
        query = query.where(getattr(model, "activo") == activo)

    # enum fields
    if enum_fields:
        for param_name, enum_cls in enum_fields.items():
            if param_name in params and hasattr(model, param_name):
                raw = params.get(param_name)
                enum_val = None
                try:
                    enum_val = enum_cls[raw]
                except Exception:
                    try:
                        enum_val = enum_cls(raw)
                    except Exception:
                        enum_val = None
                if enum_val is not None:
                    query = query.where(getattr(model, param_name) == enum_val)

    # eager loads
    if eager_loads is not None:
        query = query.options(*eager_loads)

    # pagination
    limit = params.get("limit")
    if limit:
        try:
            limit_i = int(limit)
            page = int(params.get("page") or 1)
            page = max(1, page)
            offset = (page - 1) * limit_i
            query = query.limit(limit_i).offset(offset)
        except Exception:
            pass

    return query
