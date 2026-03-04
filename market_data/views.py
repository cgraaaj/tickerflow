import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.tracking import UsageTrackingMixin
from . import queries
from .serializers import (
    CandleQuerySerializer,
    ExpiryQuerySerializer,
    InstrumentQuerySerializer,
    TickQuerySerializer,
)

logger = logging.getLogger("market_data.views")


class StockListView(UsageTrackingMixin, APIView):
    """List all active stocks from the options schema."""

    def get(self, request):
        stocks, elapsed_ms = queries.get_stocks()
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
