#!/usr/bin/env python3
"""Fetch recent quant-finance papers from arXiv q-fin categories.

Outputs a JSON array of candidate paper objects to stdout. The digest agent
picks the top 5 from this pool. Uses only the Python standard library so it
runs in a clean sandbox with no pip install and no third-party deps.
"""
import json
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# The "mathy" end of quant finance: modeling / pricing / trading / computational
# / statistical / risk. Portfolio (q-fin.PM), general finance (q-fin.GN) and
# economics (q-fin.EC) are intentionally excluded per the digest's scope.
CATEGORIES = ["q-fin.MF", "q-fin.PR", "q-fin.CP", "q-fin.TR", "q-fin.ST", "q-fin.RM"]

WINDOW_DAYS = 8      # prefer papers from roughly the last week
MAX_FETCH = 80       # candidate pool size to pull from arXiv
MIN_CANDIDATES = 12  # if the window is too sparse, widen to most-recent-N

API = "http://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"


def fetch_raw():
    query = "+OR+".join("cat:" + c for c in CATEGORIES)
    url = (f"{API}?search_query={query}"
           f"&start=0&max_results={MAX_FETCH}"
           f"&sortBy=submittedDate&sortOrder=descending")
    req = urllib.request.Request(url, headers={"User-Agent": "quant-paper-digest/1.0"})
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.URLError as e:
            last_err = e
    raise SystemExit(f"arXiv request failed after 3 attempts: {last_err}")


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
    papers = parse(fetch_raw())
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
