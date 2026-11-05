"""Find public LinkedIn hiring posts (UAE) via DuckDuckGo and save them to posts.json.

Runs on GitHub Actions. A Claude scheduled task reads posts.json,
filters by fit and experience, and emails the matches.
"""
import json
import re
import time
from datetime import datetime, timezone
from html import unescape

import requests

try:
    from ddgs import DDGS
except ImportError:  # older package name
    from duckduckgo_search import DDGS

QUERIES = [
    'site:linkedin.com/posts hiring "business analyst" Dubai CV',
    'site:linkedin.com/posts hiring "data analyst" Dubai CV',
    'site:linkedin.com/posts hiring "BI analyst" OR "power bi" Dubai CV',
    'site:linkedin.com/posts hiring "MIS" Dubai CV',
    'site:linkedin.com/posts hiring "reporting analyst" UAE CV',
    'site:linkedin.com/posts hiring "revenue analyst" OR "commercial analyst" Dubai',
    'site:linkedin.com/posts hiring odoo Dubai CV',
    'site:linkedin.com/posts "business analyst" UAE "send your CV"',
    'site:linkedin.com/posts "data analyst" UAE "share your CV"',
    'site:linkedin.com/posts "we are hiring" analyst Dubai "@"',
]
TIMELIMIT = "w"          # d = past day, w = past week
RESULTS_PER_QUERY = 20
BACKENDS = "duckduckgo,bing,brave,yahoo,mojeek"  # web search engines only
TEXT_LIMIT = 4000
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
POST_URL_RE = re.compile(r"linkedin\.com/(posts|feed/update)/", re.I)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept-Language": "en-US,en;q=0.9"}


def search(queries):
    found, log = {}, []
    ddgs = DDGS()
    for q in queries:
        try:
            res = list(ddgs.text(q, region="us-en", safesearch="off", backend=BACKENDS,
                                 timelimit=TIMELIMIT, max_results=RESULTS_PER_QUERY) or [])
            n = 0
            for r in res:
                url = (r.get("href") or r.get("url") or "").split("?")[0]
                if not POST_URL_RE.search(url):
                    continue
                n += 1
                found.setdefault(url, {"linkedinUrl": url, "search_title": r.get("title"),
                                       "snippet": r.get("body"), "query": q})
            log.append({"query": q, "results": len(res), "posts": n})
        except Exception as e:
            log.append({"query": q, "error": str(e)[:200]})
        time.sleep(4)
    return found, log


def meta(html, prop):
    m = re.search(r'<meta[^>]+(?:property|name)="%s"[^>]+content="([^"]*)"' % re.escape(prop), html)
    return unescape(m.group(1)) if m else None


def enrich(post):
    """Fetch the public post page for full text, author, date and emails."""
    try:
        r = requests.get(post["linkedinUrl"], headers=HEADERS, timeout=20)
        post["page_status"] = r.status_code
        if r.status_code != 200:
            return
        html = r.text
        text = None
        m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        if m:
            try:
                ld = json.loads(m.group(1))
                text = ld.get("articleBody") or ld.get("text")
                post["postedAt"] = ld.get("datePublished")
                author = ld.get("author") or {}
                if isinstance(author, dict):
                    post["author"] = author.get("name")
            except Exception:
                pass
        if not text:
            m = re.search(r'data-test-id="main-feed-activity-card__commentary"[^>]*>(.*?)</p>', html, re.S)
            text = re.sub(r"<[^>]+>", " ", m.group(1)) if m else meta(html, "og:description")
        post["content"] = unescape(text or "")[:TEXT_LIMIT].strip()
        post.setdefault("author", meta(html, "og:title"))
    except Exception as e:
        post["page_error"] = str(e)[:200]


def probe():
    """Check which search engines answer from this machine (for debugging)."""
    out = []
    for b in BACKENDS.split(","):
        for q in ["linkedin.com/posts hiring business analyst dubai",
                  "site:linkedin.com hiring business analyst dubai"]:
            try:
                res = DDGS().text(q, region="us-en", backend=b, max_results=10) or []
                out.append({"backend": b, "query": q, "results": len(res),
                            "linkedin_posts": sum(1 for r in res if POST_URL_RE.search(r.get("href", ""))),
                            "sample": [r.get("href") for r in res[:3]]})
            except Exception as e:
                out.append({"backend": b, "query": q, "error": str(e)[:150]})
            time.sleep(2)
    return out


def main():
    probe_log = probe()
    found, log = search(QUERIES)
    posts = list(found.values())
    for p in posts:
        enrich(p)
        blob = " ".join(filter(None, [p.get("content"), p.get("snippet")]))
        p["emails"] = sorted({e.rstrip(".") for e in EMAIL_RE.findall(blob)
                              if not e.lower().endswith((".png", ".jpg"))})
        time.sleep(2)

    out = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "duckduckgo",
        "timelimit": TIMELIMIT,
        "total": len(posts),
        "with_email": sum(1 for p in posts if p["emails"]),
        "search_log": log,
        "probe": probe_log,
        "posts": posts,
    }
    with open("posts.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"Saved {len(posts)} posts, {out['with_email']} with an email")


if __name__ == "__main__":
    main()
