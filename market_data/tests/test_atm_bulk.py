"""Smoke tests for the bulk endpoints.

These were created as a follow-up to the 2026-04-19 22:51:54 IST incident
where a Phase 3 backtest run hit ``/api/v1/instruments/atm-bulk/`` with an
80-stock payload and the whole batch returned a bare 500 because of one
malformed row. The tests below would have caught that:

* ``test_atm_bulk_phase3_payload_shape``: end-to-end happy path with the
  same payload shape Phase 3 uses (~80 stocks, mixed CE/PE, expiry date).
* ``test_atm_bulk_partial_no_match_returns_failed_indices``: bulk query
  silently dropped rows → response surfaces them in ``failed_indices``
  with HTTP 207 instead of 200, so the client knows to retry just those.
* ``test_atm_bulk_db_error_falls_back_per_row``: simulates the DB error
  path (Vault rotation, timeout, etc.) and asserts we still return the
  rows that succeeded plus indices for the rows that didn't, never a 500.
* ``test_atm_bulk_response_carries_request_id``: every response must echo
  ``X-Request-ID`` so an operator can grep logs by that id.
"""

from __future__ import annotations

import json
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import APIKey, CustomUser
from accounts.utils import generate_api_key


PHASE3_STOCKS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR",
    "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK", "BAJFINANCE", "LT",
    "AXISBANK", "ASIANPAINT", "MARUTI", "HCLTECH", "WIPRO", "ULTRACEMCO",
    "TITAN", "SUNPHARMA", "ADANIENT", "ADANIPORTS", "POWERGRID", "NTPC",
    "ONGC", "TATAMOTORS", "TATASTEEL", "M&M", "JSWSTEEL", "COALINDIA",
    "BAJAJFINSV", "GRASIM", "HINDALCO", "BPCL", "DIVISLAB", "NESTLEIND",
    "DRREDDY", "CIPLA", "EICHERMOT", "TECHM", "BRITANNIA", "BAJAJ-AUTO",
    "HEROMOTOCO", "APOLLOHOSP", "INDUSINDBK", "TATACONSUM", "SBILIFE",
    "HDFCLIFE", "UPL", "VEDL", "LTIM", "PIDILITIND", "SHREECEM",
    "ADANIGREEN", "DMART", "ICICIPRULI", "GODREJCP", "SIEMENS", "DABUR",
    "BERGEPAINT", "BANDHANBNK", "ICICIGI", "AMBUJACEM", "GAIL", "IOC",
    "MUTHOOTFIN", "CHOLAFIN", "TORNTPHARM", "JUBLFOOD", "PEL", "NMDC",
    "HAVELLS", "BIOCON", "INDIGO", "PNB", "BANKBARODA", "AUROPHARMA",
    "ABCAPITAL", "MFSL", "CONCOR",
]


def _phase3_payload() -> dict:
    requests = []
    for i, name in enumerate(PHASE3_STOCKS):
        requests.append({
            "stock_name": name,
            "instrument_type": "CE" if i % 2 == 0 else "PE",
            "nearest_strike": 1000.0 + (i * 50),
        })
    return {"requests": requests, "expiry": "2026-04-24"}


def _fake_bulk_rows(req_items: list[dict], drop_indices: set[int] | None = None) -> list[dict]:
    """Build a synthetic bulk-query response that mirrors the real query shape."""
    drop_indices = drop_indices or set()
    rows = []
    for idx, item in enumerate(req_items):
        if idx in drop_indices:
            continue
        rows.append({
            "_req_idx": idx,
            "id": f"00000000-0000-0000-0000-{idx:012d}",
            "instrument_seq": 1000 + idx,
            "stock_id": f"00000000-0000-0000-0001-{idx:012d}",
            "trading_symbol": f"{item['stock_name']}{int(item['nearest_strike'])}{item['instrument_type']}",
            "instrument_key": f"NSE_FO|{1000 + idx}",
            "strike_price": item["nearest_strike"],
            "instrument_type": item["instrument_type"],
            "expiry": "2026-04-24",
            "lot_size": 50,
            "exchange": "NSE_FO",
        })
    return rows


