import os
# import sqlite3
import json
import re
import urllib.request
import urllib.error
from urllib.parse import quote, unquote
from flask import render_template, request, jsonify, url_for

from database_config import engine
from sqlalchemy import text
# NOTE:
# For POC runner, keep login_required commented.
# When merging back into TenderGyan, uncomment and add @login_required.
# from flask_login import login_required

# DEFAULT_PRICING_DB_PATH = os.environ.get(
#     "PRICING_DB_PATH",
#     r"D:\RND\gem_tender_extraction\pricing_db.db"
# )

BID_TABLE = "gem_bid_details"
FIN_TABLE = "gem_financial_details"


# def _connect(db_path: str):
#     conn = sqlite3.connect(db_path)
#     conn.row_factory = sqlite3.Row
#     return conn


def _normalized_bid_end_date_sql(alias: str = "b"):
    """
    Returns a SQL expression that tries to normalize bid_end_datetime to YYYY-MM-DD for:
      - 'YYYY-MM-DD...' formats
      - 'DD-MM-YYYY...' formats
    """
    col = f"{alias}.bid_end_datetime"
    return f"""
    CASE
      WHEN {col} IS NULL OR TRIM({col}) = '' THEN NULL
      WHEN SUBSTRING({col} FROM 5 FOR 1) = '-' THEN SUBSTRING({col} FROM 1 FOR 10)  -- YYYY-MM-DD
      WHEN SUBSTRING({col} FROM 3 FOR 1) = '-' THEN
        SUBSTRING({col} FROM 7 FOR 4) || '-' || SUBSTRING({col} FROM 4 FOR 2) || '-' || SUBSTRING({col} FROM 1 FOR 2)  -- DD-MM-YYYY
      ELSE SUBSTRING({col} FROM 1 FOR 10)
    END
    """


