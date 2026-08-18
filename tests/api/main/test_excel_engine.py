from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import unquote

import pytest

from app.api.main.calculations import excel_engine


@pytest.mark.asyncio
async def test_write_valora_inputs_supports_ten_years_from_c_to_l(monkeypatch):
    service = SimpleNamespace(
        config=SimpleNamespace(user_email="test@example.com"),
        execute_batch=AsyncMock(),
    )
    monkeypatch.setattr(excel_engine, "get_onedrive_service", lambda: service)

    years = list(range(2016, 2026))
    payload = {
        "balance_table": {
            "years": years,
            "rows": [{"values": years} for _ in range(32)],
        },
        "results_table": {
            "years": years,
            "rows": [{"values": years} for _ in range(14)],
        },
    }

    await excel_engine._write_valora_inputs_to_excel("item-id", payload)

    requests = service.execute_batch.await_args_list[0].args[0]
    assert "C2:L2" in unquote(requests[0]["url"])
    assert requests[0]["body"]["values"] == [years]
    assert "C37:L37" in unquote(requests[1]["url"])
    assert "C4:L35" in unquote(requests[2]["url"])
    assert len(requests[2]["body"]["values"][0]) == 10
    assert "C38:L51" in unquote(requests[3]["url"])
    assert len(requests[3]["body"]["values"][0]) == 10

    projection_requests = service.execute_batch.await_args_list[1].args[0]
    assert len(projection_requests) == 4
    assert "C53" in unquote(projection_requests[0]["url"])
    assert projection_requests[0]["body"]["values"] == [[2016]]
    projection_formulas = projection_requests[3]["body"]["formulas"]
    assert projection_formulas[0][0] is None
    assert projection_formulas[0][1] == "=C53+1"
    assert projection_formulas[1][0] == "=C38"
    assert projection_formulas[7][0] == "=+C56+C57+C58+C59"
    assert projection_formulas[14][1] == "=C67+1"
    assert projection_formulas[19][1] == "=C72+1"

    source_requests = service.execute_batch.await_args_list[2].args[0]
    assert len(source_requests) == 10
    assert "C87" in source_requests[0]["url"]
    assert source_requests[0]["body"]["values"] == [[1]]
    source_formulas = source_requests[8]["body"]["formulas"]
    assert source_formulas[0][0] == "=C$72"
    assert source_formulas[1][0] is None
    assert source_formulas[1][1] == "=C87+1"
    assert source_formulas[2][0] == "=C54"
    assert source_formulas[3][10] == (
        "=FORECAST.LINEAR(M86,$C$89:$L$89,$C$86:$L$86)"
    )
    assert source_formulas[108][0] is None
    assert source_formulas[108][1] == "=LN(C189)*$K$198+$L$203"

    linest_requests = service.execute_batch.await_args_list[3].args[0]
    assert len(linest_requests) == 17
    assert linest_requests[0]["body"]["formulas"] == [
        ["=LINEST(C89:M89,LN(C87:M87))", None]
    ]
    assert linest_requests[1]["body"]["formulas"] == [
        ["=LINEST(C88:L88,LN(C87:L87))", None]
    ]
    assert linest_requests[12]["body"]["formulas"] == [
        ["=LINEST(D194:L194,LN(C189:K189))", None]
    ]
    assert linest_requests[13]["body"]["formulas"] == [
        ["=LINEST(D193:L193,LN(C189:K189))", None]
    ]
    assert "Integrado" in linest_requests[16]["url"]
    assert linest_requests[16]["body"]["formulas"] == [
        ["=LINEST(C7:L7,LN(C6:L6))", None]
    ]


@pytest.mark.asyncio
async def test_write_valora_inputs_clears_inactive_years_for_five_years(
    monkeypatch,
):
    service = SimpleNamespace(
        config=SimpleNamespace(user_email="test@example.com"),
        execute_batch=AsyncMock(),
    )
    monkeypatch.setattr(excel_engine, "get_onedrive_service", lambda: service)
    years = list(range(2021, 2026))
    payload = {
        "balance_table": {
            "years": years,
            "rows": [{"values": years} for _ in range(32)],
        },
        "results_table": {
            "years": years,
            "rows": [{"values": years} for _ in range(14)],
        },
    }

    await excel_engine._write_valora_inputs_to_excel("item-id", payload)

    data_requests = service.execute_batch.await_args_list[0].args[0]
    assert "H2:L2" in unquote(data_requests[0]["url"])
    assert "H4:L35" in unquote(data_requests[2]["url"])
    assert len(data_requests) == 17
    assert "C2:G2" in unquote(data_requests[4]["url"])
    assert data_requests[4]["body"]["values"] == [["", "", "", "", ""]]
    assert "C53:G75" in unquote(data_requests[8]["url"])

    projection_requests = service.execute_batch.await_args_list[1].args[0]
    assert projection_requests[0]["body"]["values"] == [[2021]]
    assert "H53" in projection_requests[0]["url"]
    assert projection_requests[3]["body"]["formulas"][0][1] == "=H53+1"


