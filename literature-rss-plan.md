# Literature RSS Pipeline — Design Notes

**Status**: Planned. Email parsers for arXiv/journals nuked 2026-03-09. Read this before building.

## Why RSS over email

- arXiv and journal email digests are fragile: HTML changes break parsers (JFM Cambridge took 143KB + 3 parsing attempts to crack). Click-tracked URLs, newsletter formatting cruft, inconsistent structure.
- RSS feeds are designed for machine consumption — structured, stable, DOI/link in first-class fields.
- arXiv RSS/API is the canonical data source, not the email digest (which is derived from the same API anyway).

## What was nuked

- `workspace-email/scripts/parse_arxiv_digest.py`
- `workspace-email/scripts/parse_journal_newsletters.py`
- arXiv/bioRxiv/journal senders removed from `email-prefetch.sh` literature query
- Those parser calls removed from prefetch.sh
- `arxivPapers` + `journalPapers` removed from prefetch manifest

**Still alive (email-based)**:
- `parse_google_scholar_digest.py` — Scholar has no RSS alternative
- Funding pipeline — no RSS equivalent for Carlton Baugh / UKRI / Leverhulme / ResearchConnect

## Proposed architecture

```
Non-AI launchd job: ai.comphy.literature-rss-fetch
  Runs at :10 of 00/06/12/18 (after email-prefetch at :05)
  Writes: workspace-email/staging/rss-papers-latest.json
```

The literature-collect skill reads `rss-papers-latest.json` as a third staged source alongside `google-scholar-papers-latest.json`. Same sanitization pipeline applies.

## arXiv feeds

arXiv has two options:

**Option A — RSS feeds (simplest)**
- `https://rss.arxiv.org/rss/physics.flu-dyn` — fluid dynamics
- `https://rss.arxiv.org/rss/cond-mat.soft` — soft matter / condensed matter
- `https://rss.arxiv.org/rss/physics.bio-ph` — biological physics (optional)
- Returns last ~100 papers per feed, updated daily.
- Parseable with `feedparser` Python library.

**Option B — arXiv API (more powerful)**
- `https://export.arxiv.org/api/query?search_query=cat:physics.flu-dyn&sortBy=submittedDate&sortOrder=descending&max_results=50`
- Structured Atom XML. Full abstracts, all metadata, author affiliations.
- Can query cross-listed categories, keyword combinations.
- Rate limit: 3 req/sec, 1 req/sec suggested for bulk. Not a concern at 6h cadence.

**Recommendation**: arXiv API. More metadata, keyword search support for future relevance pre-filtering.

## Journal feeds

Most major journals have RSS. Relevant ones for CoMPhy:

| Journal | RSS URL |
|---|---|
| JFM (Cambridge) | `https://www.cambridge.org/core/journals/journal-of-fluid-mechanics/rss` |
| Physical Review Letters | `https://feeds.aps.org/rss/recent/prl.xml` |
| Physical Review Fluids | `https://feeds.aps.org/rss/recent/prfluids.xml` |
| Physical Review E | `https://feeds.aps.org/rss/recent/pre.xml` |
| Soft Matter (RSC) | `https://feeds.rsc.org/rss/sm` |
| Nature Physics | `https://www.nature.com/nphys.rss` |
| Science | `https://www.sciencemag.org/rss/current.xml` |
| PNAS | `https://www.pnas.org/rss/current.xml` |

Start with JFM + PRL + PRF + PRE + Soft Matter — those are the core CoMPhy journals.

## Suggested script structure

```python
# literature-rss-fetch.py
# Called by launchd every 6h; writes rss-papers-latest.json to staging/

ARXIV_CATEGORIES = ['physics.flu-dyn', 'cond-mat.soft', 'physics.bio-ph']
JOURNAL_FEEDS = [
    {'name': 'JFM', 'url': 'https://www.cambridge.org/core/journals/journal-of-fluid-mechanics/rss'},
    {'name': 'PRL', 'url': 'https://feeds.aps.org/rss/recent/prl.xml'},
    {'name': 'PRFluids', 'url': 'https://feeds.aps.org/rss/recent/prfluids.xml'},
    {'name': 'PRE', 'url': 'https://feeds.aps.org/rss/recent/pre.xml'},
    {'name': 'SoftMatter', 'url': 'https://feeds.rsc.org/rss/sm'},
]
```

Output record schema — same as existing staged parser schema (drop-in):
```json
{
  "source": "arxiv-rss|journal-rss",
  "feedName": "physics.flu-dyn",
  "title": "...",
  "authors": ["..."],
  "venue": "JFM",
  "year": 2026,
  "arxivId": "...",
  "doi": "...",
  "url": "...",
  "abstract": "...",
  "fetchedAt": "..."
}
```

## Integration checklist (for build session)

1. Write `~/.openclaw/shared-scripts/literature-rss-fetch.py`
2. Add call to `email-prefetch.sh` after Scholar parser (or create separate launchd job)
3. Add `rssPapers: "rss-papers-latest.json"` back to manifest
4. Update literature-collect skill: add `rss-papers-latest.json` as Step 3b source
5. Create launchd plist `ai.comphy.literature-rss-fetch` if keeping as separate job
6. Test: `python3 literature-rss-fetch.py $STAGING` should produce valid JSON
7. Run literature-collect cron once to verify deduplication + sanitization + dump update

## Notes
- deduplication: arXiv RSS entries have stable `arxivId`; journal RSS entries use DOI. Both are already in the dedupe key set.
- injection risk: RSS feeds are from trusted academic sources, but sanitization rules still apply — same field caps and injection pattern check.
- Google Scholar email stays as-is: Scholar has no RSS equivalent and the parser is working.
