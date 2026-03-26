# #!/usr/bin/env python3
# """
# load_gem_bid_details.py

# Loads two CSV files into PostgreSQL sequentially:
#   1. gem_bid_details.csv        → public.gem_bid_details
#   2. gem_financial_details.csv  → public.gem_financial_details

# Run:
#     python load_gem_bid_details.py --bid-file <path> --financial-file <path> [--dry-run]

# Environment variables (required):
#     DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

# Optional:
#     BATCH_SIZE  — rows per execute_batch call for financial details (default 500)
# """

# import argparse
# import csv
# import logging
# import os
# import sys
# import re
# from collections import defaultdict
# from datetime import datetime
# from pathlib import Path

# import psycopg2
# import psycopg2.extras

# # ---------------------------------------------------------------------------
# # Paths
# # ---------------------------------------------------------------------------
# LOG_DIR = Path("/app/logs")

# # ---------------------------------------------------------------------------
# # Config
# # ---------------------------------------------------------------------------
# BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "500"))

# # ---------------------------------------------------------------------------
# # SQL — bid details
# # ---------------------------------------------------------------------------
# BD_INSERT_SQL = """
#     INSERT INTO public.gem_bid_details (
#         bid_id, bid_number, category, ministry, department, organisation,
#         buyer_name, buyer_location, bid_status, quantity_total,
#         bid_start_datetime, bid_end_datetime, bid_open_datetime,
#         bid_validity_days
#     )
#     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
# """

# BD_EXISTING_IDS_SQL = """
#     SELECT bid_id FROM public.gem_bid_details WHERE bid_id IS NOT NULL
# """

# # ---------------------------------------------------------------------------
# # SQL — financial details
# # ---------------------------------------------------------------------------
# FD_INSERT_SQL = """
#     INSERT INTO public.gem_financial_details (
#         bid_id, bid_number, seller_name, offered_item, total_price, rank
#     )
#     VALUES (%s, %s, %s, %s, %s, %s)
# """

# FD_PARENT_SQL = """
#     SELECT bid_id, bid_number
#     FROM public.gem_bid_details
#     WHERE bid_id IS NOT NULL AND bid_number IS NOT NULL
# """

# FD_EXISTING_KEYS_SQL = """
#     SELECT bid_id, bid_number, offered_item, rank
#     FROM public.gem_financial_details
# """

# # ---------------------------------------------------------------------------
# # Logging setup
# # ---------------------------------------------------------------------------

# def setup_logger(log_dir: Path) -> logging.Logger:
#     log_dir.mkdir(parents=True, exist_ok=True)
#     ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
#     log_path = log_dir / f"gem_bid_details_log_{ts}.log"

#     logger = logging.getLogger("gem_loader")
#     logger.setLevel(logging.DEBUG)

#     fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s",
#                             datefmt="%Y-%m-%d %H:%M:%S")

#     fh = logging.FileHandler(log_path, encoding="utf-8")
#     fh.setFormatter(fmt)
#     logger.addHandler(fh)

#     ch = logging.StreamHandler(sys.stdout)
#     ch.setLevel(logging.INFO)
#     ch.setFormatter(fmt)
#     logger.addHandler(ch)

#     logger.info("Log file: %s", log_path)
#     return logger

# # ---------------------------------------------------------------------------
# # DB connection
# # ---------------------------------------------------------------------------

# def get_db_connection() -> psycopg2.extensions.connection:
#     return psycopg2.connect(
#         host=os.environ.get("POSTGRES_HOST", "db"),
#         port=int(os.environ.get("POSTGRES_PORT", "5432")),
#         dbname=os.environ.get("POSTGRES_DB", "tender_analyzer"),
#         user=os.environ.get("POSTGRES_USER", "postgres"),
#         password=os.environ.get("POSTGRES_PASSWORD", "rushabh"),
#     )

# # ---------------------------------------------------------------------------
# # Value parsers — shared
# # ---------------------------------------------------------------------------

# def _to_text(value: str) -> "str | None":
#     stripped = value.strip()
#     return stripped if stripped else None


# def _to_int(value: str) -> "int | None":
#     stripped = value.strip()
#     if not stripped:
#         return None
#     return int(stripped)


# def _to_real(value: str) -> "float | None":
#     stripped = value.strip()
#     if not stripped:
#         return None
#     return float(stripped)


# def _to_timestamp(value: str) -> "datetime | None":
#     stripped = value.strip()
#     if not stripped:
#         return None
#     return datetime.strptime(stripped, "%d-%m-%Y %H:%M:%S")

