#!/usr/bin/env python3
"""Fetch recent quant-finance papers from arXiv q-fin categories.

Outputs a JSON array of candidate paper objects to stdout. The digest agent
picks the top 5 from this pool. Uses only the Python standard library so it
runs in a clean sandbox with no pip install and no third-party deps.
"""
import json
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html import unescape

# The "mathy" end of quant finance: modeling / pricing / trading / computational
# / statistical / risk. Portfolio (q-fin.PM), general finance (q-fin.GN) and
# economics (q-fin.EC) are intentionally excluded per the digest's scope.
CATEGORIES = ["q-fin.MF", "q-fin.PR", "q-fin.CP", "q-fin.TR", "q-fin.ST", "q-fin.RM"]

WINDOW_DAYS = 8      # prefer papers from roughly the last week
MAX_FETCH = 80       # candidate pool size to pull from arXiv
MIN_CANDIDATES = 12  # if the window is too sparse, widen to most-recent-N

API = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"


HEADERS = {
    "User-Agent": "quant-paper-digest/1.0",
    # Some upstreams (and the egress proxy) return 406 Not Acceptable for
    # requests without an explicit Accept header; send one to be safe.
    "Accept": "application/atom+xml,*/*",
}


def _fetch_curl(url):
    """Fetch via the curl CLI. In the sandbox egress proxy, curl reaches
    export.arxiv.org reliably where urllib intermittently gets a spurious
    406 Not Acceptable for the identical request, so curl is preferred."""
    proc = subprocess.run(
        ["curl", "-sS", "--fail", "--max-time", "60",
         "-H", f"User-Agent: {HEADERS['User-Agent']}",
         "-H", f"Accept: {HEADERS['Accept']}",
         url],
        capture_output=True, timeout=90,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"curl exit {proc.returncode}: {err}")
    if not proc.stdout:
        raise RuntimeError("curl returned empty body")
    return proc.stdout


def _fetch_urllib(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def fetch_raw():
    query = "+OR+".join("cat:" + c for c in CATEGORIES)
    url = (f"{API}?search_query={query}"
           f"&start=0&max_results={MAX_FETCH}"
           f"&sortBy=submittedDate&sortOrder=descending")
    # Try curl first (reliable through the proxy), then urllib as a fallback;
    # a few attempts each with backoff to ride out transient 406s / hiccups.
    last_err = None
    for attempt in range(4):
        for name, fetch in (("curl", _fetch_curl), ("urllib", _fetch_urllib)):
            try:
                data = fetch(url)
                if data:
                    return data
            except Exception as e:  # noqa: BLE001 - report and keep trying
                last_err = f"{name}: {e}"
                print(f"attempt {attempt + 1} {name} failed: {e}",
                      file=sys.stderr)
        time.sleep(2 * (attempt + 1))
    raise SystemExit(f"arXiv request failed after retries; last error: {last_err}")


# ---------------------------------------------------------------------------
# Web fallback. arXiv's Fastly edge intermittently returns 406 Not Acceptable
# for the Atom API (export.arxiv.org/api/query) regardless of headers, while
# the public website (arxiv.org/list, arxiv.org/abs) keeps serving HTTP 200.
# When the API is blocked we scrape the same real papers from those pages so
# the digest can still run. This fetches identical arXiv content through a
# working endpoint; it does not invent anything.
# ---------------------------------------------------------------------------
WEB_LISTING = "https://arxiv.org/list/{cat}/recent?skip=0&show={n}"
WEB_ABS = "https://arxiv.org/abs/{arxiv_id}"
WEB_PER_CAT = 25     # ids to pull from each category listing
WEB_MAX_ABS = 40     # cap on /abs page fetches (politeness + runtime)


def _curl_text(url):
    proc = subprocess.run(
        ["curl", "-sS", "--fail", "--max-time", "60",
         "-H", "User-Agent: quant-paper-digest/1.0 (mailto:ely.shao31@gmail.com)",
         url],
        capture_output=True, timeout=90,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"curl exit {proc.returncode}: {err}")
    return proc.stdout.decode("utf-8", "replace")


def _listing_ids(cat):
    """Return arXiv ids from a category's 'recent' listing, newest first."""
    html = _curl_text(WEB_LISTING.format(cat=cat, n=WEB_PER_CAT))
    ids = []
    for m in re.finditer(r'/abs/(\d{4}\.\d{4,5})', html):
        if m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def _meta(html, name):
    m = re.search(
        r'<meta[^>]+name="' + re.escape(name) + r'"[^>]+content="([^"]*)"',
        html)
    return unescape(m.group(1)).strip() if m else ""


def _meta_all(html, name):
    return [unescape(x).strip() for x in re.findall(
        r'<meta[^>]+name="' + re.escape(name) + r'"[^>]+content="([^"]*)"',
        html)]


def _fetch_abs(arxiv_id):
    html = _curl_text(WEB_ABS.format(arxiv_id=arxiv_id))
    title = " ".join(_meta(html, "citation_title").split())

    # citation_author is "Last, First"; flip to "First Last" for readability.
    authors = []
    for a in _meta_all(html, "citation_author"):
        if "," in a:
            last, first = (p.strip() for p in a.split(",", 1))
            a = f"{first} {last}".strip()
        authors.append(a)

    m = re.search(r'<blockquote class="abstract[^"]*">(.*?)</blockquote>',
                  html, re.S)
    abstract = ""
    if m:
        txt = re.sub(r'<[^>]+>', ' ', m.group(1))
        txt = unescape(txt).replace("Abstract:", "", 1)
        abstract = " ".join(txt.split())

    date = _meta(html, "citation_date") or _meta(html, "citation_online_date")
    published = ""
    if date:
        try:
            published = datetime.strptime(
                date, "%Y/%m/%d").replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            published = date

    ps = re.search(r'<span class="primary-subject">([^<(]*)\(([^)]+)\)', html)
    primary = ps.group(2).strip() if ps else ""
    cats = re.findall(r'\(([a-z\-]+\.[A-Z]{2})\)', html)
    cats = list(dict.fromkeys([primary] + cats)) if primary else list(dict.fromkeys(cats))

    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "venue": f"arXiv {primary}" if primary else "arXiv",
        "year": published[:4] if published else (date[:4] if date else ""),
        "citations": None,
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "pdf_url": _meta(html, "citation_pdf_url")
                   or f"https://arxiv.org/pdf/{arxiv_id}",
        "domain": primary,
        "categories": cats,
        "published": published,
    }


