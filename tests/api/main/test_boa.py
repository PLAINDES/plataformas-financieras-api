import unittest
from unittest.mock import patch

import pandas as pd

from app.api.main.chatbot import boa


class FakeTicker:
    def __init__(
        self,
        *,
        balance_sheet: pd.DataFrame | None = None,
        quarterly_balance_sheet: pd.DataFrame | None = None,
    ):
        self.balance_sheet = balance_sheet if balance_sheet is not None else pd.DataFrame()
        self.quarterly_balance_sheet = (
            quarterly_balance_sheet
            if quarterly_balance_sheet is not None
            else pd.DataFrame()
        )
        self.financials = pd.DataFrame()
        self.info = {
            "shortName": "Test Company",
            "currency": "USD",
            "financialCurrency": "USD",
            "country": "United States",
            "sector": "Industrials",
            "industry": "Testing",
            "beta": 1.2,
            "marketCap": 1_000.0,
        }


class BoaHelperTests(unittest.TestCase):
    def setUp(self):
        boa._ticker_resolution_cache.clear()

    def test_first_valid_skips_null_newest_column(self):
        frame = pd.DataFrame(
            {"latest": [float("nan")], "previous": [125.0]},
            index=["Long Term Debt"],
        )

        self.assertEqual(boa.first_valid(frame, boa.DEBT_LABELS_LT), 125.0)

    def test_get_deuda_uses_quarterly_fallback(self):
        quarterly = pd.DataFrame(
            {"latest": [80.0, 20.0]},
            index=["Long Term Debt", "Current Debt"],
        )
        stock = FakeTicker(quarterly_balance_sheet=quarterly)

        debt_lt, debt_st, sources = boa.get_deuda(stock)

        self.assertEqual((debt_lt, debt_st), (80.0, 20.0))
        self.assertEqual(sources["debt_lt"], "quarterly_balance_sheet")
        self.assertEqual(sources["debt_st"], "quarterly_balance_sheet")

    def test_get_deuda_fills_only_missing_component_from_quarterly(self):
        annual = pd.DataFrame(
            {"latest": [80.0]},
            index=["Long Term Debt"],
        )
        quarterly = pd.DataFrame(
            {"latest": [20.0]},
            index=["Current Debt"],
        )
        stock = FakeTicker(
            balance_sheet=annual,
            quarterly_balance_sheet=quarterly,
        )

        debt_lt, debt_st, sources = boa.get_deuda(stock)

        self.assertEqual((debt_lt, debt_st), (80.0, 20.0))
        self.assertEqual(sources["debt_lt"], "balance_sheet")
        self.assertEqual(sources["debt_st"], "quarterly_balance_sheet")

    def test_process_single_ticker_returns_calculated_values(self):
        annual = pd.DataFrame(
            {"latest": [float("nan"), 20.0], "previous": [80.0, 10.0]},
            index=["Long Term Debt", "Current Debt"],
        )
        stock = FakeTicker(balance_sheet=annual)

        with (
            patch.object(boa.yf, "Ticker", lambda *args, **kwargs: stock),
            patch.object(boa, "get_fx_rate", lambda *args, **kwargs: 1.0),
            patch.object(boa, "_delay", lambda *args, **kwargs: None),
        ):
            _, result, diagnostic = boa._process_single_ticker("TEST")

        self.assertEqual(diagnostic["reason"], "ok")
        self.assertEqual(result["debt_lt"], 80.0)
        self.assertEqual(result["debt_st"], 20.0)
        self.assertEqual(result["debt_value"], 100.0)
        self.assertEqual(result["market_cap"], 1_000.0)
        self.assertIsNotNone(result["beta_unlevered"])
        self.assertEqual(
            result["debt_source"],
            "lt:balance_sheet|st:balance_sheet",
        )

    def test_missing_short_term_debt_is_valid_and_calculates_as_zero(self):
        annual = pd.DataFrame(
            {"latest": [80.0]},
            index=["Long Term Debt"],
        )
        stock = FakeTicker(balance_sheet=annual)

        with (
            patch.object(boa.yf, "Ticker", lambda *args, **kwargs: stock),
            patch.object(boa, "get_fx_rate", lambda *args, **kwargs: 1.0),
            patch.object(boa, "_delay", lambda *args, **kwargs: None),
        ):
            _, result, diagnostic = boa._process_single_ticker("TEST")

        self.assertEqual(diagnostic["reason"], "ok")
        self.assertEqual(result["debt_st"], 0.0)
        self.assertNotIn("debt_st", result["missing_fields"])
        self.assertEqual(result["diagnostic_reason"], "ok")
        self.assertEqual(result["debt_st_status"], "missing_normalized_to_zero")
        self.assertTrue(boa._has_complete_values(result))
        self.assertEqual(
            result["debt_st_failure_reason"],
            "sin_etiqueta_o_valor_en_balance_anual_y_trimestral",
        )

    def test_missing_long_term_debt_is_valid_and_calculates_as_zero(self):
        annual = pd.DataFrame(
            {"latest": [20.0]},
            index=["Current Debt"],
        )
        stock = FakeTicker(balance_sheet=annual)

        with (
            patch.object(boa.yf, "Ticker", lambda *args, **kwargs: stock),
            patch.object(boa, "get_fx_rate", lambda *args, **kwargs: 1.0),
            patch.object(boa, "_delay", lambda *args, **kwargs: None),
        ):
            _, result, diagnostic = boa._process_single_ticker("TEST")

        self.assertEqual(diagnostic["reason"], "ok")
        self.assertEqual(result["debt_lt"], 0.0)
        self.assertNotIn("debt_lt", result["missing_fields"])
        self.assertEqual(result["diagnostic_reason"], "ok")
        self.assertEqual(result["debt_lt_status"], "missing_normalized_to_zero")
        self.assertTrue(boa._has_complete_values(result))

    def test_missing_both_debt_components_remains_incomplete(self):
        stock = FakeTicker()

        with (
            patch.object(boa.yf, "Ticker", lambda *args, **kwargs: stock),
            patch.object(boa, "get_fx_rate", lambda *args, **kwargs: 1.0),
            patch.object(boa, "_delay", lambda *args, **kwargs: None),
        ):
            _, result, diagnostic = boa._process_single_ticker("TEST")

        self.assertEqual(diagnostic["reason"], "ok")
        self.assertIn("debt_lt", result["missing_fields"])
        self.assertIn("debt_st", result["missing_fields"])
        self.assertIn("debt_value", result["missing_fields"])
        self.assertEqual(result["diagnostic_reason"], "datos_incompletos")
        self.assertFalse(boa._has_complete_values(result))

    def test_verified_ticker_alias_resolves_vsco_to_vsxy(self):
        resolution = boa.resolve_ticker_symbol("VSCO", search_candidates=False)

        self.assertEqual(resolution["ticker_resolved"], "VSXY")
        self.assertEqual(resolution["ticker_resolution_status"], "resolved")
        self.assertEqual(resolution["ticker_resolution_reason"], "symbol_changed")
        self.assertEqual(resolution["ticker_resolution_source"], "SEC")

    def test_search_candidate_without_company_identity_requires_review(self):
        class FakeSearch:
            quotes = [{
                "symbol": "POSSIBLE",
                "longname": "Possible Company",
                "quoteType": "EQUITY",
                "exchange": "NYQ",
            }]

        with patch.object(boa.yf, "Search", lambda *args, **kwargs: FakeSearch()):
            resolution = boa.resolve_ticker_symbol("OLD", search_candidates=True)

        self.assertIsNone(resolution["ticker_resolved"])
        self.assertEqual(resolution["ticker_resolution_status"], "requires_review")
        self.assertEqual(resolution["ticker_resolution_candidates"][0]["ticker"], "POSSIBLE")

    def test_calculation_uses_resolved_ticker_and_preserves_original(self):
        annual = pd.DataFrame(
            {"latest": [80.0, 20.0]},
            index=["Long Term Debt", "Current Debt"],
        )
        stock = FakeTicker(balance_sheet=annual)
        requested_symbols = []

        def fake_ticker(symbol, *args, **kwargs):
            requested_symbols.append(symbol)
            return stock

        with (
            patch.object(boa.yf, "Ticker", fake_ticker),
            patch.object(boa, "get_fx_rate", lambda *args, **kwargs: 1.0),
            patch.object(boa, "_delay", lambda *args, **kwargs: None),
            patch.object(boa.time, "sleep", lambda *args, **kwargs: None),
        ):
            response = boa.calculate_subsectores_boa(
                [{"ticker": "VSCO", "sector": "Retail", "subsector": "Apparel"}],
                batch_size=1,
                save_to_db=False,
            )

        self.assertIn("VSXY", requested_symbols)
        row = response["ticker_rows"][0]
        self.assertEqual(row["ticker"], "VSCO")
        self.assertEqual(row["ticker_resolved"], "VSXY")
        self.assertEqual(row["ticker_resolution_status"], "resolved")


if __name__ == "__main__":
    unittest.main()