# # ---------------------------------------------------------------------------
# # Row builders
# # ---------------------------------------------------------------------------

# def build_bd_params(row: dict) -> tuple:
#     """Map one bid-details CSV row to the INSERT parameter tuple."""
#     return (
#         _to_int(row["bid_id"]),
#         _to_text(row["bid_number"]),
#         _to_text(row["category"]),
#         _to_text(row["ministry"]),
#         _to_text(row["department"]),
#         _to_text(row["organisation"]),
#         _to_text(row["buyer_name"]),
#         _to_text(row["buyer_location"]),
#         _to_text(row["bid_status"]),
#         _to_real(row["quantity_total"]),
#         _to_timestamp(row["bid_start_datetime"]),
#         _to_timestamp(row["bid_end_datetime"]),
#         _to_timestamp(row["bid_open_datetime"]),
#         _to_text(row["bid_validity_days"]),
#     )

# def clean_price(value):
#     if not value:
#         return None

#     # keep only digits and decimal point
#     value = re.sub(r"[^\d.]", "", value)

#     return float(value) if value else None

# def build_fd_params(row: dict) -> tuple:
#     """Map one financial-details CSV row to the INSERT parameter tuple."""
#     return (
#         _to_int(row["bid_id"]),
#         _to_text(row["bid_number"]),
#         _to_text(row["seller_name"]),
#         _to_text(row["offered_item"]),
#         clean_price(row["total_price"]),
#         _to_text(row["rank"]),
#     )

# # ---------------------------------------------------------------------------
# # Load 1: gem_bid_details
# # ---------------------------------------------------------------------------

# def load_bid_details(conn: psycopg2.extensions.connection,
#                      logger: logging.Logger,
#                      input_file: Path,
#                      dry_run: bool) -> int:
#     """
#     Load gem_bid_details CSV into public.gem_bid_details.
#     Returns 0 on success, 1 if any rows failed.
#     """
#     start_time = datetime.now()
#     mode_label = "DRY-RUN" if dry_run else "NORMAL"

#     logger.info("=" * 70)
#     logger.info("=== gem_bid_details load started at %s [%s] ===",
#                 start_time.strftime("%Y-%m-%d %H:%M:%S"), mode_label)
#     logger.info("Input file: %s", input_file)

#     rows_read      = 0
#     rows_inserted  = 0
#     rows_duplicate = 0
#     rows_failed    = 0

#     try:
#         conn.autocommit = False

#         with conn.cursor() as cur:
#             # Pre-load existing bid_ids for duplicate detection
#             logger.info("Loading existing bid_ids from public.gem_bid_details ...")
#             cur.execute(BD_EXISTING_IDS_SQL)
#             existing_bid_ids = {row[0] for row in cur.fetchall()}
#             logger.info("Existing bid_ids loaded: %d", len(existing_bid_ids))

#             with open(input_file, newline="", encoding="utf-8") as fh:
#                 reader = csv.DictReader(fh)

#                 for row_num, csv_row in enumerate(reader, start=2):  # row 1 is header
#                     rows_read += 1

#                     # Parse
#                     try:
#                         params = build_bd_params(csv_row)
#                     except (ValueError, KeyError) as exc:
#                         rows_failed += 1
#                         logger.error("Row %d  parse error: %s", row_num, exc)
#                         continue

#                     bid_id = params[0]

#                     # Duplicate check (application-level)
#                     if bid_id in existing_bid_ids:
#                         rows_duplicate += 1
#                         logger.info("Row %d  DUPLICATE bid_id=%s — skipped",
#                                     row_num, bid_id)
#                         continue

#                     # Insert (or dry-run)
#                     if dry_run:
#                         rows_inserted += 1
#                         existing_bid_ids.add(bid_id)
#                         logger.debug("Row %d  DRY-RUN — would insert bid_id=%s",
#                                      row_num, bid_id)
#                     else:
#                         sp = f"sp_{row_num}"
#                         cur.execute(f"SAVEPOINT {sp}")
#                         try:
#                             cur.execute(BD_INSERT_SQL, params)
#                             cur.execute(f"RELEASE SAVEPOINT {sp}")
#                             rows_inserted += 1
#                             existing_bid_ids.add(bid_id)
#                         except Exception as exc:
#                             cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
#                             rows_failed += 1
#                             logger.error("Row %d  insert error (bid_id=%s): %s",
#                                          row_num, bid_id, exc)