def fetch_via_web():
    """Scrape recent q-fin papers from the arXiv website (HTTP 200) when the
    Atom API edge-returns 406. Gathers ids across categories, then fetches
    each /abs page for the full abstract."""
    seen, ordered = set(), []
    for cat in CATEGORIES:
        try:
            for i in _listing_ids(cat):
                if i not in seen:
                    seen.add(i)
                    ordered.append(i)
        except Exception as e:  # noqa: BLE001
            print(f"web listing {cat} failed: {e}", file=sys.stderr)
        time.sleep(0.3)

    papers = []
    for arxiv_id in ordered[:WEB_MAX_ABS]:
        try:
            p = _fetch_abs(arxiv_id)
            if p["title"] and p["abstract"]:
                papers.append(p)
        except Exception as e:  # noqa: BLE001
            print(f"web abs {arxiv_id} failed: {e}", file=sys.stderr)
        time.sleep(0.2)

    # Sort newest-first to mirror the API's sortBy=submittedDate descending.
    papers.sort(key=lambda p: p.get("published", ""), reverse=True)
    print(f"web fallback gathered {len(papers)} papers from "
          f"{len(ordered)} ids", file=sys.stderr)
    return papers


def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    papers = []
    for entry in root.findall(f"{ATOM}entry"):
        def text(tag):
            el = entry.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        title = " ".join(text(f"{ATOM}title").split())
        abstract = " ".join(text(f"{ATOM}summary").split())
        published = text(f"{ATOM}published")
        abs_url = text(f"{ATOM}id")

        authors = []
        for a in entry.findall(f"{ATOM}author"):
            name = a.find(f"{ATOM}name")
            if name is not None and name.text:
                authors.append(name.text.strip())

        pdf_url = ""
        for link in entry.findall(f"{ATOM}link"):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
        if not pdf_url and abs_url:
            pdf_url = abs_url.replace("/abs/", "/pdf/")

        prim = entry.find(f"{ARXIV}primary_category")
        primary = prim.get("term") if prim is not None else ""
        cats = [c.get("term") for c in entry.findall(f"{ATOM}category") if c.get("term")]

        papers.append({
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "venue": f"arXiv {primary}" if primary else "arXiv",
            "year": published[:4] if published else "",
            "citations": None,          # arXiv gives none; brand-new papers have ~0
            "url": abs_url,
            "pdf_url": pdf_url,
            "domain": primary,
            "categories": cats,
            "published": published,
        })
    return papers


def main():
    try:
        papers = parse(fetch_raw())
    except SystemExit as e:
        # The Atom API is unreachable (typically a Fastly-edge 406). Fall back
        # to scraping the arXiv website, which keeps serving HTTP 200.
        print(f"API path failed ({e}); trying web fallback", file=sys.stderr)
        papers = fetch_via_web()
        if not papers:
            raise SystemExit(
                "both the arXiv Atom API and the website fallback failed")
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)

    def pub_dt(p):
        try:
            return datetime.fromisoformat(p["published"].replace("Z", "+00:00"))
        except ValueError:
            return now

    recent = [p for p in papers if pub_dt(p) >= cutoff]
    if len(recent) < MIN_CANDIDATES:
        recent = papers[:max(MIN_CANDIDATES, 30)]

    print(f"fetched {len(papers)} raw, {len(recent)} in candidate pool", file=sys.stderr)
    json.dump(recent, sys.stdout, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
