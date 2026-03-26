# newss.py
# ------------------------------------------------------------
# Tavily → Validate (HTML) → Gemini score → Insert (DB)
# ✅ Changes applied:
# 1) Use Organization.query_builder for Tavily queries
# 2) Remove limit=14 behavior (no CLI --limit, no slicing of final results)
# 3) FIX: Use Candidate ID-based scoring (prevents URL mismatch -> 0 rows)
# 4) Prompt includes reasoning, but we only use relevance_score
# 5) Robust JSON extraction
#
# Exposes functions expected by routes.py:
#   - setup_logger
#   - build_scored_rows_one_org
#   - store_news_rows
# ------------------------------------------------------------

import os
import re
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
from sqlalchemy.dialects.postgresql import insert

from flask import current_app
from google import genai

try:
    from tavily import TavilyClient  # pip install tavily-python
except Exception:
    TavilyClient = None

from models import db, News, Organization, ServiceProductDefinition


# -----------------------------
# Tuning knobs
# -----------------------------
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)

HTTP_TIMEOUT = 12

DEFAULT_MIN_SCORE = 30

TAVILY_MAX_QUERIES = 8
TAVILY_MAX_RESULTS_PER_QUERY = 10
TAVILY_MAX_CANDIDATES_TOTAL = 60

VALIDATION_MAX_FETCH = 50
GEMINI_SCORE_MAX = 35


# -----------------------------
# Allowlist / Blocklist
# -----------------------------
ALLOWED_DOMAINS = {
    "economictimes.indiatimes.com",
    "livemint.com",
    "business-standard.com",
    "thehindubusinessline.com",
    "financialexpress.com",
    "moneycontrol.com",
    "cnbctv18.com",
    "zeebiz.com",
    "indiainfoline.com",
    "businesstoday.in",
    "outlookbusiness.com",
    "fortuneindia.com",
    "thehindu.com",
    "indianexpress.com",
    "hindustantimes.com",
    "timesofindia.indiatimes.com",
    "ibef.org",
    "investindia.gov.in",
    "dpiit.gov.in",
    "mca.gov.in",
    "pib.gov.in",
    "india.gov.in",
    "niti.gov.in",
    "eaindustry.nic.in",
    "commerce.gov.in",
    "powerline.net.in",
    "energy.economictimes.indiatimes.com",
    "psuwatch.com",
    "projectsmonitor.com",
    "economist.com",
}

BLOCKED_DOMAINS = {
    "facebook.com", "instagram.com", "linkedin.com", "pinterest.com", "reddit.com", "quora.com"
}

BLOCKED_URL_PREFIXES = (
    "https://www.pib.gov.in/PressReleasePage.aspx",
    "https://pib.gov.in/PressReleasePage.aspx",
    "http://www.pib.gov.in/PressReleasePage.aspx",
    "http://pib.gov.in/PressReleasePage.aspx",
    "https://www.pib.gov.in/PressReleaseIframePage.aspx",
    "https://pib.gov.in/PressReleaseIframePage.aspx",
    "http://www.pib.gov.in/PressReleaseIframePage.aspx",
    "http://pib.gov.in/PressReleaseIframePage.aspx",
)


# -----------------------------
# Logger
# -----------------------------
def setup_logger(log_path: str = "logs/news_services.log") -> logging.Logger:
    Path(os.path.dirname(log_path) or ".").mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("news_services")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# -----------------------------
# Config helpers
# -----------------------------
def _get_tavily_api_key() -> str:
    k = (current_app.config.get("TAVILY_API_KEY") or "").strip()
    if not k:
        raise RuntimeError("TAVILY_API_KEY missing in current_app.config")
    return k


def _get_gemini_api_key() -> str:
    k = (current_app.config.get("GEMINI_API_KEY") or "").strip()
    if not k:
        raise RuntimeError("GEMINI_API_KEY missing in current_app.config")
    return k


def _cfg_int(name: str, default: int) -> int:
    v = current_app.config.get(name, None)
    try:
        return int(v)
    except Exception:
        return default


# -----------------------------
# URL utilities
# -----------------------------
def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def _is_blocked_url(url: str) -> bool:
    u = (url or "").strip()
    return any(u.startswith(p) for p in BLOCKED_URL_PREFIXES)


def _is_allowed_domain(url: str) -> bool:
    d = _domain(url)
    if not d:
        return False
    if d in BLOCKED_DOMAINS:
        return False
    return d in ALLOWED_DOMAINS