#         if dry_run:
#             conn.rollback()
#             logger.info("DRY-RUN — transaction rolled back. No data written.")
#         else:
#             conn.commit()
#             logger.info("Transaction committed.")

#     except Exception as exc:
#         logger.critical("Fatal error during gem_bid_details load: %s", exc)
#         return 1

#     end_time = datetime.now()
#     elapsed  = (end_time - start_time).total_seconds()

#     _log_bd_summary(logger, mode_label, start_time, end_time, elapsed,
#                     rows_read, rows_inserted, rows_duplicate, rows_failed, dry_run)

#     return 1 if rows_failed > 0 else 0


# def _log_bd_summary(logger, mode_label, start_time, end_time, elapsed,
#                     rows_read, rows_inserted, rows_duplicate, rows_failed, dry_run):
#     insert_label = "Rows would insert (dry-run)" if dry_run else "Rows inserted         "
#     lines = [
#         f"=== gem_bid_details load finished at {end_time.strftime('%Y-%m-%d %H:%M:%S')} "
#         f"({elapsed:.2f}s) ===",
#         f"Mode                  : {mode_label}",
#         f"Rows read             : {rows_read}",
#         f"{insert_label} : {rows_inserted}",
#         f"Rows skipped (dupes)  : {rows_duplicate}",
#         f"Rows failed           : {rows_failed}",
#     ]
#     for line in lines:
#         logger.info(line)

#     print()
#     print("--- gem_bid_details Summary ---")
#     print(f"Mode                  : {mode_label}")
#     print(f"Rows read             : {rows_read}")
#     print(f"{insert_label} : {rows_inserted}")
#     print(f"Rows skipped (dupes)  : {rows_duplicate}")
#     print(f"Rows failed           : {rows_failed}")

# # ---------------------------------------------------------------------------
# # Load 2: gem_financial_details
# # ---------------------------------------------------------------------------

# def load_financial_details(conn: psycopg2.extensions.connection,
#                            logger: logging.Logger,
#                            input_file: Path,
#                            dry_run: bool) -> int:
#     """
#     Load gem_financial_details CSV into public.gem_financial_details.

#     Processing strategy:
#       - Validate every row (parent check + duplicate check).
#       - Group valid rows by (bid_id, bid_number).
#       - Insert each group in a single transaction using execute_batch.
#       - Commit per group; rollback and continue on group-level error.
#       - In dry-run mode: validate fully but never INSERT; rollback at the end.

#     Returns 0 on success, 1 if any rows failed.
#     """
#     start_time = datetime.now()
#     mode_label = "DRY-RUN" if dry_run else "NORMAL"

#     logger.info("=" * 70)
#     logger.info("=== gem_financial_details load started at %s [%s] ===",
#                 start_time.strftime("%Y-%m-%d %H:%M:%S"), mode_label)
#     logger.info("Input file: %s", input_file)
#     logger.info("Batch size: %d", BATCH_SIZE)

#     rows_read      = 0
#     rows_inserted  = 0
#     rows_duplicate = 0
#     rows_orphan    = 0
#     rows_failed    = 0

#     try:
#         conn.autocommit = False

#         # ------------------------------------------------------------------
#         # Pre-load reference sets
#         # ------------------------------------------------------------------
#         with conn.cursor() as cur:
#             logger.info("Loading parent keys from public.gem_bid_details ...")
#             cur.execute(FD_PARENT_SQL)
#             parent_keys = {(row[0], row[1]) for row in cur.fetchall()}
#             logger.info("Parent keys loaded: %d", len(parent_keys))

#             logger.info("Loading existing keys from public.gem_financial_details ...")
#             cur.execute(FD_EXISTING_KEYS_SQL)
#             existing_fd_keys = {(row[0], row[1], row[2], row[3]) for row in cur.fetchall()}
#             logger.info("Existing financial-detail keys loaded: %d", len(existing_fd_keys))

#         # ------------------------------------------------------------------
#         # Read CSV → parse → group by (bid_id, bid_number)
#         # ------------------------------------------------------------------
#         # groups: {(bid_id, bid_number): [(row_num, params), ...]}
#         groups = defaultdict(list)

#         with open(input_file, newline="", encoding="utf-8") as fh:
#             reader = csv.DictReader(fh)

#             for row_num, csv_row in enumerate(reader, start=2):
#                 rows_read += 1