@pytest.mark.parametrize(
    (
        "years_start_col",
        "expected_regular",
        "expected_special",
        "expected_capex_ratio",
    ),
    [
        (
            "C",
            "=LINEST(C89:M89,LN(C87:M87))",
            "=LINEST(D194:L194,LN(C189:K189))",
            "=LINEST(D193:L193,LN(C189:K189))",
        ),
        (
            "E",
            "=LINEST(E89:M89,LN(E87:M87))",
            "=LINEST(F194:L194,LN(E189:K189))",
            "=LINEST(F193:L193,LN(E189:K189))",
        ),
        (
            "H",
            "=LINEST(H89:M89,LN(H87:M87))",
            "=LINEST(I194:L194,LN(H189:K189))",
            "=LINEST(I193:L193,LN(H189:K189))",
        ),
    ],
)
def test_build_valora_linest_formulas_uses_financial_year_start(
    years_start_col,
    expected_regular,
    expected_special,
    expected_capex_ratio,
):
    formulas = excel_engine._build_valora_linest_formulas(years_start_col)

    assert len(formulas) == 17
    assert formulas[0]["formula"] == expected_regular
    assert formulas[12]["formula"] == expected_special
    assert formulas[13]["formula"] == expected_capex_ratio


@pytest.mark.parametrize(
    ("years_start_col", "expected_width", "next_year_formula"),
    [
        ("C", 10, "=C53+1"),
        ("E", 8, "=E53+1"),
        ("H", 5, "=H53+1"),
    ],
)
def test_projection_blocks_extend_existing_formulas_from_first_year(
    years_start_col, expected_width, next_year_formula
):
    formulas = excel_engine._build_valora_projection_block_formulas(
        years_start_col
    )

    assert len(formulas) == 23
    assert all(len(row) == expected_width for row in formulas)
    assert formulas[0][0] is None
    assert formulas[0][1] == next_year_formula
    assert formulas[1][0] == f"={years_start_col}38"
    assert formulas[7][0] == (
        f"=+{years_start_col}56+{years_start_col}57+"
        f"{years_start_col}58+{years_start_col}59"
    )
    assert formulas[10][0] == (
        f"={years_start_col}60+{years_start_col}61+{years_start_col}62"
    )
    assert formulas[14][0] is None
    assert formulas[14][1] == f"={years_start_col}67+1"
    assert formulas[19][0] is None
    assert formulas[19][1] == f"={years_start_col}72+1"


@pytest.mark.parametrize(
    ("years_start_col", "expected_width"),
    [("C", 11), ("E", 9), ("H", 6)],
)
def test_linest_source_tables_follow_active_financial_years(
    years_start_col, expected_width
):
    projection, integrated = excel_engine._build_valora_linest_source_formulas(
        years_start_col
    )

    assert len(projection) == 129
    assert all(len(row) == expected_width for row in projection)
    assert projection[0][0] == f"={years_start_col}$72"
    assert projection[1][0] is None
    assert projection[1][1] == f"={years_start_col}87+1"
    assert projection[2][0] == f"={years_start_col}54"
    assert projection[3][-1] == (
        f"=FORECAST.LINEAR(M86,${years_start_col}$89:$L$89,"
        f"${years_start_col}$86:$L$86)"
    )

    special_row = projection[194 - 86]
    assert special_row[0] is None
    assert special_row[1] == f"=LN({years_start_col}189)*$K$198+$L$203"

    assert len(integrated) == 5
    assert integrated[0][0] == f"=Proyección!{years_start_col}63"
    assert integrated[1][0] == f"=LN({years_start_col}6)*$J$14+$K$19"
