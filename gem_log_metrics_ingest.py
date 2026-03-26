"""
gem_log_metrics_ingest01.py

Incrementally ingests GeM run logs into:
- log_metrics
- gem_log_ingest_state

Also enriches each run with email notification info from:
- gem_email_notifications.log

Usage:
  docker compose exec web python gem_log_metrics_ingest01.py
  docker compose exec web python gem_log_metrics_ingest01.py --reset-state
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from typing import Any, Dict, Optional, Tuple, List

from sqlalchemy import text
from database_config import engine

LOG_FILE = "gem_tenders.log"
EMAIL_LOG_FILE = "gem_email_notifications.log"

RUNTIME_ALERT_THRESHOLD_SECONDS = 20 * 60  # 20 minutes


# -----------------------------
# DDL
# -----------------------------
DDL_RUN_METRICS_V2 = """
CREATE TABLE IF NOT EXISTS log_metrics (
  id BIGSERIAL PRIMARY KEY,

  org_id INTEGER NULL,
  keywords_used TEXT NULL,

  run_started_at TIMESTAMP NULL,
  run_finished_at TIMESTAMP NULL,
  duration_seconds INTEGER NULL,

  matched_tenders INTEGER NULL,
  tenders_analyzed_with_api INTEGER NULL,
  tenders_filtered_out INTEGER NULL,

  api_calls INTEGER NULL,
  tokens_used BIGINT NULL,

  email_status TEXT NULL,
  email_note TEXT NULL,
  email_recipients_count INTEGER NULL,
  email_tenders_count INTEGER NULL,

  memory_usage_mb NUMERIC(10,2) NULL,
  chrome_closed BOOLEAN NOT NULL DEFAULT FALSE,

  status TEXT NOT NULL DEFAULT 'INCOMPLETE',
  error_messages TEXT NULL,

  flag_status TEXT NOT NULL DEFAULT 'GREEN',
  flag_note TEXT NULL,
  flag_acknowledged_at TIMESTAMP NULL,

  log_file TEXT NOT NULL DEFAULT 'gem_tenders.log',
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_gem_log_run_metrics_v2_org_time
  ON log_metrics (org_id, run_finished_at DESC);
"""

DDL_INGEST_STATE = """
CREATE TABLE IF NOT EXISTS gem_log_ingest_state (
  log_file TEXT PRIMARY KEY,
  byte_offset BIGINT NOT NULL DEFAULT 0,
  partial_run JSONB NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
"""

# -----------------------------
# Regex
# -----------------------------
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+-\s+(.+)$")

START_RE = re.compile(r"GeM Tender Analyzer", re.IGNORECASE)
SUCCESS_RE = re.compile(r"completed successfully", re.IGNORECASE)

ORG_RE = re.compile(r"\borganization\s+(\d+)\b", re.IGNORECASE)
KEYWORD_RE = re.compile(r"Searching for keyword:\s*'([^']+)'", re.IGNORECASE)
SUMMARY_HEADER_RE = re.compile(r"===\s*Analysis Summary\s*===", re.IGNORECASE)

MATCHED_ANALYZED_RE = re.compile(r"Found\s+(\d+)\s+matching tenders out of\s+\d+\s+analyzed", re.IGNORECASE)
ANALYZED_WITH_API_RE = re.compile(r"Tenders analyzed with API:\s*(\d+)", re.IGNORECASE)
FILTERED_RE = re.compile(r"Tenders filtered out.*:\s*(\d+)", re.IGNORECASE)
API_CALLS_RE = re.compile(r"Total API calls made:\s*(\d+)", re.IGNORECASE)
TOKENS_RE = re.compile(r"Total tokens used:\s*(\d+)", re.IGNORECASE)

MEMORY_RE = re.compile(r"Memory usage:\s*([\d.]+)\s*MB", re.IGNORECASE)
CHROME_CLOSED_RE = re.compile(r"Closed Chrome browser", re.IGNORECASE)

ERROR_LINE_RE = re.compile(r"\s-\sERROR\s-\s", re.IGNORECASE)
TRACEBACK_RE = re.compile(r"^Traceback \(most recent call last\):")

# Email log patterns
EMAIL_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+-\s+(.+)$")
EMAIL_START_RE = re.compile(r"Starting email notifications for organization\s+(\d+)", re.IGNORECASE)
NO_EMAIL_NEEDED_RE = re.compile(r"No recent matching tenders found for organization\s+(\d+)", re.IGNORECASE)
EMAIL_SENT_RE = re.compile(
    r"Email sent for search config\s+\d+\s+to\s+(\d+)\s+recipients\s+\((\d+)\s+tenders?\)",
    re.IGNORECASE,
)
EMAIL_SUCCESS_RE = re.compile(r"Email notification process completed successfully", re.IGNORECASE)
EMAIL_FAIL_RE = re.compile(r"Failed to send email|Email notification process failed", re.IGNORECASE)


def parse_ts(line: str) -> Tuple[Optional[dt.datetime], str]:
    m = TS_RE.match(line)
    if not m:
        return None, line
    try:
        ts = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")
    except Exception:
        return None, line
    return ts, m.group(2)


def parse_email_ts(line: str) -> Tuple[Optional[dt.datetime], str]:
    m = EMAIL_TS_RE.match(line)
    if not m:
        return None, line
    try:
        ts = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S,%f")
    except Exception:
        return None, line
    return ts, m.group(2)


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


# -----------------------------
# DB helpers
# -----------------------------
def ensure_tables() -> None:
    with engine.begin() as conn:
        conn.execute(text(DDL_RUN_METRICS_V2))
        conn.execute(text(DDL_INGEST_STATE))

        conn.execute(text("ALTER TABLE log_metrics ADD COLUMN IF NOT EXISTS duration_seconds INTEGER NULL"))
        conn.execute(text("ALTER TABLE log_metrics ADD COLUMN IF NOT EXISTS email_status TEXT NULL"))
        conn.execute(text("ALTER TABLE log_metrics ADD COLUMN IF NOT EXISTS email_note TEXT NULL"))
        conn.execute(text("ALTER TABLE log_metrics ADD COLUMN IF NOT EXISTS email_recipients_count INTEGER NULL"))
        conn.execute(text("ALTER TABLE log_metrics ADD COLUMN IF NOT EXISTS email_tenders_count INTEGER NULL"))
        conn.execute(text("ALTER TABLE log_metrics ADD COLUMN IF NOT EXISTS flag_status TEXT NOT NULL DEFAULT 'GREEN'"))
        conn.execute(text("ALTER TABLE log_metrics ADD COLUMN IF NOT EXISTS flag_note TEXT NULL"))
        conn.execute(text("ALTER TABLE log_metrics ADD COLUMN IF NOT EXISTS flag_acknowledged_at TIMESTAMP NULL"))
        conn.execute(text("ALTER TABLE log_metrics ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW()"))
        conn.execute(text("ALTER TABLE log_metrics ALTER COLUMN created_at SET DEFAULT NOW()"))

        # remove old unused columns if present
        conn.execute(text("ALTER TABLE log_metrics DROP COLUMN IF EXISTS analyzed_total"))
        conn.execute(text("ALTER TABLE log_metrics DROP COLUMN IF EXISTS avg_tokens_per_api_tender"))
        conn.execute(text("ALTER TABLE log_metrics DROP COLUMN IF EXISTS estimated_tokens_saved_by_filtering"))
        conn.execute(text("ALTER TABLE log_metrics DROP COLUMN IF EXISTS matching_csv_path"))
        conn.execute(text("ALTER TABLE log_metrics DROP COLUMN IF EXISTS all_csv_path"))
        conn.execute(text("ALTER TABLE log_metrics DROP COLUMN IF EXISTS email_sent"))
        conn.execute(text("ALTER TABLE log_metrics DROP COLUMN IF EXISTS mark"))


def load_state(log_file: str) -> Dict[str, Any]:
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT log_file, byte_offset, partial_run FROM gem_log_ingest_state WHERE log_file = :f"),
            {"f": log_file},
        ).mappings().first()

        if not row:
            conn.execute(
                text("INSERT INTO gem_log_ingest_state (log_file, byte_offset, partial_run) VALUES (:f, 0, NULL)"),
                {"f": log_file},
            )
            return {"log_file": log_file, "byte_offset": 0, "partial_run": None}

        return {
            "log_file": row["log_file"],
            "byte_offset": int(row["byte_offset"] or 0),
            "partial_run": row["partial_run"],
        }


def save_state(log_file: str, byte_offset: int, partial_run: Optional[Dict[str, Any]]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE gem_log_ingest_state
                SET byte_offset = :o,
                    partial_run = CAST(:p AS JSONB),
                    updated_at = NOW()
                WHERE log_file = :f
                """
            ),
            {"f": log_file, "o": int(byte_offset), "p": _json_dumps(partial_run) if partial_run else None},
        )