#                 try:
#                     params = build_fd_params(csv_row)
#                 except (ValueError, KeyError) as exc:
#                     rows_failed += 1
#                     logger.error("Row %d  parse error: %s | data=%s",
#                                  row_num, exc, dict(csv_row))
#                     continue

#                 bid_id     = params[0]   # index 0
#                 bid_number = params[1]   # index 1
#                 groups[(bid_id, bid_number)].append((row_num, params))

#         logger.info("CSV rows read: %d | Groups: %d", rows_read, len(groups))

#         # ------------------------------------------------------------------
#         # Process each group in its own transaction
#         # ------------------------------------------------------------------
#         for group_key, group_rows in groups.items():
#             bid_id, bid_number = group_key
#             batch_to_insert = []   # [(row_num, params)] — validated, ready to insert

#             # Validate every row in the group
#             for row_num, params in group_rows:
#                 # 1. Parent check
#                 if group_key not in parent_keys:
#                     rows_orphan += 1
#                     logger.info(
#                         "Row %d  ORPHAN bid_id=%s bid_number=%s"
#                         " — no matching row in gem_bid_details, skipped",
#                         row_num, bid_id, bid_number,
#                     )
#                     continue

#                 # 2. Duplicate check (DB + within-CSV)
#                 offered_item = params[3]   # index 3
#                 rank         = params[5]   # index 5
#                 dup_key      = (bid_id, bid_number, offered_item, rank)

#                 if dup_key in existing_fd_keys:
#                     rows_duplicate += 1
#                     logger.info(
#                         "Row %d  DUPLICATE bid_id=%s bid_number=%s"
#                         " offered_item=%s rank=%s — skipped",
#                         row_num, bid_id, bid_number, offered_item, rank,
#                     )
#                     continue

#                 # Track so later rows in the same CSV don't repeat the key
#                 existing_fd_keys.add(dup_key)
#                 batch_to_insert.append((row_num, params))

#             if not batch_to_insert:
#                 continue  # entire group was orphan/duplicate/failed

#             # Insert (or dry-run) the validated batch
#             group_count = len(batch_to_insert)
#             try:
#                 if not dry_run:
#                     with conn.cursor() as cur:
#                         for offset in range(0, group_count, BATCH_SIZE):
#                             chunk = [p for _, p in batch_to_insert[offset:offset + BATCH_SIZE]]
#                             psycopg2.extras.execute_batch(
#                                 cur, FD_INSERT_SQL, chunk, page_size=BATCH_SIZE
#                             )
#                     conn.commit()
#                     rows_inserted += group_count
#                     logger.debug(
#                         "Group (bid_id=%s, bid_number=%s): %d rows committed",
#                         bid_id, bid_number, group_count,
#                     )
#                 else:
#                     # Dry-run: no DB writes; just count
#                     rows_inserted += group_count
#                     logger.debug(
#                         "Group (bid_id=%s, bid_number=%s): DRY-RUN — would insert %d rows",
#                         bid_id, bid_number, group_count,
#                     )

#             except Exception as exc:
#                 conn.rollback()
#                 rows_failed += group_count
#                 rows_inserted -= 0  # nothing was credited yet for this group
#                 # Undo optimistic key tracking so a retry could theoretically work
#                 for _, params in batch_to_insert:
#                     existing_fd_keys.discard(
#                         (params[0], params[1], params[3], params[5])
#                     )
#                 logger.error(
#                     "Group (bid_id=%s, bid_number=%s): transaction error — %d rows"
#                     " rolled back. Error: %s",
#                     bid_id, bid_number, group_count, exc,
#                 )

#         if dry_run:
#             conn.rollback()
#             logger.info("DRY-RUN — all group transactions rolled back. No data written.")

#     except Exception as exc:
#         logger.critical("Fatal error during gem_financial_details load: %s", exc)
#         return 1

#     end_time = datetime.now()
#     elapsed  = (end_time - start_time).total_seconds()

#     _log_fd_summary(logger, mode_label, end_time, elapsed,
#                     rows_read, rows_inserted, rows_duplicate, rows_orphan,
#                     rows_failed, dry_run)

#     return 1 if rows_failed > 0 else 0


