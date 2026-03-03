"""
Create TimescaleDB continuous aggregates for 1m, 5m, and 15m OHLCV candles
on options.ticker_ts, plus refresh policies and chunk compression.

These materialized views pre-compute candle data so the API doesn't need
to scan raw ticks for every request. Queries against the continuous
aggregates are orders of magnitude faster.
"""

from django.db import migrations


# Since ticker_ts is already 1-minute data, the 1m aggregate is a
# passthrough that enables TimescaleDB's real-time aggregation features
# and serves as the base for higher-interval aggregates.

CREATE_CAGG_1M = """
CREATE MATERIALIZED VIEW IF NOT EXISTS options.cagg_candles_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time_stamp) AS bucket,
    instrument_id,
    (array_agg(open ORDER BY time_stamp ASC))[1]  AS open,
    MAX(high)                                       AS high,
    MIN(low)                                        AS low,
    (array_agg(close ORDER BY time_stamp DESC))[1] AS close,
    SUM(volume)                                     AS volume,
    (array_agg(open_interest ORDER BY time_stamp DESC))[1] AS open_interest
FROM options.ticker_ts
GROUP BY bucket, instrument_id
WITH NO DATA;
"""

CREATE_CAGG_5M = """
CREATE MATERIALIZED VIEW IF NOT EXISTS options.cagg_candles_5m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', time_stamp) AS bucket,
    instrument_id,
    (array_agg(open ORDER BY time_stamp ASC))[1]  AS open,
    MAX(high)                                       AS high,
    MIN(low)                                        AS low,
    (array_agg(close ORDER BY time_stamp DESC))[1] AS close,
    SUM(volume)                                     AS volume,
    (array_agg(open_interest ORDER BY time_stamp DESC))[1] AS open_interest
FROM options.ticker_ts
GROUP BY bucket, instrument_id
WITH NO DATA;
"""

CREATE_CAGG_15M = """
CREATE MATERIALIZED VIEW IF NOT EXISTS options.cagg_candles_15m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('15 minutes', time_stamp) AS bucket,
    instrument_id,
    (array_agg(open ORDER BY time_stamp ASC))[1]  AS open,
    MAX(high)                                       AS high,
    MIN(low)                                        AS low,
    (array_agg(close ORDER BY time_stamp DESC))[1] AS close,
    SUM(volume)                                     AS volume,
    (array_agg(open_interest ORDER BY time_stamp DESC))[1] AS open_interest
FROM options.ticker_ts
GROUP BY bucket, instrument_id
WITH NO DATA;
"""

# Refresh policies: keep aggregates up to date automatically.
# end_offset = NULL means refresh up to the latest data.
# start_offset = how far back to re-aggregate on each refresh.
# schedule_interval = how often the policy runs.

ADD_REFRESH_1M = """
SELECT add_continuous_aggregate_policy('options.cagg_candles_1m',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute'
);
"""

ADD_REFRESH_5M = """
SELECT add_continuous_aggregate_policy('options.cagg_candles_5m',
    start_offset => INTERVAL '12 hours',
    end_offset => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes'
);
"""

ADD_REFRESH_15M = """
SELECT add_continuous_aggregate_policy('options.cagg_candles_15m',
    start_offset => INTERVAL '2 days',
    end_offset => INTERVAL '15 minutes',
    schedule_interval => INTERVAL '15 minutes'
);
"""

# Compression: compress chunks older than 4 weeks to save disk space.
# The 191 GB hypertable will shrink significantly.

ENABLE_COMPRESSION = """
ALTER TABLE options.ticker_ts SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'instrument_id',
    timescaledb.compress_orderby = 'time_stamp DESC'
);
"""

ADD_COMPRESSION_POLICY = """
SELECT add_compression_policy('options.ticker_ts', INTERVAL '4 weeks');
"""

# Indexes on continuous aggregates for fast lookups
CREATE_CAGG_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_cagg_1m_inst_bucket
    ON options.cagg_candles_1m (instrument_id, bucket DESC);
CREATE INDEX IF NOT EXISTS idx_cagg_5m_inst_bucket
    ON options.cagg_candles_5m (instrument_id, bucket DESC);
CREATE INDEX IF NOT EXISTS idx_cagg_15m_inst_bucket
    ON options.cagg_candles_15m (instrument_id, bucket DESC);
"""

# Reverse operations
DROP_CAGG_1M = "DROP MATERIALIZED VIEW IF EXISTS options.cagg_candles_1m CASCADE;"
DROP_CAGG_5M = "DROP MATERIALIZED VIEW IF EXISTS options.cagg_candles_5m CASCADE;"
DROP_CAGG_15M = "DROP MATERIALIZED VIEW IF EXISTS options.cagg_candles_15m CASCADE;"

REMOVE_COMPRESSION_POLICY = """
SELECT remove_compression_policy('options.ticker_ts', if_exists => true);
"""

DISABLE_COMPRESSION = """
ALTER TABLE options.ticker_ts SET (timescaledb.compress = false);
"""


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        # 1. Continuous aggregates
        migrations.RunSQL(sql=CREATE_CAGG_1M, reverse_sql=DROP_CAGG_1M),
        migrations.RunSQL(sql=CREATE_CAGG_5M, reverse_sql=DROP_CAGG_5M),
        migrations.RunSQL(sql=CREATE_CAGG_15M, reverse_sql=DROP_CAGG_15M),

        # 2. Refresh policies
        migrations.RunSQL(sql=ADD_REFRESH_1M, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=ADD_REFRESH_5M, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=ADD_REFRESH_15M, reverse_sql=migrations.RunSQL.noop),

        # 3. Compression on raw hypertable
        migrations.RunSQL(sql=ENABLE_COMPRESSION, reverse_sql=DISABLE_COMPRESSION),
        migrations.RunSQL(sql=ADD_COMPRESSION_POLICY, reverse_sql=REMOVE_COMPRESSION_POLICY),

        # 4. Indexes on aggregates
        migrations.RunSQL(sql=CREATE_CAGG_INDEXES, reverse_sql=migrations.RunSQL.noop),
    ]