def _looks_non_article_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return True
    if p.scheme not in ("http", "https"):
        return True
    path = (p.path or "").lower()
    if path in ("", "/"):
        return True
    bad = ["/search", "/tag/", "/topic/", "/topics/", "/category/", "/section/", "/author/", "/archive"]
    if any(b in path for b in bad):
        return True
    return False


def _looks_like_article_html_relaxed(soup: BeautifulSoup, html_text: str) -> bool:
    """
    Accept if ANY 2 signals are present:
      - <article> tag exists
      - og:type == article
      - article:published_time exists
      - has <h1>
      - 3+ <p> tags
      - enough visible text length (>= 1200 chars)
    """
    signals = 0

    if soup.find("article"):
        signals += 1

    og_type = soup.find("meta", property="og:type")
    if og_type and (og_type.get("content") or "").strip().lower() == "article":
        signals += 1

    pub = soup.find("meta", property="article:published_time") or soup.find("meta", attrs={"name": "pubdate"})
    if pub and (pub.get("content") or "").strip():
        signals += 1

    if soup.find("h1"):
        signals += 1

    if len(soup.find_all("p")) >= 3:
        signals += 1

    text = soup.get_text(" ", strip=True) if soup else ""
    if len(text) >= 1200:
        signals += 1

    return signals >= 2


# -----------------------------
# DB context helpers
# -----------------------------
def get_org_context(org_id: int) -> Tuple[str, str]:
    org = db.session.query(Organization).filter(Organization.id == org_id).first()
    company_url = (getattr(org, "company_url", "") if org else "") or ""

    q = db.session.query(ServiceProductDefinition).filter(ServiceProductDefinition.organization_id == org_id)
    if hasattr(ServiceProductDefinition, "updated_at"):
        q = q.order_by(ServiceProductDefinition.updated_at.desc())
    if hasattr(ServiceProductDefinition, "created_at"):
        q = q.order_by(ServiceProductDefinition.created_at.desc())
    spd = q.first()
    spd_text = (getattr(spd, "definition", "") if spd else "") or ""
    return spd_text.strip(), company_url.strip()


def get_org_query_builder(org_id: int):
    org = db.session.query(Organization).filter(Organization.id == org_id).first()
    return getattr(org, "query_builder", None) if org else None


def _parse_query_builder(raw) -> List[str]:
    if raw is None:
        return []

    if isinstance(raw, (list, tuple, set)):
        parts = list(raw)

    elif isinstance(raw, dict):
        parts = raw.get("queries") or raw.get("q") or []
        if not isinstance(parts, (list, tuple, set)):
            parts = [str(parts)]

    else:
        s = str(raw).strip()
        if not s:
            return []

        if (s.startswith("[") and s.endswith("]")) or (s.startswith('{"') and s.endswith("}")):
            try:
                parsed = json.loads(s)
                return _parse_query_builder(parsed)[:TAVILY_MAX_QUERIES]
            except Exception:
                pass

        parts = s.split(";") if ";" in s else s.splitlines()

    queries: List[str] = []
    seen = set()
    for p in parts:
        q = re.sub(r"\s+", " ", str(p).strip())
        if not q:
            continue
        if q in seen:
            continue
        seen.add(q)
        queries.append(q)

    return queries[:TAVILY_MAX_QUERIES]


# -----------------------------
# SPD query builder (fallback only)
# -----------------------------
_STOPWORDS = {
    "we", "our", "and", "or", "the", "a", "an", "to", "of", "in", "for", "with", "on",
    "is", "are", "was", "were", "be", "been", "being", "provide", "provides", "providing",
    "manufacture", "manufactures", "manufacturing", "service", "services",
    "all", "any", "sizes", "types", "also", "like", "etc", "include", "including",
    "do", "does", "not", "don't", "dont", "cannot", "no"
}

_KEEP_SHORT = {"epc", "psu", "l1", "r&d", "rd", "stp", "wtp", "lng", "cgd", "oem", "emi"}


def _clean_tokens(text: str) -> List[str]:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9&\s,-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    toks = re.findall(r"[a-z0-9&]{2,}", text)
    out = []
    for t in toks:
        if t in _STOPWORDS:
            continue
        if len(t) < 3 and t not in _KEEP_SHORT:
            continue
        out.append(t)
    return out