# def _log_fd_summary(logger, mode_label, end_time, elapsed,
#                     rows_read, rows_inserted, rows_duplicate, rows_orphan,
#                     rows_failed, dry_run):
#     insert_label = "Rows would insert (dry-run)" if dry_run else "Rows inserted              "
#     lines = [
#         f"=== gem_financial_details load finished at {end_time.strftime('%Y-%m-%d %H:%M:%S')} "
#         f"({elapsed:.2f}s) ===",
#         f"Mode                       : {mode_label}",
#         f"Rows read                  : {rows_read}",
#         f"{insert_label} : {rows_inserted}",
#         f"Rows skipped (duplicates)  : {rows_duplicate}",
#         f"Rows skipped (orphans)     : {rows_orphan}",
#         f"Rows failed                : {rows_failed}",
#     ]
#     for line in lines:
#         logger.info(line)

#     print()
#     print("--- gem_financial_details Summary ---")
#     print(f"Mode                       : {mode_label}")
#     print(f"Rows read                  : {rows_read}")
#     print(f"{insert_label} : {rows_inserted}")
#     print(f"Rows skipped (duplicates)  : {rows_duplicate}")
#     print(f"Rows skipped (orphans)     : {rows_orphan}")
#     print(f"Rows failed                : {rows_failed}")
#     if dry_run:
#         print("Execution mode             : DRY-RUN (no data written)")
#     else:
#         print("Execution mode             : NORMAL")

# # ---------------------------------------------------------------------------
# # Main
# # ---------------------------------------------------------------------------

# def main() -> int:
#     parser = argparse.ArgumentParser(
#         description="Load gem_bid_details and gem_financial_details CSVs into PostgreSQL."
#     )
#     parser.add_argument(
#         "bid_file",
#         help="Path to gem_bid_details CSV file"
#     )
#     parser.add_argument(
#         "financial_file",
#         help="Path to gem_financial_details CSV file"
#     )
#     parser.add_argument(
#         "--dry-run", action="store_true",
#         help="Parse and validate all rows but do not insert or commit."
#     )
#     args    = parser.parse_args()
#     dry_run = args.dry_run

#     # Convert to Path objects
#     bid_file = Path(args.bid_file)
#     financial_file = Path(args.financial_file)

#     # Validate input files exist
#     if not bid_file.exists():
#         print(f"ERROR: Bid file not found: {bid_file}", file=sys.stderr)
#         return 1
#     if not financial_file.exists():
#         print(f"ERROR: Financial file not found: {financial_file}", file=sys.stderr)
#         return 1

#     logger = setup_logger(LOG_DIR)

#     conn = None
#     try:
#         conn = get_db_connection()

#         rc1 = load_bid_details(conn, logger, bid_file, dry_run)
#         rc2 = load_financial_details(conn, logger, financial_file, dry_run)

#     except Exception as exc:
#         if logger:
#             logger.critical("Fatal error establishing DB connection: %s", exc)
#         else:
#             print(f"CRITICAL: {exc}", file=sys.stderr)
#         return 1
#     finally:
#         if conn and not conn.closed:
#             conn.close()

#     return 1 if (rc1 or rc2) else 0

# if __name__ == "__main__":
#     sys.exit(main())

























#!/usr/bin/env python3
"""
load_gem_bid_details.py

Loads two CSV files into PostgreSQL sequentially:
  1. gem_bid_details*.csv        → public.gem_bid_details
  2. gem_financial_details*.csv  → public.gem_financial_details

Run:
    python load_gem_bid_details.py <bid_file> <financial_file> [--dry-run]

Environment variables:
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

Optional:
    BATCH_SIZE  — rows per execute_batch call for financial details (default 500)
"""

import argparse
import csv
import logging
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras


LOG_DIR = Path("/app/logs")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "500"))


# ---------------------------------------------------------------------------
# SQL — bid details
# ---------------------------------------------------------------------------

BD_INSERT_SQL = """
    INSERT INTO public.gem_bid_details (
        bid_id, bid_number, category, ministry, department, organisation,
        buyer_name, buyer_location, bid_status, quantity_total,
        bid_start_datetime, bid_end_datetime, bid_open_datetime,
        bid_validity_days
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

BD_EXISTING_ROWS_SQL = """
    SELECT
        bid_id, bid_number, category, ministry, department, organisation,
        buyer_name, buyer_location, bid_status, quantity_total,
        bid_start_datetime, bid_end_datetime, bid_open_datetime,
        bid_validity_days
    FROM public.gem_bid_details
"""


# ---------------------------------------------------------------------------
# SQL — financial details
# ---------------------------------------------------------------------------

FD_INSERT_SQL = """
    INSERT INTO public.gem_financial_details (
        bid_id, bid_number, seller_name, offered_item, total_price, rank
    )
    VALUES (%s, %s, %s, %s, %s, %s)