# -------------------------
# Gemini NL->SQL helpers
# -------------------------
def _gemini_generate_sql(api_key: str, question: str, schema_prompt: str, model: str = None) -> dict:
    """
    Calls Gemini REST API to produce SQL + short explanation in JSON.
    Returns dict with keys: sql, explanation (best-effort).
    """
    model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    system_instructions = (
        "You are a senior data analyst. Convert the user's business question into a SINGLE PostgreSQL SELECT query.\n"
        "Rules:\n"
        "- Output ONLY valid JSON with keys: sql, explanation.\n"
        "- sql must be a single SELECT statement (no INSERT/UPDATE/DELETE/DDL/PRAGMA).\n"
        "- Prefer explicit column names.\n"
        "- If question is ambiguous, make a reasonable assumption and mention it in explanation.\n"
        "- Keep results practical; if missing, add LIMIT 50.\n"
    )

    prompt = f"{system_instructions}\n\nDATA DICTIONARY:\n{schema_prompt}\n\nUSER QUESTION:\n{question}\n"

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 512
        }
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Gemini HTTPError {e.code}: {body}")
    except Exception as e:
        raise RuntimeError(f"Gemini request failed: {e}")

    # Extract text
    text = ""
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        text = json.dumps(data)

    text = (text or "").strip()

    # Remove accidental code fences
    text = re.sub(r"^```(json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # Try to parse JSON from model output
    # Try direct JSON parse
    try:
        obj = json.loads(text)
        return {
            "sql": (obj.get("sql") or "").strip(),
            "explanation": (obj.get("explanation") or "").strip()
        }
    except Exception:
        pass

    # Try to extract JSON substring
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        try:
            obj = json.loads(json_match.group())
            return {
                "sql": (obj.get("sql") or "").strip(),
                "explanation": (obj.get("explanation") or "").strip()
            }
        except Exception:
            pass

    # Fallback: assume raw SQL
    return {"sql": text.strip(), "explanation": ""}



def _is_safe_select_sql(sql: str) -> bool:
    if not sql:
        return False

    s = sql.strip().lower()

    # must start with select or with clause (CTE) leading to select
    if not (s.startswith("select") or s.startswith("with")):
        return False

    # Allow one trailing semicolon, but block any other semicolons
    s_stripped = s.strip()
    if s_stripped.endswith(";"):
        s_stripped = s_stripped[:-1].strip()

    if ";" in s_stripped:
        return False


    banned = [
        "insert", "update", "delete", "drop", "alter", "create", "attach",
        "detach", "pragma", "reindex", "vacuum", "replace", "truncate"
    ]
    for kw in banned:
        if re.search(rf"\b{kw}\b", s):
            return False

    return True


def _ensure_limit(sql: str, default_limit: int = 50) -> str:
    s = (sql or "").strip()
    if re.search(r"\blimit\b", s, flags=re.IGNORECASE):
        return s
    return s + f"\nLIMIT {int(default_limit)}"


def init_pricing_intelligence_routes(app):
    """
    Registers Pricing Intelligence pages + APIs.
    - Main dashboard: /pricing-intelligence
    - Bid drilldown: /pricing-intelligence/bid/<bid_number>
    - Seller wins drilldown: /pricing-intelligence/seller/<seller_name>/wins
    """

    # def _db_path():
    #     return app.config.get("PRICING_DB_PATH", DEFAULT_PRICING_DB_PATH)

    # -------------------------
    # Pages
    # -------------------------
    @app.route("/pricing-intelligence", methods=["GET"])
    # @login_required
    def pricing_intelligence_page():
        return render_template(
            "pricing_intelligence.html",
            title="Tender Pricing Intelligence",
            url_prefix=app.config.get("URL_PREFIX", ""),
            drilldown=None,
        )

    @app.route("/pricing-intelligence/bid/<path:bid_number>", methods=["GET"])
    # @login_required
    def pricing_intelligence_bid_drilldown(bid_number):
        # bid_number may contain slashes (e.g., GEM/2025/B/xxxx) so we use <path:...>
        return render_template(
            "pricing_intelligence.html",
            title=f"Bid Drilldown: {bid_number}",
            url_prefix=app.config.get("URL_PREFIX", ""),
            drilldown="bid",
            bid_number=bid_number,
        )

    @app.route("/pricing-intelligence/seller/<path:seller_name>/wins", methods=["GET"])
    # @login_required
    def pricing_intelligence_seller_wins_drilldown(seller_name):
        return render_template(
            "pricing_intelligence.html",
            title=f"Wins Drilldown: {seller_name}",
            url_prefix=app.config.get("URL_PREFIX", ""),
            drilldown="seller_wins",
            seller_name=seller_name,
        )

    # -------------------------
    # APIs
    # -------------------------
    @app.route("/api/pricing-intelligence/search", methods=["POST"])
    # @login_required
    def pricing_intelligence_search():
        payload = request.get_json(silent=True) or {}

        # Get all filter parameters including tender_id
        tender_id = (payload.get("tender_id") or "").strip()
        buyer_contains = (payload.get("buyer_contains") or "").strip().lower()
        item_contains = (payload.get("item_contains") or "").strip().lower()
        seller_contains = (payload.get("seller_contains") or "").strip().lower()
        date_from = (payload.get("date_from") or "").strip()  # YYYY-MM-DD
        date_to = (payload.get("date_to") or "").strip()      # YYYY-MM-DD

        try:
            # conn = _connect(_db_path())
            # cur = conn.cursor()

            bid_end_iso = _normalized_bid_end_date_sql("b")

            where = []
            # params = []
            params = {}

            # Add tender_id filter if provided
            if tender_id:
                where.append("b.bid_number ILIKE :tender_id")
                params["tender_id"] = f"%{tender_id}%"

            if buyer_contains:
                where.append("LOWER(b.organisation) LIKE :buyer")
                # params.append(f"%{buyer_contains}%")
                params["buyer"] = f"%{buyer_contains}%"

            if seller_contains:
                where.append("LOWER(f.seller_name) LIKE :seller")
                # params.append(f"%{seller_contains}%")
                params["seller"] = f"%{seller_contains}%"

            if item_contains:
                where.append("LOWER(f.offered_item) LIKE :item")
                # params.append(f"%{item_contains}%")
                params["item"] = f"%{item_contains}%"

            # if date_from:
            #     where.append(f"({bid_end_iso}) >= :date_from")
            #     # params.append(date_from)
            #     params["date_from"] = date_from

            # if date_to:
            #     where.append(f"({bid_end_iso}) <= :date_to")
            #     # params["date_to"] = date_to
            #     params["date_to"] = date_to

            if date_from:
                where.append("b.bid_end_datetime >= :date_from")
                params["date_from"] = date_from

            if date_to:
                where.append("b.bid_end_datetime < (CAST(:date_to AS DATE) + INTERVAL '1 day')")
                params["date_to"] = date_to


            where_sql = ("WHERE " + " AND ".join(where)) if where else ""

            with engine.connect() as conn:
                
                # KPIs
                kpi_sql = f"""
                SELECT
                COUNT(DISTINCT b.bid_id) AS bids_with_offers,
                COUNT(*) AS total_offers,
                COUNT(DISTINCT b.organisation) AS unique_organisations,
                COUNT(DISTINCT f.seller_name) AS unique_sellers
                FROM {BID_TABLE} b
                JOIN {FIN_TABLE} f ON f.bid_id = b.bid_id
                {where_sql}
                """
                # kpi_row = cur.execute(kpi_sql, params).fetchone()
                # kpis = dict(kpi_row) if kpi_row else {}

                kpi_row = conn.execute(text(kpi_sql), params).mappings().first()
                kpis = dict(kpi_row) if kpi_row else {}

                # Bid Results (Pricing Landscape)
                bids_sql = f"""
                SELECT
                b.bid_number,
                b.organisation,
                b.buyer_location,
                b.bid_open_datetime,
                COUNT(*) AS offer_count,
                STRING_AGG(DISTINCT f.offered_item, ', ') AS offered_items,
                MIN(f.total_price::NUMERIC) AS min_offer,
                AVG(f.total_price::NUMERIC) AS avg_offer,
                MAX(f.total_price::NUMERIC) AS max_offer
                FROM {BID_TABLE} b
                JOIN {FIN_TABLE} f ON f.bid_id = b.bid_id
                {where_sql}
                GROUP BY b.bid_number, b.organisation, b.buyer_location, b.bid_open_datetime
                ORDER BY b.bid_open_datetime DESC
                LIMIT 500
                """
                # bids = [dict(r) for r in cur.execute(bids_sql, params).fetchall()]
                bids = [dict(r) for r in conn.execute(text(bids_sql), params).mappings().all()]

                # Bidder Intelligence (Competitive Positioning)
                bidders_sql = f"""
                SELECT
                f.seller_name AS seller_name,
                COUNT(*) AS total_offers,
                SUM(CASE WHEN f.rank='L1' THEN 1 ELSE 0 END) AS wins_l1,
                SUM(CASE WHEN f.rank='L2' THEN 1 ELSE 0 END) AS l2_count,
                SUM(CASE WHEN f.rank='L1' THEN COALESCE(f.total_price::NUMERIC,0) ELSE 0 END) AS total_won_amount
                FROM {BID_TABLE} b
                JOIN {FIN_TABLE} f ON f.bid_id = b.bid_id
                {where_sql}
                GROUP BY f.seller_name
                ORDER BY wins_l1 DESC, total_offers DESC
                LIMIT 500
                """
                # bidders = [dict(r) for r in cur.execute(bidders_sql, params).fetchall()]
                bidders = [dict(r) for r in conn.execute(text(bidders_sql), params).mappings().all()]

                # conn.close()

                return jsonify({
                    "kpis": kpis,
                    "bids": bids,
                    "bidders": bidders
                })

        except Exception as e:
            app.logger.exception("Pricing Intelligence search failed")
            return jsonify({"error": str(e)}), 500

    # -------- NEW: Chat (NL -> SQL -> run on SQLite) --------
    @app.route("/api/pricing-intelligence/chat", methods=["POST"])
    # @login_required
    def pricing_intelligence_chat():
        payload = request.get_json(silent=True) or {}
        question = (payload.get("question") or "").strip()

        if not question:
            return jsonify({"error": "Please enter a question."}), 400

        # Prefer app.config (TenderGyan style), fallback to env var.
        gemini_key = app.config.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not gemini_key:
            return jsonify({"error": "Gemini API key not configured (GEMINI_API_KEY)."}), 500

        schema_prompt = f"""
Tables:

1) {BID_TABLE} (alias b)
- bid_id (join key)
- bid_number (text; may contain slashes e.g. GEM/2025/B/xxxx)
- organisation (buyer organisation name)
- buyer_location
- bid_open_datetime (text datetime)
- bid_end_datetime (text datetime; mixed formats possible)

2) {FIN_TABLE} (alias f)
- bid_id (join key to {BID_TABLE}.bid_id)
- bid_number (text)
- seller_name
- offered_item
- total_price (numeric)
- rank (text: L1/L2/L3/...)

Common join:
FROM {BID_TABLE} b JOIN {FIN_TABLE} f ON f.bid_id = b.bid_id
"""

        try:
            llm = _gemini_generate_sql(
                api_key=gemini_key,
                question=question,
                schema_prompt=schema_prompt
            )

            sql = (llm.get("sql") or "").strip()
            explanation = (llm.get("explanation") or "").strip()

            if not _is_safe_select_sql(sql):
                return jsonify({
                    "error": "Unsafe or invalid SQL generated. Please rephrase your question.",
                    "sql": sql,
                    "explanation": explanation
                }), 400

            sql = _ensure_limit(sql, default_limit=50)

            # conn = _connect(_db_path())
            # cur = conn.cursor()
            # rows = cur.execute(sql).fetchall()
            # conn.close()
            with engine.connect() as conn:
                result = conn.execute(text(sql))
                rows = result.mappings().all()


            if rows:
                columns = list(rows[0].keys())
                # data_rows = [list(r) for r in rows]
                data_rows = [list(r.values()) for r in rows]
            else:
                columns = []
                data_rows = []

            return jsonify({
                "question": question,
                "sql": sql,
                "explanation": explanation,
                "columns": columns,
                "rows": data_rows
            })

        except Exception as e:
            app.logger.exception("Pricing Intelligence chat failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/pricing-intelligence/bid/<path:bid_number>/offers", methods=["GET"])
    # @login_required
    def pricing_intelligence_bid_offers_api(bid_number):
        """All offers for a bid_number: bid_number, seller_name, total_price, rank"""
        try:
            # conn = _connect(_db_path())
            # cur = conn.cursor()

            sql = f"""
            SELECT
              f.bid_number,
              f.seller_name,
              f.total_price,
              f.rank
            FROM {FIN_TABLE} f
            WHERE f.bid_number = :bid_number
            ORDER BY
              CASE
                WHEN f.rank='L1' THEN 1
                WHEN f.rank='L2' THEN 2
                WHEN f.rank='L3' THEN 3
                ELSE 99
              END,
              COALESCE(f.total_price::NUMERIC, 1e18) ASC
            LIMIT 2000
            """
            # rows = [dict(r) for r in cur.execute(sql, (bid_number,)).fetchall()]
            # conn.close()

            with engine.connect() as conn:
                rows = conn.execute(
                    text(sql),
                    {"bid_number": bid_number}
                ).mappings().all()

            # Convert RowMapping to list of dicts
            offers = [dict(r) for r in rows]

            return jsonify({"bid_number": bid_number, "offers": offers})
        except Exception as e:
            app.logger.exception("Bid offers drilldown failed")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/pricing-intelligence/seller/<path:seller_name>/wins", methods=["GET"])
    # @login_required
    def pricing_intelligence_seller_wins_api(seller_name):
        """All bids where seller is L1 (wins)."""
        try:
            # conn = _connect(_db_path())
            # cur = conn.cursor()

            # Select bids where this seller is L1.
            sql = f"""
            SELECT
              b.bid_number,
              b.organisation,
              b.buyer_location,
              b.bid_open_datetime,
              STRING_AGG(DISTINCT f2.offered_item, ', ') AS offered_items,
              f.total_price AS winning_price
            FROM {BID_TABLE} b
            JOIN {FIN_TABLE} f ON f.bid_id = b.bid_id AND f.rank='L1' AND f.seller_name = :seller_name
            JOIN {FIN_TABLE} f2 ON f2.bid_id = b.bid_id
            GROUP BY b.bid_number, b.organisation, b.buyer_location, b.bid_open_datetime, f.total_price
            ORDER BY b.bid_open_datetime DESC
            LIMIT 2000
            """
            # rows = [dict(r) for r in cur.execute(sql, (seller_name,)).fetchall()]
            # conn.close()

            with engine.connect() as conn:
                rows = conn.execute(
                    text(sql),
                    {"seller_name": seller_name}
                ).mappings().all()

            wins = [dict(r) for r in rows]

            return jsonify({"seller_name": seller_name, "wins": wins})
        except Exception as e:
            app.logger.exception("Seller wins drilldown failed")
            return jsonify({"error": str(e)}), 500