def _extract_negative_terms(spd_text: str) -> List[str]:
    t = (spd_text or "").lower()
    negatives: List[str] = []

    patterns = [
        r"(?:we\s+don['’]?t|do\s+not|does\s+not|not)\s+(?:manufacture|make|provide|offer|sell)\s+([^.\n;]+)",
        r"(?:we\s+do\s+not|we\s+don['’]?t)\s+([^.\n;]+)",
    ]

    for pat in patterns:
        for m in re.finditer(pat, t, flags=re.IGNORECASE):
            chunk = m.group(1) if m.groups() else ""
            toks = _clean_tokens(chunk)
            negatives.extend(toks)

    uniq = []
    seen = set()
    for x in negatives:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq[:10]


def _extract_positive_terms(spd_text: str) -> List[str]:
    text = (spd_text or "")
    low = text.lower()

    toks = _clean_tokens(low)

    focus_chunks = []
    for verb in ["manufacture", "manufactures", "provide", "provides", "supply", "supplies", "install", "installation", "service", "services"]:
        for m in re.finditer(rf"{verb}\s+([^.\n;]+)", low):
            focus_chunks.append(m.group(1))

    focus_toks = []
    for ch in focus_chunks:
        focus_toks.extend(_clean_tokens(ch))

    from collections import Counter
    c = Counter(toks + focus_toks)

    blacklist = {"system", "solutions", "equipment", "machine", "machines", "service", "services"}
    ranked = [w for w, _ in c.most_common() if w not in blacklist]

    out = []
    seen = set()
    for w in ranked:
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= 10:
            break
    return out


def _build_queries(spd_text: str, company_url: str, max_queries: int = None) -> List[str]:
    max_queries = int(max_queries or TAVILY_MAX_QUERIES)

    pos = _extract_positive_terms(spd_text)
    neg = _extract_negative_terms(spd_text)

    core = " ".join(pos[:6]) if pos else "industry procurement"
    neg_part = ""
    if neg:
        neg_part = " " + " ".join([f"-{x}" for x in neg[:4]])

    domain_hint = _domain(company_url) if company_url else ""

    intents = [
        "tender procurement EPC contract",
        "capex project investment expansion",
        "policy regulation compliance",
        "supply chain vendor sourcing",
        "contract award L1 bidder",
        "PSU government project tender",
        "import export tariff duty",
        "pricing raw material cost disruption",
    ]

    queries = []
    for intent in intents:
        q = f"India {core} {intent} news{neg_part}"
        q = re.sub(r"\s+", " ", q).strip()
        if q not in queries:
            queries.append(q)
        if len(queries) >= max_queries:
            break

    if domain_hint and len(queries) < max_queries:
        q = f"{domain_hint} India business expansion investment news"
        q = re.sub(r"\s+", " ", q).strip()
        if q not in queries:
            queries.append(q)

    return queries[:max_queries]


# -----------------------------
# Tavily fetch
# -----------------------------
def _tavily_fetch_candidates(
    spd_text: str,
    company_url: str,
    org_queries: List[str],
    logger: logging.Logger
) -> List[Dict[str, Any]]:
    if TavilyClient is None:
        raise RuntimeError("tavily-python not installed. Add `tavily-python` to requirements.txt")

    client = TavilyClient(api_key=_get_tavily_api_key())

    queries = (org_queries or [])[:TAVILY_MAX_QUERIES]
    if not queries:
        queries = _build_queries(spd_text, company_url, max_queries=TAVILY_MAX_QUERIES)

    logger.info(f"[TAVILY] queries={queries}")

    candidates: List[Dict[str, Any]] = []
    seen = set()

    for q in queries:
        try:
            resp = client.search(
                query=q,
                topic="news",
                search_depth="advanced",
                max_results=TAVILY_MAX_RESULTS_PER_QUERY,
                include_answer=False,
                include_raw_content=True,
                include_domains=sorted(ALLOWED_DOMAINS),
                exclude_domains=list(BLOCKED_DOMAINS),
            )
            results = resp.get("results", []) or []
        except Exception as e:
            logger.info(f"[TAVILY] failed q={q!r} err={e}")
            results = []

        for r in results:
            url = (r.get("url") or "").strip()
            title = (r.get("title") or "").strip()
            snippet = (r.get("content") or "").strip()

            if not url or url in seen:
                continue
            if _is_blocked_url(url):
                continue
            if not _is_allowed_domain(url):
                continue
            if _looks_non_article_url(url):
                continue

            seen.add(url)
            candidates.append({"url": url, "title": title[:180], "snippet": snippet[:300], "source": _domain(url)})

            if len(candidates) >= TAVILY_MAX_CANDIDATES_TOTAL:
                break

        if len(candidates) >= TAVILY_MAX_CANDIDATES_TOTAL:
            break

    logger.info(f"[TAVILY] candidates={len(candidates)}")
    return candidates


