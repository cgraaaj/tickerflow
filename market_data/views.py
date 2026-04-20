import logging
import time

from django.db import DatabaseError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.tracking import UsageTrackingMixin
from tickerflow.observability import get_request_id
from . import queries
from .serializers import (
    ATMBulkQuerySerializer,
    CandleQuerySerializer,
    ExpiryQuerySerializer,
    InstrumentQuerySerializer,
    StockQuerySerializer,
    TickQuerySerializer,
)

logger = logging.getLogger("market_data.views")


class StockListView(UsageTrackingMixin, APIView):
    """List stocks from the options schema.

    Query params:
        include_inactive (bool, optional): include stocks no longer in F&O (default false)
        search (str, optional): case-insensitive name search
    """

    def get(self, request):
        serializer = StockQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        stocks, elapsed_ms = queries.get_stocks(
            include_inactive=params["include_inactive"],
            search=params.get("search") or None,
        )
        return Response({
            "count": len(stocks),
            "query_ms": elapsed_ms,
            "results": stocks,
        })


class InstrumentListView(UsageTrackingMixin, APIView):
    """
    List instruments with optional filters.

    Single-stock query params:
        stock_id (UUID, optional)
        stock_name (str, optional): filter by stock name

    Batch query params (mutually exclusive with single-stock equivalents):
        stock_ids (str, optional): comma-separated UUIDs (max 20)
        stock_names (str, optional): comma-separated names (max 20)

    Common filters:
        instrument_type (str, optional): CE, PE, or FUT
        expiry (date, optional): YYYY-MM-DD
        nearest_strike (float, optional): order results by proximity to this price
        limit (int, optional): default 50, max 2000
    """

    def get(self, request):
        serializer = InstrumentQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        is_batch = "_stock_id_list" in params or "_stock_name_list" in params

        if is_batch:
            instruments, elapsed_ms = queries.get_instruments_batch(
                stock_ids=params.get("_stock_id_list"),
                stock_names=params.get("_stock_name_list"),
                instrument_type=params["instrument_type"],
                expiry=str(params["expiry"]) if params["expiry"] else None,
                limit=params["limit"],
            )
        else:
            instruments, elapsed_ms = queries.get_instruments(
                stock_id=str(params["stock_id"]) if params["stock_id"] else None,
                stock_name=params["stock_name"],
                instrument_type=params["instrument_type"],
                expiry=str(params["expiry"]) if params["expiry"] else None,
                nearest_strike=params["nearest_strike"],
                limit=params["limit"],
            )

        return Response({
            "count": len(instruments),
            "query_ms": elapsed_ms,
            "results": instruments,
        })


class ExpiryListView(UsageTrackingMixin, APIView):
    """List distinct expiry dates from the instrument table."""

    def get(self, request):
        serializer = ExpiryQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        expiries, elapsed_ms = queries.get_expiries(
            instrument_type=params["instrument_type"],
        )
        return Response({
            "count": len(expiries),
            "query_ms": elapsed_ms,
            "results": expiries,
        })


class TickListView(UsageTrackingMixin, APIView):
    """
    Fetch historical tick data (1-minute OHLCV) for one or more instruments.

    Single-instrument query params:
        instrument_id (int): instrument sequence ID

    Batch query param (mutually exclusive with instrument_id):
        instrument_ids (str): comma-separated instrument sequence IDs (max 50)

    Common filters:
        start (datetime, optional): inclusive start time (ISO 8601)
        end (datetime, optional): inclusive end time (ISO 8601)
        limit (int, optional): max rows (default 100, max 50000)
        offset (int, optional): pagination offset (default 0, single mode only)
    """

    def get(self, request):
        serializer = TickQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        is_batch = "_instrument_id_list" in params

        if is_batch:
            rows, total_count, elapsed_ms = queries.get_ticks_batch(
                instrument_ids=params["_instrument_id_list"],
                start=params["start"],
                end=params["end"],
                limit=params["limit"],
            )
            return Response({
                "count": len(rows),
                "total": total_count,
                "limit": params["limit"],
                "query_ms": elapsed_ms,
                "results": rows,
            })

        rows, total_count, elapsed_ms = queries.get_ticks(
            instrument_id=params["instrument_id"],
            start=params["start"],
            end=params["end"],
            limit=params["limit"],
            offset=params["offset"],
        )

        return Response({
            "count": len(rows),
            "total": total_count,
            "limit": params["limit"],
            "offset": params["offset"],
            "query_ms": elapsed_ms,
            "results": rows,
        })


