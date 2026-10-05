"""fix Kapital report metric ordering and identity sources"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    statement = sa.text(
        "UPDATE main_template_codes SET source_path = :path "
        "WHERE UPPER(REPLACE(code, '$', '')) = :code"
    )

    for prefix, markets in {
        "WPBY": ("mercado_desarrollado", "mercado_desarrollado"),
        "WEZG": ("mercado_emergente_dolares", "mercado_emergente_moneda_local"),
        "RESC": ("empresa_dolares", "empresa_moneda_local"),
    }.items():
        for market in markets:
            for offset, field in {
                1: "koa", 2: "ke", 3: "kd", 4: "kd(1-t)", 5: "cppc"
            }.items():
                code_number = offset if market == markets[0] else offset + 5
                if prefix == "WPBY" and offset > 5:
                    continue
                connection.execute(
                    statement,
                    {
                        "path": f"resultados.{market}.{field}",
                        "code": f"{prefix}{code_number}",
                    },
                )

    for code, path in {
        "KMZG1": "inputs.industria",
        "KMZG2": "inputs.pais",
        "KMZG3": "inputs.moneda",
        "KMZG4": "inputs.fecha",
    }.items():
        connection.execute(statement, {"code": code, "path": path})


def downgrade() -> None:
    pass
