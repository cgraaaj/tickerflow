#!/usr/bin/env bash
set -euo pipefail

#
# One-time migration: convert IST-as-UTC timestamps to proper UTC
# in the options.ticker_ts hypertable.
#
# All data before 2026-02-07 stores IST times with a +00 offset
# (e.g. 09:15 IST market open as 09:15:00+00). This script subtracts
# 5h30m to produce real UTC (03:45:00+00).
#
# Strategy: bulk decompress -> single UPDATE -> recompress
# Requires ~184 GB temporary disk during decompression.
#

DB_HOST="${DB_HOST:-10.19.94.40}"
DB_USER="${DB_USER:-sd_admin}"
DB_NAME="${DB_NAME:-stock-dumps}"
DB_PORT="${DB_PORT:-5432}"
CUTOFF="2026-02-07 00:00:00+00"
CHUNK_BOUNDARY="2026-02-12 00:00:00+00"
LOGFILE="migrate_ist_to_utc_$(date +%Y%m%d_%H%M%S).log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGFILE"; }

run_sql() {
    PGPASSWORD="${PGPASSWORD:?Set PGPASSWORD}" \
    psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -p "$DB_PORT" \
         -v ON_ERROR_STOP=1 --no-psqlrc -qAt "$@"
}

run_sql_verbose() {
    PGPASSWORD="${PGPASSWORD:?Set PGPASSWORD}" \
    psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -p "$DB_PORT" \
         -v ON_ERROR_STOP=1 --no-psqlrc "$@"
}

# ── Pre-flight checks ─────────────────────────────────────────────
log "=== IST-to-UTC Migration Started ==="
log "Target: $DB_HOST:$DB_PORT/$DB_NAME"
log "Cutoff: $CUTOFF"
log "Log:    $LOGFILE"

log "--- Pre-flight: verifying IST-as-UTC data exists ---"
SAMPLE_TS=$(run_sql -c "
    SELECT time_stamp
    FROM options.ticker_ts
    WHERE instrument_id = 29827
      AND time_stamp::date = '2025-02-20'
    ORDER BY time_stamp LIMIT 1;
")
log "Sample pre-migration timestamp (instrument 29827, 2025-02-20): $SAMPLE_TS"
if [[ "$SAMPLE_TS" == *"09:15"* ]]; then
    log "CONFIRMED: data is IST-as-UTC (09:15+00 = IST market open stored as UTC)"
elif [[ "$SAMPLE_TS" == *"03:45"* ]]; then
    log "WARNING: data appears already migrated (03:45+00 = proper UTC market open). Aborting."
    exit 0
else
    log "WARNING: unexpected timestamp format: $SAMPLE_TS -- review manually"
    exit 1
fi

COMPRESSED_COUNT=$(run_sql -c "
    SELECT COUNT(*)
    FROM timescaledb_information.chunks
    WHERE hypertable_name = 'ticker_ts'
      AND range_start < '$CHUNK_BOUNDARY'
      AND is_compressed = true;
")
log "Compressed chunks to decompress: $COMPRESSED_COUNT"

# ── Phase 1: Decompress ───────────────────────────────────────────
log "=== Phase 1: Decompressing affected chunks ==="

CHUNKS=$(run_sql -c "
    SELECT chunk_schema || '.' || chunk_name
    FROM timescaledb_information.chunks
    WHERE hypertable_name = 'ticker_ts'
      AND range_start < '$CHUNK_BOUNDARY'
      AND is_compressed = true
    ORDER BY range_start;
")

TOTAL=$(echo "$CHUNKS" | wc -l)
i=0
for chunk in $CHUNKS; do
    i=$((i + 1))
    log "  Decompressing [$i/$TOTAL]: $chunk"
    START_T=$(date +%s)
    run_sql -c "SELECT decompress_chunk('${chunk}');" >/dev/null
    ELAPSED=$(( $(date +%s) - START_T ))
    log "  Done in ${ELAPSED}s"
done

log "All chunks decompressed."

# ── Phase 2: UPDATE ───────────────────────────────────────────────
log "=== Phase 2: Shifting timestamps (- 5h30m) for data before $CUTOFF ==="

START_T=$(date +%s)
ROWS_UPDATED=$(run_sql -c "
    UPDATE options.ticker_ts
       SET time_stamp = time_stamp - INTERVAL '5 hours 30 minutes'
     WHERE time_stamp < '$CUTOFF';
    SELECT 'ROWS_AFFECTED';
" 2>&1 | head -1)
ELAPSED=$(( $(date +%s) - START_T ))
log "UPDATE complete in ${ELAPSED}s. Result: $ROWS_UPDATED"

# ── Phase 2b: VACUUM ──────────────────────────────────────────────
log "=== Phase 2b: Running VACUUM on ticker_ts ==="
START_T=$(date +%s)
run_sql -c "VACUUM options.ticker_ts;" 2>&1 | tee -a "$LOGFILE" || true
ELAPSED=$(( $(date +%s) - START_T ))
log "VACUUM complete in ${ELAPSED}s"

# ── Phase 3: Recompress ───────────────────────────────────────────
log "=== Phase 3: Recompressing chunks ==="

CHUNKS_TO_COMPRESS=$(run_sql -c "
    SELECT chunk_schema || '.' || chunk_name
    FROM timescaledb_information.chunks
    WHERE hypertable_name = 'ticker_ts'
      AND range_start < '$CHUNK_BOUNDARY'
      AND is_compressed = false
    ORDER BY range_start;
")

TOTAL=$(echo "$CHUNKS_TO_COMPRESS" | wc -l)
i=0
for chunk in $CHUNKS_TO_COMPRESS; do
    i=$((i + 1))
    log "  Compressing [$i/$TOTAL]: $chunk"
    START_T=$(date +%s)
    run_sql -c "SELECT compress_chunk('${chunk}');" >/dev/null
    ELAPSED=$(( $(date +%s) - START_T ))
    log "  Done in ${ELAPSED}s"
done

log "All chunks recompressed."

# ── Phase 4: Verification ─────────────────────────────────────────
log "=== Phase 4: Post-migration verification ==="

VERIFY_TS=$(run_sql -c "
    SELECT time_stamp
    FROM options.ticker_ts
    WHERE instrument_id = 29827
      AND time_stamp >= '2025-02-19 03:00:00+00'
      AND time_stamp <  '2025-02-20 11:00:00+00'
    ORDER BY time_stamp LIMIT 1;
")
log "Post-migration sample (instrument 29827, 2025-02-20): $VERIFY_TS"

if [[ "$VERIFY_TS" == *"03:45"* ]]; then
    log "PASS: timestamp correctly shifted to 03:45+00 (proper UTC)"
else
    log "FAIL: expected 03:45+00 but got $VERIFY_TS"
fi

IST_REMNANT=$(run_sql -c "
    SELECT COUNT(*)
    FROM options.ticker_ts
    WHERE time_stamp >= '2024-07-01' AND time_stamp < '2026-02-01 18:00:00+00'
      AND EXTRACT(hour FROM time_stamp) >= 11;
")
log "Rows with hour >= 11 in old data range (should be 0): $IST_REMNANT"

PROPER_UTC_CHECK=$(run_sql -c "
    SELECT time_stamp
    FROM options.ticker_ts
    WHERE instrument_id = 247338
      AND time_stamp::date = '2026-03-04'
    ORDER BY time_stamp LIMIT 1;
")
log "Proper UTC data untouched check (instrument 247338, 2026-03-04): $PROPER_UTC_CHECK"

log "=== Migration Complete ==="
log "Full log saved to: $LOGFILE"