def insert_run(run: Dict[str, Any]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO log_metrics (
                  org_id, keywords_used,
                  run_started_at, run_finished_at, duration_seconds,
                  matched_tenders, tenders_analyzed_with_api, tenders_filtered_out,
                  api_calls, tokens_used,
                  email_status, email_note, email_recipients_count, email_tenders_count,
                  memory_usage_mb, chrome_closed,
                  status, error_messages,
                  flag_status, flag_note, flag_acknowledged_at,
                  log_file, created_at
                ) VALUES (
                  :org_id, :keywords_used,
                  :run_started_at, :run_finished_at, :duration_seconds,
                  :matched_tenders, :tenders_analyzed_with_api, :tenders_filtered_out,
                  :api_calls, :tokens_used,
                  :email_status, :email_note, :email_recipients_count, :email_tenders_count,
                  :memory_usage_mb, :chrome_closed,
                  :status, :error_messages,
                  :flag_status, :flag_note, :flag_acknowledged_at,
                  :log_file, NOW()
                )
                """
            ),
            run,
        )


# -----------------------------
# Email parsing
# -----------------------------
def parse_email_log(email_log_path: str) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []

    if not os.path.exists(email_log_path):
        return blocks

    current: Optional[Dict[str, Any]] = None

    with open(email_log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            ts, raw = parse_email_ts(line)
            raw = raw.strip()

            m_start = EMAIL_START_RE.search(raw)
            if m_start:
                if current:
                    blocks.append(current)
                current = {
                    "org_id": int(m_start.group(1)),
                    "started_at": ts,
                    "finished_at": ts,
                    "email_status": "NONE",
                    "email_note": "No notification data",
                    "email_recipients_count": 0,
                    "email_tenders_count": 0,
                }
                continue

            if current is None:
                continue

            if ts:
                current["finished_at"] = ts

            m_no_email = NO_EMAIL_NEEDED_RE.search(raw)
            if m_no_email:
                current["email_status"] = "NO_EMAIL_NEEDED"
                current["email_note"] = "No recent matching tenders found"
                current["email_recipients_count"] = 0
                current["email_tenders_count"] = 0
                continue

            m_sent = EMAIL_SENT_RE.search(raw)
            if m_sent:
                recipients = int(m_sent.group(1))
                tenders = int(m_sent.group(2))
                current["email_status"] = "SENT"
                current["email_note"] = f"Sent to {recipients} recipients for {tenders} tender(s)"
                current["email_recipients_count"] = recipients
                current["email_tenders_count"] = tenders
                continue

            if EMAIL_FAIL_RE.search(raw):
                current["email_status"] = "FAILED"
                current["email_note"] = "Email delivery failed"
                continue

            if EMAIL_SUCCESS_RE.search(raw):
                if current["email_status"] == "NONE":
                    current["email_status"] = "NO_EMAIL_NEEDED"
                    current["email_note"] = "Notification process completed"

    if current:
        blocks.append(current)

    return blocks


def enrich_email_fields(run: Dict[str, Any], email_blocks: List[Dict[str, Any]]) -> None:
    org_id = run.get("org_id")
    finished_at = run.get("run_finished_at")

    run["email_status"] = "NONE"
    run["email_note"] = "No notification data"
    run["email_recipients_count"] = 0
    run["email_tenders_count"] = 0

    if not org_id or not finished_at:
        return

    best_block = None
    best_delta = None

    for block in email_blocks:
        if block.get("org_id") != org_id:
            continue

        block_started = block.get("started_at")
        if not block_started:
            continue

        delta = abs((block_started - finished_at).total_seconds())

        if delta <= 30 * 60:
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_block = block

    if best_block:
        run["email_status"] = best_block.get("email_status", "NONE")
        run["email_note"] = best_block.get("email_note", "No notification data")
        run["email_recipients_count"] = best_block.get("email_recipients_count", 0)
        run["email_tenders_count"] = best_block.get("email_tenders_count", 0)


# -----------------------------
# Run accumulator
# -----------------------------
def new_run(log_file: str, started_at: Optional[dt.datetime]) -> Dict[str, Any]:
    return {
        "org_id": None,
        "keywords_used": None,

        "run_started_at": started_at,
        "run_finished_at": None,
        "duration_seconds": None,

        "matched_tenders": None,
        "tenders_analyzed_with_api": None,
        "tenders_filtered_out": None,

        "api_calls": None,
        "tokens_used": None,

        "email_status": "NONE",
        "email_note": "No notification data",
        "email_recipients_count": 0,
        "email_tenders_count": 0,

        "memory_usage_mb": None,
        "chrome_closed": False,

        "status": "INCOMPLETE",
        "error_messages": "",

        "flag_status": "GREEN",
        "flag_note": None,
        "flag_acknowledged_at": None,

        "log_file": log_file,

        "_summary_seen": False,
        "_keywords": [],
        "_has_errors": False,
        "_saw_success": False,
    }


def _append_error(run: Dict[str, Any], raw: str) -> None:
    msg = raw.strip()
    if not msg:
        return
    existing = run.get("error_messages") or ""
    combined = (existing + "\n" + msg).strip() if existing else msg
    run["error_messages"] = combined[-20000:]


def update_from_line(run: Dict[str, Any], ts: Optional[dt.datetime], raw: str) -> None:
    m = ORG_RE.search(raw)
    if m and run.get("org_id") is None:
        run["org_id"] = int(m.group(1))

    m = KEYWORD_RE.search(raw)
    if m:
        kw = m.group(1).strip()
        if kw and kw not in run["_keywords"]:
            run["_keywords"].append(kw)

    if SUMMARY_HEADER_RE.search(raw):
        run["_summary_seen"] = True

    m = MATCHED_ANALYZED_RE.search(raw)
    if m:
        run["matched_tenders"] = int(m.group(1))

    m = ANALYZED_WITH_API_RE.search(raw)
    if m:
        run["tenders_analyzed_with_api"] = int(m.group(1))

    m = FILTERED_RE.search(raw)
    if m:
        run["tenders_filtered_out"] = int(m.group(1))

    m = API_CALLS_RE.search(raw)
    if m:
        run["api_calls"] = int(m.group(1))

    m = TOKENS_RE.search(raw)
    if m:
        run["tokens_used"] = int(m.group(1))

    m = MEMORY_RE.search(raw)
    if m:
        run["memory_usage_mb"] = float(m.group(1))

    if CHROME_CLOSED_RE.search(raw):
        run["chrome_closed"] = True

    if ERROR_LINE_RE.search(raw) or TRACEBACK_RE.search(raw):
        run["_has_errors"] = True
        _append_error(run, raw)

    if SUCCESS_RE.search(raw):
        run["_saw_success"] = True


def should_start_new_run(raw: str) -> bool:
    return bool(START_RE.search(raw)) and "Pagination" in raw


def should_close_run(raw: str) -> bool:
    return bool(SUCCESS_RE.search(raw))


def finalize_run(run: Dict[str, Any], email_blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    kws = run.get("_keywords") or []
    run["keywords_used"] = ", ".join(kws) if kws else None

    if run.get("run_started_at") and run.get("run_finished_at"):
        run["duration_seconds"] = int((run["run_finished_at"] - run["run_started_at"]).total_seconds())
    else:
        run["duration_seconds"] = None

    if run.get("_saw_success"):
        run["status"] = "SUCCESS"
    elif run.get("_has_errors"):
        run["status"] = "FAILED"
    else:
        run["status"] = "INCOMPLETE"

    enrich_email_fields(run, email_blocks)

    duration = run.get("duration_seconds")
    if duration is not None and duration > RUNTIME_ALERT_THRESHOLD_SECONDS:
        run["flag_status"] = "RED"
        run["flag_note"] = (
            f"Time taken for the job to run seems higher than threshold "
            f"({duration} seconds > {RUNTIME_ALERT_THRESHOLD_SECONDS} seconds)."
        )
    else:
        run["flag_status"] = "GREEN"
        run["flag_note"] = None

    run.pop("_summary_seen", None)
    run.pop("_keywords", None)
    run.pop("_has_errors", None)
    run.pop("_saw_success", None)
    return run


# -----------------------------
# Main
# -----------------------------
def ingest(log_file: str, reset_state: bool = False) -> Dict[str, Any]:
    ensure_tables()

    state = load_state(log_file)
    if reset_state:
        save_state(log_file, 0, None)
        state["byte_offset"] = 0
        state["partial_run"] = None

    byte_offset = int(state.get("byte_offset") or 0)
    partial_run = state.get("partial_run")
    run: Optional[Dict[str, Any]] = partial_run if isinstance(partial_run, dict) else None

    path = log_file if os.path.isabs(log_file) else os.path.join(os.path.dirname(__file__), log_file)
    email_log_path = EMAIL_LOG_FILE if os.path.isabs(EMAIL_LOG_FILE) else os.path.join(os.path.dirname(__file__), EMAIL_LOG_FILE)

    if not os.path.exists(path):
        return {"ok": False, "error": f"Log file not found: {path}"}

    email_blocks = parse_email_log(email_log_path)

    with open(path, "rb") as f:
        f.seek(byte_offset)
        chunk = f.read()
        new_offset = f.tell()

    if not chunk:
        return {
            "ok": True,
            "message": "No new log bytes to ingest.",
            "inserted": 0,
            "processed_lines": 0,
            "byte_offset": byte_offset,
            "has_partial_run": run is not None,
        }

    text_data = chunk.decode("utf-8", errors="replace")
    lines = text_data.splitlines()

    inserted = 0
    processed_lines = 0

    for line in lines:
        processed_lines += 1
        ts, rest = parse_ts(line)
        raw = rest

        if should_start_new_run(raw):
            if run is not None and run.get("run_finished_at") is None:
                run["run_finished_at"] = ts or run.get("run_finished_at")
                insert_run(finalize_run(run, email_blocks))
                inserted += 1
                run = None

            run = new_run(log_file=log_file, started_at=ts)

        if run is None:
            continue

        update_from_line(run, ts, raw)

        if should_close_run(raw):
            run["run_finished_at"] = ts or run.get("run_finished_at")
            run["_saw_success"] = True
            insert_run(finalize_run(run, email_blocks))
            inserted += 1
            run = None

    save_state(log_file, new_offset, run)

    return {
        "ok": True,
        "inserted": inserted,
        "processed_lines": processed_lines,
        "byte_offset": new_offset,
        "has_partial_run": run is not None,
        "partial_status": run.get("status") if run else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-file", default="gem_tenders.log")
    ap.add_argument("--reset-state", action="store_true")
    args = ap.parse_args()

    res = ingest(args.log_file, reset_state=args.reset_state)
    if not res.get("ok"):
        raise SystemExit(res.get("error") or "Ingest failed")

    print(
        f"OK | inserted={res['inserted']} | "
        f"lines={res['processed_lines']} | "
        f"byte_offset={res['byte_offset']} | "
        f"partial={res.get('has_partial_run')}"
    )


if __name__ == "__main__":
    main()