"""
Raw SQL helpers for TimescaleDB time-series queries.

All queries target the `options` schema directly and use parameterized
statements to prevent SQL injection. The hypertable `options.ticker_ts`
has ~1B rows with indexes on (instrument_id, time_stamp DESC).

Candle queries always use real-time time_bucket() aggregation on the raw
hypertable.  Continuous aggregate views (cagg_candles_*) exist but are
not routed to until refresh policies are active and backfilled.  Set
USE_CAGG_ROUTING = True once that is done.
"""

import time
import logging
from datetime import datetime

from django.db import connection

logger = logging.getLogger("market_data.queries")

# Flip to True once cagg refresh policies are active and backfilled.
USE_CAGG_ROUTING = False

CAGG_VIEWS = {
    "1m": "options.cagg_candles_1m",
    "5m": "options.cagg_candles_5m",
    "15m": "options.cagg_candles_15m",
}

INTERVAL_MAP = {
    "1m": "1 minute",
    "5m": "5 minutes",
    "15m": "15 minutes",
    "30m": "30 minutes",
    "1h": "1 hour",
    "4h": "4 hours",
    "1d": "1 day",
}


def _execute(sql: str, params: list) -> tuple[list[dict], float]:
    """
    Execute a parameterized query and return (rows_as_dicts, elapsed_ms).
    """
    start = time.monotonic()
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col.name for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    elapsed_ms = round((time.monotonic() - start) * 1000, 2)
    logger.info("query=%s params=%s rows=%d elapsed_ms=%.2f", sql.strip()[:80], params, len(rows), elapsed_ms)
    return rows, elapsed_ms


