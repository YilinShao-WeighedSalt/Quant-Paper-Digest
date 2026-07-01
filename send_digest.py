#!/usr/bin/env python3
"""Render the quant-finance paper digest to a standalone HTML page.

Usage:
    python3 send_digest.py <digest_final.json> [--save]

<digest_final.json> is the fetcher output with an added "analysis" field
(markdown, containing a "Plain English" part and a "The Math" part) on each
paper. With --save the HTML + JSON are written to digests/digest_YYYYMMDD.html
and digests/digest_YYYYMMDD.json, and the saved paths + date are printed so the
caller can reuse the exact date string. Without --save the HTML goes to stdout.

Math ($...$, $$...$$, \\(...\\), \\[...\\]) is protected from the markdown pass
and rendered client-side by MathJax.
"""
import html
import json
import os
import re
import sys
from datetime import datetime

try:
    import markdown as _md
except ImportError:
    sys.exit("missing dependency: run `pip install markdown` before send_digest.py")

# Display math first (so its inner `$` never trips the inline pattern), then inline.
MATH_PATTERNS = [
    re.compile(r"\$\$.*?\$\$", re.DOTALL),
    re.compile(r"\\\[.*?\\\]", re.DOTALL),
    re.compile(r"\\\(.*?\\\)", re.DOTALL),
    re.compile(r"\$(?:\\.|[^$\\\n])+\$"),   # inline $...$ on a single line
]


def render_markdown(text):
    """Markdown -> HTML, preserving LaTeX math spans verbatim for MathJax."""
    store = []

    def stash(m):
        store.append(m.group(0))
        return f"MJXMATHTOKEN{len(store) - 1}END"

    for pat in MATH_PATTERNS:
        text = pat.sub(stash, text)

    rendered = _md.markdown(text, extensions=["extra", "sane_lists"])
    return re.sub(r"MJXMATHTOKEN(\d+)END", lambda m: store[int(m.group(1))], rendered)


def paper_block(i, p):
    authors_list = p.get("authors", []) or []
    authors = ", ".join(authors_list[:6]) + (" et al." if len(authors_list) > 6 else "")
    cat = p.get("domain") or p.get("venue", "")
    links = []
    if p.get("url"):
        links.append(f'<a href="{html.escape(p["url"])}">abstract</a>')
    if p.get("pdf_url"):
        links.append(f'<a href="{html.escape(p["pdf_url"])}">pdf</a>')
    links_html = " &middot; ".join(links)
    analysis_html = render_markdown(p.get("analysis") or "*No analysis provided.*")
    return f"""
<section class="paper">
  <h2><span class="num">{i}.</span> {html.escape(p.get("title", ""))}</h2>
  <p class="meta">{html.escape(authors)}<br>
    <span class="cat">{html.escape(cat)}</span> &middot; {html.escape(p.get("published", "")[:10])} &middot; {links_html}</p>
  <div class="analysis">{analysis_html}</div>
</section>"""


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Quant Paper Digest — {human_date}</title>
<script>
window.MathJax = {{
  tex: {{ inlineMath: [['$','$'], ['\\\\(','\\\\)']], displayMath: [['$$','$$'], ['\\\\[','\\\\]']] }},
  svg: {{ fontCache: 'global' }}
}};
</script>
<script async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
<style>
  :root {{ --ink:#1a1a2e; --muted:#6b7280; --rule:#e5e7eb; --accent:#3b3b8f; --mathbg:#f6f7fb; }}
  body {{ font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
         color:var(--ink); max-width:780px; margin:0 auto; padding:32px 20px 80px;
         line-height:1.62; font-size:17px; }}
  header {{ border-bottom:3px solid var(--accent); padding-bottom:14px; margin-bottom:8px; }}
  header h1 {{ font-size:26px; margin:0 0 4px; letter-spacing:-.2px; }}
  header .sub {{ color:var(--muted); font-size:14px; }}
  .intro {{ color:var(--muted); font-size:15px; margin:14px 0 28px; }}
  section.paper {{ padding:26px 0; border-bottom:1px solid var(--rule); }}
  section.paper h2 {{ font-size:20px; line-height:1.35; margin:0 0 6px; }}
  .num {{ color:var(--accent); font-weight:700; }}
  .meta {{ color:var(--muted); font-size:13.5px; margin:0 0 14px; }}
  .meta .cat {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px;
               background:#eef0f7; color:var(--accent); padding:1px 6px; border-radius:4px; }}
  .meta a {{ color:var(--accent); text-decoration:none; }}
  .analysis h3 {{ font-size:15px; text-transform:uppercase; letter-spacing:.06em;
                 color:var(--accent); margin:22px 0 6px; }}
  .analysis h4 {{ font-size:16px; margin:18px 0 4px; }}
  .analysis table {{ border-collapse:collapse; width:100%; margin:12px 0; font-size:14.5px; }}
  .analysis th, .analysis td {{ border:1px solid var(--rule); padding:6px 10px; text-align:left; }}
  .analysis th {{ background:var(--mathbg); }}
  .analysis code {{ background:var(--mathbg); padding:1px 5px; border-radius:4px;
                   font-size:14px; }}
  .analysis pre {{ background:var(--mathbg); padding:12px; border-radius:6px; overflow-x:auto; }}
  mjx-container[display="true"] {{ background:var(--mathbg); padding:8px 4px; border-radius:6px;
                                   overflow-x:auto; }}
  footer {{ color:var(--muted); font-size:13px; margin-top:36px; text-align:center; }}
  footer a {{ color:var(--accent); }}
</style>
</head>
<body>
<header>
  <h1>Quant Paper Digest</h1>
  <div class="sub">{human_date} &middot; {count} papers from arXiv q-fin</div>
</header>
<p class="intro">The week's most substantive quantitative-finance research — the
modeling, pricing, trading and risk end. Each paper is explained twice: once in
plain English assuming zero background, once with the actual mathematics.</p>
{blocks}
<footer>
  Generated automatically from arXiv q-fin (MF · PR · CP · TR · ST · RM).
  Equations rendered with MathJax. Every claim is the author's; read the linked papers to verify.
</footer>
</body>
</html>
"""


def build_html(papers, human_date):
    blocks = "\n".join(paper_block(i + 1, p) for i, p in enumerate(papers))
    return PAGE.format(human_date=human_date, count=len(papers), blocks=blocks)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    save = "--save" in sys.argv
    if not args:
        sys.exit("usage: python3 send_digest.py <digest_final.json> [--save]")

    with open(args[0]) as f:
        papers = json.load(f)

    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    human_date = now.strftime("%B %d, %Y")
    page = build_html(papers, human_date)

    if save:
        os.makedirs("digests", exist_ok=True)
        html_path = f"digests/digest_{date_str}.html"
        json_path = f"digests/digest_{date_str}.json"
        with open(html_path, "w") as f:
            f.write(page)
        with open(json_path, "w") as f:
            json.dump(papers, f, indent=2, ensure_ascii=False)
        print(f"SAVED_HTML: {html_path}")
        print(f"SAVED_JSON: {json_path}")
        print(f"DATE: {date_str}")
    else:
        sys.stdout.write(page)


if __name__ == "__main__":
    main()