@override_settings(RATE_LIMITS={"basic": 0, "internal": 0})
class ATMBulkSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            email="phase3-smoke@tickerflow.test",
            password="not-used",
            tier="internal",
        )
        plaintext, prefix, hashed = generate_api_key()
        APIKey.objects.create(
            user=cls.user,
            prefix=prefix,
            hashed_key=hashed,
            label="phase3-smoke",
        )
        cls.api_key = plaintext
        cls.url = reverse("market_data:instrument-atm-bulk")

    def _post(self, payload, **extra):
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_API_KEY=self.api_key,
            **extra,
        )

    def test_atm_bulk_phase3_payload_shape(self):
        payload = _phase3_payload()
        with mock.patch(
            "market_data.queries.find_atm_instruments_bulk",
            return_value=(_fake_bulk_rows(payload["requests"]), 12.34),
        ):
            response = self._post(payload)

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["count"], len(PHASE3_STOCKS))
        self.assertEqual(body["failed_indices"], [])
        self.assertEqual(len(body["results"]), len(PHASE3_STOCKS))
        # Stable ordering by _req_idx is part of the contract.
        self.assertEqual(
            [r["_req_idx"] for r in body["results"]],
            list(range(len(PHASE3_STOCKS))),
        )

    def test_atm_bulk_partial_no_match_returns_failed_indices(self):
        payload = _phase3_payload()
        # Pretend the LATERAL join couldn't find an instrument for these rows
        # (e.g. typo'd stock_name, expiry not listed for that underlying).
        dropped = {3, 17, 42}
        with mock.patch(
            "market_data.queries.find_atm_instruments_bulk",
            return_value=(_fake_bulk_rows(payload["requests"], dropped), 8.9),
        ):
            response = self._post(payload)

        self.assertEqual(response.status_code, 207, response.content)
        body = response.json()
        failed_idx = {f["index"] for f in body["failed_indices"]}
        self.assertEqual(failed_idx, dropped)
        for failed in body["failed_indices"]:
            self.assertEqual(failed["reason"], "no_match")
        self.assertEqual(len(body["results"]), len(PHASE3_STOCKS) - len(dropped))

    def test_atm_bulk_db_error_falls_back_per_row(self):
        from django.db import DatabaseError

        payload = _phase3_payload()

        def _per_row(stock_name, instrument_type, nearest_strike, expiry=None):
            # Simulate a real-world fallback: 2 rows fail, the rest succeed.
            if stock_name in {"M&M", "PNB"}:
                return None
            return {
                "id": "00000000-0000-0000-0000-000000000001",
                "instrument_seq": 999,
                "stock_id": "00000000-0000-0000-0001-000000000001",
                "trading_symbol": f"{stock_name}{int(nearest_strike)}{instrument_type}",
                "instrument_key": "NSE_FO|999",
                "strike_price": nearest_strike,
                "instrument_type": instrument_type.upper(),
                "expiry": expiry,
                "lot_size": 50,
                "exchange": "NSE_FO",
            }

        with mock.patch(
            "market_data.queries.find_atm_instruments_bulk",
            side_effect=DatabaseError("connection terminated by administrator"),
        ), mock.patch(
            "market_data.queries.find_atm_instrument_one",
            side_effect=_per_row,
        ):
            response = self._post(payload)

        # Some rows succeeded → 207 Multi-Status, never a bare 500.
        self.assertEqual(response.status_code, 207, response.content)
        body = response.json()
        failed_names = {
            payload["requests"][f["index"]]["stock_name"]
            for f in body["failed_indices"]
        }
        self.assertEqual(failed_names, {"M&M", "PNB"})
        self.assertEqual(
            len(body["results"]),
            len(PHASE3_STOCKS) - len(body["failed_indices"]),
        )

    def test_atm_bulk_response_carries_request_id(self):
        payload = _phase3_payload()
        custom_rid = "ci-smoke-test-rid-001"
        with mock.patch(
            "market_data.queries.find_atm_instruments_bulk",
            return_value=(_fake_bulk_rows(payload["requests"]), 1.0),
        ):
            response = self._post(payload, HTTP_X_REQUEST_ID=custom_rid)

        self.assertEqual(response["X-Request-ID"], custom_rid)

    def test_atm_bulk_validation_error_is_structured(self):
        # Missing nearest_strike on row 0 — must NOT 500, must be a clean 400
        # with the structured envelope.
        payload = {
            "requests": [{"stock_name": "RELIANCE", "instrument_type": "CE"}],
            "expiry": "2026-04-24",
        }
        response = self._post(payload)
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertIn("request_id", body)
        self.assertIn("error", body)