def get_ticks(
    instrument_id: int,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int, float]:
    """
    Fetch tick data for an instrument within an optional time range.

    Uses keyset-style filtering with LIMIT/OFFSET for pagination.
    The composite index (instrument_id, time_stamp DESC) drives performance.

    Returns:
        (rows, total_count, elapsed_ms)
    """
    where_clauses = ["instrument_id = %s"]
    params: list = [instrument_id]

    if start:
        where_clauses.append("time_stamp >= %s")
        params.append(start)
    if end:
        where_clauses.append("time_stamp <= %s")
        params.append(end)

    where = " AND ".join(where_clauses)

    count_sql = f"SELECT COUNT(*) FROM options.ticker_ts WHERE {where}"
    data_sql = f"""
        SELECT instrument_id, time_stamp, open, high, low, close, volume, open_interest
        FROM options.ticker_ts
        WHERE {where}
        ORDER BY time_stamp DESC
        LIMIT %s OFFSET %s
    """

    t0 = time.monotonic()
    with connection.cursor() as cursor:
        cursor.execute(count_sql, params)
        total_count = cursor.fetchone()[0]

        cursor.execute(data_sql, params + [limit, offset])
        columns = [col.name for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
    logger.info(
        "get_ticks instrument_id=%s start=%s end=%s rows=%d total=%d elapsed_ms=%.2f",
        instrument_id, start, end, len(rows), total_count, elapsed_ms,
    )
    return rows, total_count, elapsed_ms


def get_candles(
    instrument_id: int,
    interval: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 500,
) -> tuple[list[dict], float]:
    """
    Aggregate tick data into OHLCV candles.

    For 1m/5m/15m intervals, reads from pre-computed continuous aggregates
    (cagg_candles_*) for sub-millisecond performance. For other intervals,
    falls back to real-time time_bucket aggregation on the raw hypertable.
    """
    pg_interval = INTERVAL_MAP.get(interval)
    if not pg_interval:
        raise ValueError(f"Unsupported interval '{interval}'. Choose from: {', '.join(INTERVAL_MAP.keys())}")

    if USE_CAGG_ROUTING:
        cagg_view = CAGG_VIEWS.get(interval)
        if cagg_view:
            return _candles_from_cagg(cagg_view, instrument_id, start, end, limit)

    return _candles_from_raw(pg_interval, instrument_id, start, end, limit)


def _candles_from_cagg(
    view: str,
    instrument_id: int,
    start: datetime | None,
    end: datetime | None,
    limit: int,
) -> tuple[list[dict], float]:
    """Read pre-computed candles from a continuous aggregate view."""
    where_clauses = ["instrument_id = %s"]
    params: list = [instrument_id]

    if start:
        where_clauses.append("bucket >= %s")
        params.append(start)
    if end:
        where_clauses.append("bucket <= %s")
        params.append(end)

    where = " AND ".join(where_clauses)

    sql = f"""
        SELECT bucket, open, high, low, close, volume, open_interest
        FROM {view}
        WHERE {where}
        ORDER BY bucket DESC
        LIMIT %s
    """
    params.append(limit)

    rows, elapsed_ms = _execute(sql, params)
    logger.info(
        "get_candles [CAGG %s] instrument_id=%s rows=%d elapsed_ms=%.2f",
        view, instrument_id, len(rows), elapsed_ms,
    )
    return rows, elapsed_ms


def _candles_from_raw(
    pg_interval: str,
    instrument_id: int,
    start: datetime | None,
    end: datetime | None,
    limit: int,
) -> tuple[list[dict], float]:
    """Real-time aggregation via time_bucket on the raw hypertable."""
    where_clauses = ["instrument_id = %s"]
    params: list = [instrument_id]

    if start:
        where_clauses.append("time_stamp >= %s")
        params.append(start)
    if end:
        where_clauses.append("time_stamp <= %s")
        params.append(end)

    where = " AND ".join(where_clauses)

    sql = f"""
        SELECT
            time_bucket('{pg_interval}', time_stamp) AS bucket,
            (array_agg(open ORDER BY time_stamp ASC))[1]  AS open,
            MAX(high)                                       AS high,
            MIN(low)                                        AS low,
            (array_agg(close ORDER BY time_stamp DESC))[1] AS close,
            SUM(volume)                                     AS volume,
            (array_agg(open_interest ORDER BY time_stamp DESC))[1] AS open_interest
        FROM options.ticker_ts
        WHERE {where}
        GROUP BY bucket
        ORDER BY bucket DESC
        LIMIT %s
    """
    params.append(limit)

    rows, elapsed_ms = _execute(sql, params)
    logger.info(
        "get_candles [RAW time_bucket('%s')] instrument_id=%s rows=%d elapsed_ms=%.2f",
        pg_interval, instrument_id, len(rows), elapsed_ms,
    )
    return rows, elapsed_ms


def get_stocks() -> tuple[list[dict], float]:
    """List all active stocks."""
    sql = """
        SELECT id, name, instrument_key, is_active
        FROM options.stock
        WHERE is_active = true
        ORDER BY name
    """
    return _execute(sql, [])


def get_instruments(
    stock_id: str | None = None,
    stock_name: str | None = None,
    instrument_type: str | None = None,
    expiry: str | None = None,
    nearest_strike: float | None = None,
    limit: int = 50,
) -> tuple[list[dict], float]:
    """
    List instruments with optional filters.

    Filters:
        stock_id:         UUID of the stock
        stock_name:       name of the stock (joins options.stock)
        instrument_type:  CE, PE, or FUT
        expiry:           expiry date (YYYY-MM-DD)
        nearest_strike:   if provided, orders by proximity to this price
    """
    use_join = stock_name is not None
    where_clauses = []
    params: list = []

    if stock_id:
        where_clauses.append("i.stock_id = %s")
        params.append(stock_id)

    if stock_name:
        where_clauses.append("s.name = %s")
        params.append(stock_name)

    if instrument_type:
        where_clauses.append("i.instrument_type = %s")
        params.append(instrument_type.upper())

    if expiry:
        where_clauses.append("i.expiry = %s")
        params.append(expiry)

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    if nearest_strike is not None:
        order = "ORDER BY ABS(i.strike_price - %s)"
        params.append(nearest_strike)
    else:
        order = "ORDER BY i.expiry DESC, i.strike_price ASC"

    join_clause = "JOIN options.stock s ON s.id = i.stock_id" if use_join else ""

    sql = f"""
        SELECT i.id, i.instrument_seq, i.stock_id, i.trading_symbol,
               i.instrument_key, i.strike_price, i.instrument_type,
               i.expiry, i.lot_size, i.exchange
        FROM options.instrument i
        {join_clause}
        {where}
        {order}
        LIMIT %s
    """
    params.append(limit)
    return _execute(sql, params)


def get_instruments_batch(
    stock_ids: list[str] | None = None,
    stock_names: list[str] | None = None,
    instrument_type: str | None = None,
    expiry: str | None = None,
    limit: int = 2000,
) -> tuple[list[dict], float]:
    """
    Fetch instruments for multiple stocks in a single query.

    Accepts either a list of stock UUIDs or a list of stock names (not both).
    Designed for batch consumers (e.g. option-chain screeners, backtest
    pipelines) that need instruments across many underlyings at once.
    """
    use_join = stock_names is not None and len(stock_names) > 0
    where_clauses: list[str] = []
    params: list = []

    if stock_ids:
        placeholders = ", ".join(["%s"] * len(stock_ids))
        where_clauses.append(f"i.stock_id IN ({placeholders})")
        params.extend(stock_ids)

    if stock_names:
        placeholders = ", ".join(["%s"] * len(stock_names))
        where_clauses.append(f"s.name IN ({placeholders})")
        params.extend(stock_names)

    if instrument_type:
        where_clauses.append("i.instrument_type = %s")
        params.append(instrument_type.upper())

    if expiry:
        where_clauses.append("i.expiry = %s")
        params.append(expiry)

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    join_clause = "JOIN options.stock s ON s.id = i.stock_id" if use_join else ""

    sql = f"""
        SELECT i.id, i.instrument_seq, i.stock_id, i.trading_symbol,
               i.instrument_key, i.strike_price, i.instrument_type,
               i.expiry, i.lot_size, i.exchange
        FROM options.instrument i
        {join_clause}
        {where}
        ORDER BY i.stock_id, i.strike_price
        LIMIT %s
    """
    params.append(limit)

    rows, elapsed_ms = _execute(sql, params)
    logger.info(
        "get_instruments_batch stock_ids=%s stock_names=%s rows=%d elapsed_ms=%.2f",
        stock_ids, stock_names, len(rows), elapsed_ms,
    )
    return rows, elapsed_ms


def get_ticks_batch(
    instrument_ids: list[int],
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 50000,
) -> tuple[list[dict], int, float]:
    """
    Fetch tick data for multiple instruments in a single query.

    Returns rows ordered by (instrument_id, time_stamp) so callers can
    groupby instrument locally.  Skips per-instrument pagination — batch
    consumers typically want all rows within a time window.

    Returns:
        (rows, total_count, elapsed_ms)
    """
    placeholders = ", ".join(["%s"] * len(instrument_ids))
    where_clauses = [f"instrument_id IN ({placeholders})"]
    params: list = list(instrument_ids)

    if start:
        where_clauses.append("time_stamp >= %s")
        params.append(start)
    if end:
        where_clauses.append("time_stamp <= %s")
        params.append(end)

    where = " AND ".join(where_clauses)

    count_sql = f"SELECT COUNT(*) FROM options.ticker_ts WHERE {where}"
    data_sql = f"""
        SELECT instrument_id, time_stamp, open, high, low, close, volume, open_interest
        FROM options.ticker_ts
        WHERE {where}
        ORDER BY instrument_id, time_stamp
        LIMIT %s
    """

    t0 = time.monotonic()
    with connection.cursor() as cursor:
        cursor.execute(count_sql, params)
        total_count = cursor.fetchone()[0]

        cursor.execute(data_sql, params + [limit])
        columns = [col.name for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
    logger.info(
        "get_ticks_batch ids=%s start=%s end=%s rows=%d total=%d elapsed_ms=%.2f",
        instrument_ids, start, end, len(rows), total_count, elapsed_ms,
    )
    return rows, total_count, elapsed_ms


def get_expiries(
    instrument_type: str | None = None,
) -> tuple[list[dict], float]:
    """List distinct expiry dates."""
    where_clauses = ["instrument_type != 'FUT'"]
    params: list = []

    if instrument_type:
        where_clauses = ["instrument_type = %s"]
        params = [instrument_type.upper()]

    where = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
        SELECT DISTINCT expiry
        FROM options.instrument
        {where}
        ORDER BY expiry
    """
    return _execute(sql, params)