"""

FD_PARENT_SQL = """
    SELECT bid_id, bid_number
    FROM public.gem_bid_details
    WHERE bid_id IS NOT NULL AND bid_number IS NOT NULL
"""

FD_EXISTING_KEYS_SQL = """
    SELECT bid_id, bid_number, seller_name, offered_item, total_price, rank
    FROM public.gem_financial_details
"""


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logger(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"gem_bid_details_log_{ts}.log"

    logger = logging.getLogger("gem_loader")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    logger.info("Log file: %s", log_path)
    return logger


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def get_db_connection() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "db"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ.get("POSTGRES_DB", "tender_analyzer"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", "rushabh"),
    )


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------

def _to_text(value: str):
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _to_int(value: str):
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return int(stripped)


def _to_real(value: str):
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return float(stripped)


def _to_timestamp(value: str):
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return datetime.strptime(stripped, "%d-%m-%Y %H:%M:%S")


def clean_price(value):
    if not value:
        return None
    value = re.sub(r"[^\d.]", "", value)
    return float(value) if value else None


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------

def build_bd_params(row: dict) -> tuple:
    return (
        _to_int(row["bid_id"]),
        _to_text(row["bid_number"]),
        _to_text(row["category"]),
        _to_text(row["ministry"]),
        _to_text(row["department"]),
        _to_text(row["organisation"]),
        _to_text(row["buyer_name"]),
        _to_text(row["buyer_location"]),
        _to_text(row["bid_status"]),
        _to_real(row["quantity_total"]),
        _to_timestamp(row["bid_start_datetime"]),
        _to_timestamp(row["bid_end_datetime"]),
        _to_timestamp(row["bid_open_datetime"]),
        _to_text(row["bid_validity_days"]),
    )


def build_fd_params(row: dict) -> tuple:
    return (
        _to_int(row["bid_id"]),
        _to_text(row["bid_number"]),
        _to_text(row["seller_name"]),
        _to_text(row["offered_item"]),
        clean_price(row["total_price"]),
        _to_text(row["rank"]),
    )


# ---------------------------------------------------------------------------
# Load bid details
# ---------------------------------------------------------------------------

def load_bid_details(
    conn: psycopg2.extensions.connection,
    logger: logging.Logger,
    input_file: Path,
    dry_run: bool,
) -> int:
    start_time = datetime.now()
    mode_label = "DRY-RUN" if dry_run else "NORMAL"

    logger.info("=" * 70)
    logger.info(
        "=== gem_bid_details load started at %s [%s] ===",
        start_time.strftime("%Y-%m-%d %H:%M:%S"),
        mode_label,
    )
    logger.info("Input file: %s", input_file)

    rows_read = 0
    rows_inserted = 0
    rows_duplicate = 0
    rows_failed = 0

    try:
        conn.autocommit = False

        with conn.cursor() as cur:
            logger.info("Loading existing bid-detail rows from public.gem_bid_details ...")
            cur.execute(BD_EXISTING_ROWS_SQL)
            existing_bd_keys = {tuple(row) for row in cur.fetchall()}
            logger.info("Existing bid-detail keys loaded: %d", len(existing_bd_keys))

            with open(input_file, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)

                for row_num, csv_row in enumerate(reader, start=2):
                    rows_read += 1

                    try:
                        params = build_bd_params(csv_row)
                    except (ValueError, KeyError) as exc:
                        rows_failed += 1
                        logger.error("Row %d parse error: %s", row_num, exc)
                        continue

                    dup_key = params

                    if dup_key in existing_bd_keys:
                        rows_duplicate += 1
                        logger.info("Row %d DUPLICATE full bid-detail row — skipped", row_num)
                        continue

                    if dry_run:
                        rows_inserted += 1
                        existing_bd_keys.add(dup_key)
                    else:
                        sp = f"sp_{row_num}"
                        cur.execute(f"SAVEPOINT {sp}")
                        try:
                            cur.execute(BD_INSERT_SQL, params)
                            cur.execute(f"RELEASE SAVEPOINT {sp}")
                            rows_inserted += 1
                            existing_bd_keys.add(dup_key)
                        except Exception as exc:
                            cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                            rows_failed += 1
                            logger.error(
                                "Row %d insert error (bid_id=%s, bid_number=%s): %s",
                                row_num, params[0], params[1], exc,
                            )

        if dry_run:
            conn.rollback()
            logger.info("DRY-RUN — transaction rolled back. No data written.")
        else:
            conn.commit()
            logger.info("Transaction committed.")

    except Exception as exc:
        logger.critical("Fatal error during gem_bid_details load: %s", exc)
        return 1

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    _log_bd_summary(
        logger, mode_label, end_time, elapsed,
        rows_read, rows_inserted, rows_duplicate, rows_failed, dry_run
    )

    return 1 if rows_failed > 0 else 0


def _log_bd_summary(
    logger, mode_label, end_time, elapsed,
    rows_read, rows_inserted, rows_duplicate, rows_failed, dry_run
):
    insert_label = "Rows would insert (dry-run)" if dry_run else "Rows inserted"
    logger.info(
        "=== gem_bid_details load finished at %s (%.2fs) ===",
        end_time.strftime("%Y-%m-%d %H:%M:%S"),
        elapsed,
    )
    logger.info("Mode                 : %s", mode_label)
    logger.info("Rows read            : %d", rows_read)
    logger.info("%s : %d", insert_label, rows_inserted)
    logger.info("Rows skipped (dupes) : %d", rows_duplicate)
    logger.info("Rows failed          : %d", rows_failed)


# ---------------------------------------------------------------------------
# Load financial details
# ---------------------------------------------------------------------------

def load_financial_details(
    conn: psycopg2.extensions.connection,
    logger: logging.Logger,
    input_file: Path,
    dry_run: bool,
) -> int:
    start_time = datetime.now()
    mode_label = "DRY-RUN" if dry_run else "NORMAL"

    logger.info("=" * 70)
    logger.info(
        "=== gem_financial_details load started at %s [%s] ===",
        start_time.strftime("%Y-%m-%d %H:%M:%S"),
        mode_label,
    )
    logger.info("Input file: %s", input_file)
    logger.info("Batch size: %d", BATCH_SIZE)

    rows_read = 0
    rows_inserted = 0
    rows_duplicate = 0
    rows_orphan = 0
    rows_failed = 0

    try:
        conn.autocommit = False

        with conn.cursor() as cur:
            logger.info("Loading parent keys from public.gem_bid_details ...")
            cur.execute(FD_PARENT_SQL)
            parent_keys = {(row[0], row[1]) for row in cur.fetchall()}
            logger.info("Parent keys loaded: %d", len(parent_keys))

            logger.info("Loading existing keys from public.gem_financial_details ...")
            cur.execute(FD_EXISTING_KEYS_SQL)
            existing_fd_keys = {tuple(row) for row in cur.fetchall()}
            logger.info("Existing financial-detail keys loaded: %d", len(existing_fd_keys))

        groups = defaultdict(list)

        with open(input_file, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)

            for row_num, csv_row in enumerate(reader, start=2):
                rows_read += 1

                try:
                    params = build_fd_params(csv_row)
                except (ValueError, KeyError) as exc:
                    rows_failed += 1
                    logger.error("Row %d parse error: %s | data=%s", row_num, exc, dict(csv_row))
                    continue

                bid_id = params[0]
                bid_number = params[1]
                groups[(bid_id, bid_number)].append((row_num, params))

        logger.info("CSV rows read: %d | Groups: %d", rows_read, len(groups))

        for group_key, group_rows in groups.items():
            bid_id, bid_number = group_key
            batch_to_insert = []

            for row_num, params in group_rows:
                if group_key not in parent_keys:
                    rows_orphan += 1
                    logger.info(
                        "Row %d ORPHAN bid_id=%s bid_number=%s — no matching row in gem_bid_details, skipped",
                        row_num, bid_id, bid_number,
                    )
                    continue

                dup_key = params

                if dup_key in existing_fd_keys:
                    rows_duplicate += 1
                    logger.info("Row %d DUPLICATE full financial-detail row — skipped", row_num)
                    continue

                existing_fd_keys.add(dup_key)
                batch_to_insert.append((row_num, params))

            if not batch_to_insert:
                continue

            group_count = len(batch_to_insert)

            try:
                if not dry_run:
                    with conn.cursor() as cur:
                        for offset in range(0, group_count, BATCH_SIZE):
                            chunk = [p for _, p in batch_to_insert[offset:offset + BATCH_SIZE]]
                            psycopg2.extras.execute_batch(
                                cur, FD_INSERT_SQL, chunk, page_size=BATCH_SIZE
                            )
                    conn.commit()
                    rows_inserted += group_count
                    logger.debug(
                        "Group (bid_id=%s, bid_number=%s): %d rows committed",
                        bid_id, bid_number, group_count,
                    )
                else:
                    rows_inserted += group_count
                    logger.debug(
                        "Group (bid_id=%s, bid_number=%s): DRY-RUN — would insert %d rows",
                        bid_id, bid_number, group_count,
                    )

            except Exception as exc:
                conn.rollback()
                rows_failed += group_count

                for _, params in batch_to_insert:
                    existing_fd_keys.discard(params)

                logger.error(
                    "Group (bid_id=%s, bid_number=%s): transaction error — %d rows rolled back. Error: %s",
                    bid_id, bid_number, group_count, exc,
                )

        if dry_run:
            conn.rollback()
            logger.info("DRY-RUN — all group transactions rolled back. No data written.")

    except Exception as exc:
        logger.critical("Fatal error during gem_financial_details load: %s", exc)
        return 1

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    _log_fd_summary(
        logger, mode_label, end_time, elapsed,
        rows_read, rows_inserted, rows_duplicate, rows_orphan, rows_failed, dry_run
    )

    return 1 if rows_failed > 0 else 0


def _log_fd_summary(
    logger, mode_label, end_time, elapsed,
    rows_read, rows_inserted, rows_duplicate, rows_orphan, rows_failed, dry_run
):
    insert_label = "Rows would insert (dry-run)" if dry_run else "Rows inserted"
    logger.info(
        "=== gem_financial_details load finished at %s (%.2fs) ===",
        end_time.strftime("%Y-%m-%d %H:%M:%S"),
        elapsed,
    )
    logger.info("Mode                      : %s", mode_label)
    logger.info("Rows read                 : %d", rows_read)
    logger.info("%s : %d", insert_label, rows_inserted)
    logger.info("Rows skipped (duplicates) : %d", rows_duplicate)
    logger.info("Rows skipped (orphans)    : %d", rows_orphan)
    logger.info("Rows failed               : %d", rows_failed)


# ---------------------------------------------------------------------------
# Reusable helpers for admin upload
# ---------------------------------------------------------------------------

def resolve_upload_files(files: list[Path]) -> tuple[Path, Path]:
    bid_file = None
    financial_file = None

    for f in files:
        name = f.name.lower()
        if name.startswith("gem_bid_details"):
            bid_file = f
        elif name.startswith("gem_financial_details"):
            financial_file = f

    if not bid_file or not financial_file:
        raise ValueError(
            "Both files starting with 'gem_bid_details' and "
            "'gem_financial_details' are required."
        )

    return bid_file, financial_file


def run_gem_csv_import(bid_file: Path, financial_file: Path, dry_run: bool = False) -> dict:
    if not bid_file.exists():
        raise FileNotFoundError(f"Bid file not found: {bid_file}")
    if not financial_file.exists():
        raise FileNotFoundError(f"Financial file not found: {financial_file}")

    logger = setup_logger(LOG_DIR)
    conn = None

    try:
        conn = get_db_connection()

        rc1 = load_bid_details(conn, logger, bid_file, dry_run)
        rc2 = load_financial_details(conn, logger, financial_file, dry_run)

        return {
            "success": not (rc1 or rc2),
            "bid_status": "success" if rc1 == 0 else "failed",
            "financial_status": "success" if rc2 == 0 else "failed",
            "dry_run": dry_run,
        }

    except Exception as exc:
        logger.exception("Import failed")
        return {
            "success": False,
            "bid_status": "failed",
            "financial_status": "failed",
            "dry_run": dry_run,
            "error": str(exc),
        }
    finally:
        if conn and not conn.closed:
            conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load gem_bid_details and gem_financial_details CSVs into PostgreSQL."
    )
    parser.add_argument("bid_file", help="Path to gem_bid_details CSV file")
    parser.add_argument("financial_file", help="Path to gem_financial_details CSV file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate all rows but do not insert or commit.",
    )
    args = parser.parse_args()

    bid_file = Path(args.bid_file)
    financial_file = Path(args.financial_file)

    if not bid_file.exists():
        print(f"ERROR: Bid file not found: {bid_file}", file=sys.stderr)
        return 1
    if not financial_file.exists():
        print(f"ERROR: Financial file not found: {financial_file}", file=sys.stderr)
        return 1

    result = run_gem_csv_import(
        bid_file=bid_file,
        financial_file=financial_file,
        dry_run=args.dry_run,
    )

    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())