class CandleListView(UsageTrackingMixin, APIView):
    """
    Aggregate tick data into OHLCV candles using TimescaleDB time_bucket.

    Query params:
        instrument_id (int, required): instrument sequence ID
        interval (str, required): one of 1m, 5m, 15m, 30m, 1h, 4h, 1d
        start (datetime, optional): inclusive start time (ISO 8601)
        end (datetime, optional): inclusive end time (ISO 8601)
        limit (int, optional): max candles to return (default 500, max 5000)
    """

    def get(self, request):
        serializer = CandleQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        try:
            rows, elapsed_ms = queries.get_candles(
                instrument_id=params["instrument_id"],
                interval=params["interval"],
                start=params["start"],
                end=params["end"],
                limit=params["limit"],
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            "count": len(rows),
            "interval": params["interval"],
            "query_ms": elapsed_ms,
            "results": rows,
        })


class ATMBulkView(UsageTrackingMixin, APIView):
    """Find nearest-strike (ATM) instruments for multiple stock+type pairs.

    Accepts a JSON POST body with ``requests`` (list of {stock_name,
    instrument_type, nearest_strike}) and an optional ``expiry`` date.

    Returns one instrument per request, ordered by request index.
    Eliminates N+1 round-trips for backtest pipelines that look up
    ATM instruments for hundreds of trades.

    Failure semantics
    -----------------
    The handler is **partial-success aware**: a single bad row (typo'd
    stock name, no instrument matches the expiry, etc.) does NOT cause the
    entire batch to 500. Instead the response includes a ``failed_indices``
    array so the caller can retry / skip those rows surgically.

    Two failure paths are handled:

    1. Silent miss in the bulk query (LATERAL ``LIMIT 1`` returned 0 rows
       for an input row) — the index is added to ``failed_indices`` with
       ``reason="no_match"``.
    2. Bulk query raised a ``DatabaseError`` (timeout, broken connection,
       Vault credential rotation race, malformed batch). We fall back to
       per-row lookups so the rows that *do* succeed are still returned;
       the rows that fail are reported in ``failed_indices``.
    """

    def post(self, request):
        serializer = ATMBulkQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        req_items: list[dict] = params["requests"]
        expiry_str = str(params["expiry"]) if params["expiry"] else None

        rows, elapsed_ms, failed = self._resolve_with_fallback(req_items, expiry_str)

        body = {
            "count": len(rows),
            "query_ms": elapsed_ms,
            "results": rows,
            "failed_indices": failed,
        }
        http_status = (
            status.HTTP_207_MULTI_STATUS if failed and rows else
            status.HTTP_502_BAD_GATEWAY if failed and not rows else
            status.HTTP_200_OK
        )
        return Response(body, status=http_status)

    @staticmethod
    def _resolve_with_fallback(
        req_items: list[dict],
        expiry_str: str | None,
    ) -> tuple[list[dict], float, list[dict]]:
        """Run the bulk query first; on DB error fall back row-by-row.

        Returns ``(rows, elapsed_ms, failed_indices)`` where each entry in
        ``failed_indices`` is ``{"index": int, "reason": str}``.
        """
        request_id = get_request_id()

        try:
            rows, elapsed_ms = queries.find_atm_instruments_bulk(
                requests=req_items,
                expiry=expiry_str,
            )
            seen = {row["_req_idx"] for row in rows}
            failed = [
                {"index": i, "reason": "no_match"}
                for i in range(len(req_items))
                if i not in seen
            ]
            if failed:
                logger.warning(
                    "atm-bulk partial: %d/%d rows missing rid=%s indices=%s",
                    len(failed), len(req_items), request_id,
                    [f["index"] for f in failed][:20],
                )
            return rows, elapsed_ms, failed

        except DatabaseError as exc:
            logger.exception(
                "atm-bulk query failed, falling back row-by-row rid=%s err=%s",
                request_id, exc,
            )

        rows: list[dict] = []
        failed: list[dict] = []
        t0 = time.monotonic()
        for idx, item in enumerate(req_items):
            try:
                hit = queries.find_atm_instrument_one(
                    stock_name=item["stock_name"],
                    instrument_type=item["instrument_type"],
                    nearest_strike=item["nearest_strike"],
                    expiry=expiry_str,
                )
            except DatabaseError as exc:
                logger.warning(
                    "atm-bulk fallback row %d failed rid=%s err=%s",
                    idx, request_id, exc,
                )
                failed.append({"index": idx, "reason": "db_error"})
                continue
            except (KeyError, AttributeError, ValueError) as exc:
                failed.append({"index": idx, "reason": f"bad_input: {exc}"})
                continue

            if hit is None:
                failed.append({"index": idx, "reason": "no_match"})
            else:
                hit["_req_idx"] = idx
                rows.append(hit)

        elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
        return rows, elapsed_ms, failed
