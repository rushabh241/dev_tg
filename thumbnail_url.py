"""
Backfill missing thumbnail_url in news_table by scraping each news_url.

Matches your schema:
- table: news_table
- PK: news_id
- url column: news_url
- thumbnail column: thumbnail_url

Uses your existing DB engine from database_config.py
"""

import os
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from sqlalchemy import text

from database_config import engine  # uses POSTGRES_* already configured in your project


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml",
}

# Optional: limit how many records to process in one run (0/empty = no limit)
LIMIT = int(os.getenv("THUMBNAIL_BACKFILL_LIMIT", "0") or "0")

# Optional: small delay to be polite to websites
SLEEP_SECONDS = float(os.getenv("THUMBNAIL_BACKFILL_SLEEP", "0.2") or "0.2")

# File extensions we NEVER want to scrape for thumbnails
BAD_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".zip", ".rar",
     ".webp", ".svg"
)


def is_valid_news_url(url: str) -> bool:
    """
    Fast sanity checks before making network calls.
    """
    if not url:
        return False

    u = url.strip()
    ul = u.lower()

    # Must start with http/https
    if not ul.startswith(("http://", "https://")):
        return False

    # Skip obvious non-page URLs
    if ul.startswith(("javascript:", "mailto:", "tel:")):
        return False

    # Skip static/binary files
    if any(ul.endswith(ext) for ext in BAD_EXTENSIONS):
        return False

    parsed = urlparse(u)
    if not parsed.netloc:
        return False

    return True


def url_is_reachable(url: str, timeout: int = 5) -> bool:
    """
    Cheap check to see if URL is alive before scraping.
    Uses HEAD to avoid downloading full HTML.
    """
    try:
        r = requests.head(url, headers=HEADERS, timeout=timeout, allow_redirects=True)

        # Some sites reject HEAD; fall back to a lightweight GET in that case.
        if r.status_code in (403, 405):
            r2 = requests.get(
                url,
                headers={**HEADERS, "Range": "bytes=0-2048"},
                timeout=timeout,
                allow_redirects=True,
            )
            return r2.status_code < 400

        return r.status_code < 400
    except requests.RequestException:
        return False


def fetch_thumbnail_from_web(page_url: str, timeout: int = 10) -> Optional[str]:
    """
    Visits page_url and returns a thumbnail candidate.
    Priority:
      1) og:image
      2) twitter:image / twitter:image:src
      3) fallback: first reasonable <img>
    Returns absolute URL or None.
    """
    if not is_valid_news_url(page_url):
        print(f"[skip] invalid url format -> {page_url}")
        return None

    if not url_is_reachable(page_url):
        print(f"[skip] unreachable url -> {page_url}")
        return None

    try:
        r = requests.get(page_url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        og = soup.find("meta", attrs={"property": "og:image"})
        if og and og.get("content"):
            return urljoin(page_url, og["content"].strip())

        tw = soup.find("meta", attrs={"name": "twitter:image"})
        if tw and tw.get("content"):
            return urljoin(page_url, tw["content"].strip())

        tw2 = soup.find("meta", attrs={"name": "twitter:image:src"})
        if tw2 and tw2.get("content"):
            return urljoin(page_url, tw2["content"].strip())

        # Fallback: first non-data image
        for img in soup.find_all("img")[:20]:
            src = (img.get("src") or img.get("data-src") or "").strip()
            if not src or src.startswith("data:"):
                continue
            return urljoin(page_url, src)

        return None

    except requests.RequestException as e:
        print(f"[net] {page_url} -> {e}")
        return None
    except Exception as e:
        print(f"[parse] {page_url} -> {e}")
        return None


def main():
    print("=== Thumbnail backfill starting ===")

    select_sql = """
        SELECT news_id, news_url
        FROM news_table
        WHERE (thumbnail_url IS NULL OR thumbnail_url = '')
          AND (news_url IS NOT NULL AND news_url <> '')
        ORDER BY creation_date DESC
    """

    if LIMIT and LIMIT > 0:
        select_sql += " LIMIT :limit"

    update_sql = """
        UPDATE news_table
        SET thumbnail_url = :thumb
        WHERE news_id = :news_id
    """

    processed = 0
    updated = 0
    skipped = 0

    # tiny cache so duplicate URLs don’t refetch
    thumb_cache = {}

    with engine.connect() as conn:
        rows = conn.execute(text(select_sql), {"limit": LIMIT} if LIMIT else {}).fetchall()
        print(f"Found {len(rows)} rows missing thumbnails.")

        for news_id, news_url in rows:
            url = (news_url or "").strip()

            if not is_valid_news_url(url):
                skipped += 1
                print(f"  ⚠️ skipped malformed url: news_id={news_id} -> {url}")
                continue

            processed += 1

            if url in thumb_cache:
                thumb = thumb_cache[url]
            else:
                print(f"[{processed}/{len(rows)}] Fetching: {url}")
                thumb = fetch_thumbnail_from_web(url)
                thumb_cache[url] = thumb
                time.sleep(SLEEP_SECONDS)

            if thumb:
                conn.execute(text(update_sql), {"thumb": thumb, "news_id": news_id})
                conn.commit()
                updated += 1
                print(f"  ✅ updated news_id={news_id} -> {thumb}")
            else:
                skipped += 1
                print(f"  ⚠️ no thumbnail: news_id={news_id}")

    print("=== Done ===")
    print(f"Processed: {processed}, Updated: {updated}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
