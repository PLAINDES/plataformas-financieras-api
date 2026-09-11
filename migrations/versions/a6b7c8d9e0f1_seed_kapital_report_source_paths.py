"""seed explicit native source paths for Kapital report codes"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    statement = sa.text(
        "UPDATE main_template_codes "
        "SET source_path = :path, source_format = 'percent' "
        "WHERE UPPER(REPLACE(code, '$', '')) = :code"
    )
    groups = {
        "WPBY": ("mercado_desarrollado", "mercado_desarrollado"),
        "WEZG": ("mercado_emergente_dolares", "mercado_emergente_moneda_local"),
        "RESC": ("empresa_dolares", "empresa_moneda_local"),
    }
    fields = {1: "koa", 2: "ke", 3: "kd", 4: "wacc", 5: "kd(1-t)"}
    for prefix, markets in groups.items():
        market, local_market = markets
        for offset, field in fields.items():
            connection.execute(
                statement,
                {"path": f"resultados.{market}.{field}", "code": f"{prefix}{offset}"},
            )
        if prefix != "WPBY":
            for offset, field in fields.items():
                connection.execute(
                    statement,
                    {"path": f"resultados.{local_market}.{field}", "code": f"{prefix}{offset + 5}"},
                )


def downgrade() -> None:
    op.execute(
        "UPDATE main_template_codes SET source_path = NULL, source_format = NULL "
        "WHERE code LIKE '%WPBY%' OR code LIKE '%WEZG%' OR code LIKE '%RESC%'"
    )
