# Quant Paper Digest

A weekly, automated digest of the top 5 **quantitative-finance** papers from
arXiv q-fin. Every paper is explained **twice** — once in plain English assuming
zero background, once with the actual mathematics (rendered with MathJax).

Runs as a scheduled Claude cloud routine every Sunday. Modeled on the sibling
`Paper-digest` routine, re-scoped to quant finance and redesigned for a dual
"math + layperson" report.

## How it works

1. **`paper_fetcher.py`** — pulls a candidate pool (~30–40 papers) from the last
   week across arXiv q-fin categories **MF, PR, CP, TR, ST, RM** (the modeling /
   pricing / trading / risk end; portfolio and general-market categories are
   excluded). Standard-library only, no pip deps.
2. **The routine agent** selects the 5 most substantive papers and writes a
   two-track analysis for each: *The Gist → Plain English → The Math → Jargon
   Decoded → Honest Take → Bottom Line*.
3. **`send_digest.py`** — renders the analyses to a standalone HTML page
   (`digests/digest_YYYYMMDD.html`) with MathJax for the equations, and saves
   the JSON alongside. Requires `markdown` (`pip install markdown`).
4. The routine commits the digest and sends a push + email via ntfy linking to
   the rendered report on `raw.githack.com`.

The exact routine instructions live in [`docs/routine-prompt.md`](docs/routine-prompt.md).

## Local use

```
python3 paper_fetcher.py > pool.json          # fetch the candidate pool
# ...add an "analysis" markdown field to 5 selected papers -> digest_final.json
pip install markdown
python3 send_digest.py digest_final.json --save   # writes digests/digest_YYYYMMDD.html
```

## Scope

arXiv q-fin: `q-fin.MF` (mathematical finance), `q-fin.PR` (pricing of
securities), `q-fin.CP` (computational finance), `q-fin.TR` (trading & market
microstructure), `q-fin.ST` (statistical finance), `q-fin.RM` (risk management).