# -----------------------------
# Validate + canonicalize + thumbnail
# -----------------------------
def _validate_and_extract(url: str, session: requests.Session) -> Optional[Dict[str, Any]]:
    if not url:
        return None
    if _is_blocked_url(url):
        return None
    if not _is_allowed_domain(url):
        return None
    if _looks_non_article_url(url):
        return None

    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
        "Connection": "keep-alive",
    }

    try:
        r = session.get(url, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
    except Exception:
        return None

    if r.status_code != 200:
        return None

    ctype = (r.headers.get("Content-Type") or "").lower()
    if "text/html" not in ctype and "application/xhtml" not in ctype:
        return None

    final_url = (r.url or "").strip()
    if not final_url:
        return None
    if _is_blocked_url(final_url):
        return None
    if not _is_allowed_domain(final_url):
        return None
    if _looks_non_article_url(final_url):
        return None

    html = r.text or ""
    if len(html.strip()) < 800:
        return None

    soup = BeautifulSoup(html, "html.parser")

    if not _looks_like_article_html_relaxed(soup, html_text=html):
        return None

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    title = re.sub(r"\s+", " ", title).strip()[:180] if title else ""

    thumb = None
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        thumb = urljoin(final_url, og.get("content").strip())
    if not thumb:
        tw = soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", property="twitter:image")
        if tw and tw.get("content"):
            thumb = urljoin(final_url, tw.get("content").strip())

    return {"url": final_url, "html_title": title, "thumbnail_url": thumb}


# -----------------------------
# Gemini scoring (ID-based)
# -----------------------------
def _build_score_prompt(spd_text: str, candidates: List[Dict[str, Any]], min_score: int) -> str:
    lines = []
    for i, c in enumerate(candidates, 1):
        lines.append(
            f"Candidate {i}:\n"
            f"  ID: {i}\n"
            f"  URL: {c['url']}\n"
            f"  Title: {c.get('title', '')}\n"
            f"  Snippet: {c.get('snippet', '')}\n"
            f"  Source: {c.get('source', '')}\n"
        )
    blob = "\n".join(lines)[:90000]

    return f"""
You are an Industry & Procurement Intelligence Analyst for a B2B platform. 
Your objective is to score the relevance of candidate news articles to a specific manufacturing organization.

Organization Profile & Core Products:
{spd_text}

Candidate News (Evaluate ONLY these candidates):
{blob}

CRITICAL SCORING RULES & RUBRIC (0-100):
You are NOT a simple keyword scanner. DO NOT look for exact product mentions. 
Industrial valves are universally required in all process manufacturing, fluid control, and energy infrastructure. 

Therefore, you must apply this MANDATORY OVERRIDE RULE:
If the candidate discusses a NEW PIPELINE, REFINERY EXPANSION, POWER PLANT, WATER TREATMENT FACILITY, CHEMICAL PARK, or MAJOR EPC CONTRACT in India, you MUST score it 85 or higher, even if the word "valve" is never mentioned in the text.

- [80-100] High Relevance: Infrastructure capex, new plant announcements, government/PSU investment plans, or major EPC awards in the Oil, Gas, Petrochemical, Power, or Water sectors.
- [50-79] Medium Relevance: Broad supply chain news, steel raw material pricing, or general industry regulatory shifts.
- [0-49] Low Relevance / Noise (Fail): Generic consumer news, totally unrelated industries, or generic financial stock market updates.
  - Generic consumer/lifestyle news.
  - Totally unrelated industries (e.g., consumer software, retail, Bollywood).
  - General financial/stock market updates without operational or capex impact.
  - Products the organization explicitly states they DO NOT manufacture.

INSTRUCTIONS:
For each candidate, you MUST first write a 1-2 sentence `reasoning` and then provide the `relevance_score`.

OUTPUT RULES:
- Return ONLY valid JSON.
- No markdown, no backticks, no extra text.

Return strictly in the following JSON format:
{{
  "scores": [
    {{
      "id": <integer>,
      "url": "exact candidate url",
      "reasoning": "brief explanation",
      "relevance_score": <integer>
    }}
  ]
}}
""".strip()

def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object start '{' found in Gemini response")

    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                chunk = text[start:i + 1]
                return json.loads(chunk)

    raise ValueError("No complete JSON object found in Gemini response")


def _gemini_score(spd_text: str, candidates: List[Dict[str, Any]], model_name: str, min_score: int) -> Dict[int, int]:
    client = genai.Client(api_key=_get_gemini_api_key())
    prompt = _build_score_prompt(spd_text, candidates, min_score=min_score)

    resp = client.models.generate_content(model=model_name, contents=prompt)
    text = getattr(resp, "text", None) or str(resp)

    data = _extract_json(text)
    out: Dict[int, int] = {}

    for row in (data.get("scores") or []):
        try:
            i = int(row.get("id"))
            s = int(row.get("relevance_score") or 0)
            reason = row.get("reasoning", "No reason provided")
            
            # ✅ ADD THIS LINE:
            print(f"--> [Gemini] ID: {i} | Score: {s} | Reason: {reason}")
            
            out[i] = max(0, min(100, s))
        except Exception:
            continue

    return out


# ============================================================
# ✅ PUBLIC FUNCTIONS YOUR routes.py EXPECTS
# ============================================================
def build_scored_rows_one_org(
    org_id: int,
    #limit: int,  # kept for compatibility with existing calls; ignored
    model_name: str,
    logger: Optional[logging.Logger] = None,
) -> List[Dict[str, Any]]:
    logger = logger or setup_logger()
    logger.info(f"[ORG {org_id}] starting build_scored_rows_one_org()")

    spd_text, company_url = get_org_context(org_id)
    if not spd_text:
        logger.info(f"[ORG {org_id}] No SPD. Skipping.")
        return []

    min_score = _cfg_int("NEWS_MIN_RELEVANCE_SCORE", DEFAULT_MIN_SCORE)

    raw_qb = get_org_query_builder(org_id)
    org_queries = _parse_query_builder(raw_qb)

    logger.info(f"[ORG {org_id}] using min_score={min_score}")
    logger.info(f"[ORG {org_id}] query_builder_queries={len(org_queries)}")

    candidates = _tavily_fetch_candidates(
        spd_text=spd_text,
        company_url=company_url,
        org_queries=org_queries,
        logger=logger,
    )
    logger.info(f"[ORG {org_id}] Tavily candidates={len(candidates)}")
    if not candidates:
        return []

    session = requests.Session()
    validated: List[Dict[str, Any]] = []
    seen = set()

    for c in candidates:
        if len(validated) >= VALIDATION_MAX_FETCH:
            break

        raw_url = c["url"]
        v = _validate_and_extract(raw_url, session=session)
        if not v:
            continue

        final_url = v["url"]
        if final_url in seen:
            continue
        seen.add(final_url)

        title = (c.get("title") or "").strip()
        if not title or len(title) < 8:
            title = (v.get("html_title") or "").strip()

        title = re.sub(r"\s+", " ", (title or "")).strip()[:180]
        if not title or len(title) < 8:
            continue

        validated.append(
            {
                "url": final_url,
                "title": title,
                "snippet": (c.get("snippet") or "").strip()[:300],
                "source": (c.get("source") or "").strip()[:80],
                "thumbnail_url": v.get("thumbnail_url"),
            }
        )

    logger.info(f"[ORG {org_id}] validated={len(validated)} (max_fetch={VALIDATION_MAX_FETCH})")
    if not validated:
        logger.info(f"[ORG {org_id}] No validated articles.")
        return []

    to_score = validated[:GEMINI_SCORE_MAX]
    logger.info(f"[ORG {org_id}] sending_to_gemini={len(to_score)} model={model_name} min_score={min_score}")

    scores_by_id = _gemini_score(
        spd_text=spd_text,
        candidates=to_score,
        model_name=model_name,
        min_score=min_score,
    )
    logger.info(f"[ORG {org_id}] gemini_scores_received={len(scores_by_id)}")

    rows: List[Dict[str, Any]] = []
    for idx, it in enumerate(to_score, start=1):
        score = scores_by_id.get(idx, 0)
        if score < min_score:
            continue
        rows.append(
            {
                "news_title": it["title"],
                "news_url": it["url"],
                "relevance_score": int(score),
                "thumbnail_url": it.get("thumbnail_url"),
                "organization_id": org_id,
            }
        )

    rows.sort(key=lambda x: int(x.get("relevance_score") or 0), reverse=True)
    logger.info(f"[ORG {org_id}] final_rows_after_filter={len(rows)}")
    return rows


def store_news_rows(
    rows: List[Dict[str, Any]],
    organization_id: int,
    logger: Optional[logging.Logger] = None,
) -> Tuple[int, int, Dict[str, int]]:
    logger = logger or setup_logger()

    inserted = 0
    skipped = 0
    reasons: Dict[str, int] = {}

    if not rows:
        return 0, 0, {"no_rows": 1}

    seen = set()
    cleaned = []
    for r in rows:
        title = (r.get("news_title") or "").strip()
        url = (r.get("news_url") or "").strip()

        if not title or not url:
            skipped += 1
            reasons["missing_title_or_url"] = reasons.get("missing_title_or_url", 0) + 1
            continue
        if _is_blocked_url(url) or (not _is_allowed_domain(url)):
            skipped += 1
            reasons["blocked_or_not_allowed"] = reasons.get("blocked_or_not_allowed", 0) + 1
            continue
        if url in seen:
            skipped += 1
            reasons["duplicate_in_batch"] = reasons.get("duplicate_in_batch", 0) + 1
            continue

        seen.add(url)
        cleaned.append(r)

    if not cleaned:
        return 0, skipped, reasons

    urls = [x["news_url"] for x in cleaned]
    existing = (
        db.session.query(News.news_url)
        .filter(News.organization_id == organization_id)
        .filter(News.news_url.in_(urls))
        .all()
    )
    existing_urls = {e[0] for e in existing if e and e[0]}

    insert_rows = []
    for x in cleaned:
        url = x["news_url"]
        if url in existing_urls:
            skipped += 1
            reasons["already_exists_db"] = reasons.get("already_exists_db", 0) + 1
            continue

        insert_rows.append(
            {
                "news_title": x["news_title"],
                "news_url": url,
                "creation_date": datetime.utcnow(),
                "relevance_score": int(x.get("relevance_score") or 0),
                "thumbnail_url": x.get("thumbnail_url"),
                "organization_id": organization_id,
            }
        )

    if not insert_rows:
        return 0, skipped, reasons

    stmt = insert(News).values(insert_rows).on_conflict_do_nothing(
        index_elements=["organization_id", "news_url"]
    )
    result = db.session.execute(stmt)
    db.session.commit()

    inserted = int(getattr(result, "rowcount", 0) or 0)
    conflict = max(0, len(insert_rows) - inserted)
    if conflict:
        skipped += conflict
        reasons["insert_conflict"] = reasons.get("insert_conflict", 0) + conflict

    logger.info(f"[ORG {organization_id}] INSERTED={inserted} SKIPPED={skipped} reasons={reasons}")
    return inserted, skipped, reasons


# ============================================================
# CLI ENTRYPOINT (run directly)
# ============================================================
if __name__ == "__main__":
    import argparse
    from app import app
    import config

    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=int, help="Organization ID")
    parser.add_argument("--model", type=str, default=getattr(config, "NEWS_GEMINI_MODEL", "gemini-2.5-pro"))
    parser.add_argument("--all", action="store_true", help="Run for all orgs")
    args = parser.parse_args()

    logger = setup_logger()

    with app.app_context():
        if args.all:
            org_ids = [o.id for o in Organization.query.order_by(Organization.id.asc()).all()]
            print(f"Running for {len(org_ids)} org(s)...")

            total_inserted = 0
            total_skipped = 0

            for oid in org_ids:
                print(f"\nRunning for ORG {oid}...")

                rows = build_scored_rows_one_org(
                    org_id=oid,
                    model_name=args.model,
                    logger=logger,
                )
                print(f"ROWS: {len(rows)}")

                inserted, skipped, reasons = store_news_rows(
                    rows=rows,
                    organization_id=oid,
                    logger=logger,
                )
                total_inserted += inserted
                total_skipped += skipped
                print(f"ORG {oid} -> INSERTED {inserted}, SKIPPED {skipped}, REASONS {reasons}")

            print(f"\nDONE ✅ Total INSERTED={total_inserted} Total SKIPPED={total_skipped}")

        elif args.org:
            rows = build_scored_rows_one_org(
                org_id=args.org,
                model_name=args.model,
                logger=logger,
            )
            print(f"ROWS: {len(rows)}")

            inserted, skipped, reasons = store_news_rows(
                rows=rows,
                organization_id=args.org,
                logger=logger,
            )
            print(f"INSERTED: {inserted}")
            print(f"SKIPPED: {skipped}")
            print(f"REASONS: {reasons}")

        else:
            print("❌ Please provide either --org <org_id> OR --all")
