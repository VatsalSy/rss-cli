# rss-cli

CLI tool for fetching RSS feeds and scrubbing the latest entries into a clean, machine-friendly output.

## Overview

`rss-cli` reads one or more RSS or Atom feeds, fetches the most recent entries, and scrubs them into a stable JSON structure for downstream processing. The default limit is `50` entries per feed, and the user can pass a different value with `--limit` or override it per row through CSV input. It can also keep only entries from the last `X` hours.

The tool is dependency-light and uses Python's standard library for fetch, XML parsing, and normalization.

`rss-cli -h` now includes usage examples, CSV schema, and behavior notes, so the CLI can be used directly without opening the source.

## Features

- Read RSS and Atom feeds from one or more URLs.
- Read feed requests from a CSV file with `feed`, `limit`, and optional `hours` columns.
- Keep the most recent `N` entries per feed with `--limit`.
- Filter feeds to entries published or updated within the last `X` hours.
- Scrub titles, summaries, content, links, categories, authors, and dates into a consistent schema.
- Emit one JSON document to stdout or write it to a file with `--output`.
- Continue across multiple feeds and report per-feed failures in an `errors` list.

## Installation

`python3 -m pip install -e .` installs `rss-cli` into the Python environment behind the `python3` command you run.

- If you have an activated virtualenv, it installs into that virtualenv.
- If you do not have a virtualenv active, it installs into the default environment for that `python3`.
- On Homebrew-managed Python, direct `pip install` may fail with `externally-managed-environment` due to PEP 668.
- Check the target environment with `which python3` and `python3 -m pip --version`.

Recommended isolated setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -e .
```

App-style install with `pipx`:

```bash
brew install pipx
pipx install --editable .
rss-cli -h
```

Use without installing into an environment:

```bash
PYTHONPATH=src python3 -m rss_cli -h
```

## Quick Start

Show built-in help:

```bash
rss-cli -h
```

If `rss-cli` is not found, either:

- install it into a virtualenv with `python3 -m venv .venv && source .venv/bin/activate && python3 -m pip install -e .`
- install it as an app with `pipx install --editable .`
- or run it directly with `PYTHONPATH=src python3 -m rss_cli`

Fetch one feed for the last 24 hours:

```bash
rss-cli --feed https://rss.arxiv.org/rss/physics.flu-dyn --hours 24 --pretty
```

Use the repo's curated feed list:

```bash
rss-cli --csv feeds.csv --pretty
```

Write JSON to a file:

```bash
rss-cli --csv feeds.csv --pretty --output latest.json
```

## Usage Patterns

Single feed:

```bash
rss-cli --feed https://rss.arxiv.org/rss/physics.flu-dyn --limit 50
```

Multiple feeds:

```bash
rss-cli --feed https://rss.arxiv.org/rss/physics.flu-dyn \
  --feed https://feeds.aps.org/rss/recent/prfluids.xml \
  --limit 50
```

Last 24 hours only:

```bash
rss-cli --feed https://rss.arxiv.org/rss/physics.flu-dyn --hours 24 --pretty
```

Last 24 hours only, capped at 20 entries:

```bash
rss-cli --feed https://feeds.aps.org/rss/recent/prfluids.xml \
  --hours 24 \
  --limit 20 \
  --pretty
```

CSV-driven input:

```bash
rss-cli --csv feeds.csv --pretty
```

Example `feeds.csv`:

```csv
feed,hours,limit
https://rss.arxiv.org/rss/physics.flu-dyn,24,50
https://feeds.aps.org/rss/recent/prfluids.xml,12,20
```

CSV column rules:

- `feed` is required.
- `hours` is optional and overrides `--hours` for that row.
- `limit` is optional and overrides `--limit` for that row.
- If a row leaves out `hours` or `limit`, the CLI falls back to the global flags.

Positional URLs also work:

```bash
rss-cli https://rss.arxiv.org/rss/physics.flu-dyn --limit 25
```

Write to a file and pretty-print:

```bash
rss-cli --feed https://rss.arxiv.org/rss/physics.flu-dyn \
  --limit 10 \
  --pretty \
  --output latest.json
```

## How It Decides What To Return

For each feed, the CLI:

1. fetches the feed XML
2. normalizes RSS/Atom fields into a stable schema
3. sorts entries by the freshest available timestamp
4. applies the `hours` window if requested
5. applies the `limit`

This means `--hours 24 --limit 20` means "keep entries from the last 24 hours, then return at most 20 of them."

## Output Shape

The CLI emits one JSON object with this top-level shape:

```json
{
  "fetched_at": "2026-03-09T21:04:54+00:00",
  "default_limit_per_feed": 50,
  "default_hours_window": 24,
  "feed_count": 1,
  "feeds": [
    {
      "feed_title": "physics.flu-dyn updates on arXiv.org",
      "feed_url": "https://rss.arxiv.org/rss/physics.flu-dyn",
      "site_url": "http://rss.arxiv.org/rss/physics.flu-dyn",
      "description": "physics.flu-dyn updates on the arXiv.org e-print archive.",
      "entry_count": 50,
      "requested_limit": 50,
      "requested_hours": 24,
      "window_start": "2026-03-08T21:04:54+00:00",
      "skipped_undated_entries": 0,
      "input_source": "cli",
      "entries": [
        {
          "entry_id": "oai:arXiv.org:2603.05547v1",
          "title": "Investigation of ...",
          "link": "https://arxiv.org/abs/2603.05547",
          "doi": null,
          "authors": ["Author Name"],
          "summary": "Scrubbed summary text",
          "content_text": null,
          "published": "2026-03-09T04:00:00+00:00",
          "published_raw": "Mon, 09 Mar 2026 00:00:00 -0400",
          "updated": null,
          "updated_raw": null,
          "categories": ["physics.flu-dyn"],
          "source_feed_title": "physics.flu-dyn updates on arXiv.org",
          "source_feed_url": "https://rss.arxiv.org/rss/physics.flu-dyn"
        }
      ]
    }
  ],
  "errors": []
}
```

## Development

Run parser tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Run without installing:

```bash
PYTHONPATH=src python3 -m rss_cli --feed https://rss.arxiv.org/rss/physics.flu-dyn --hours 24
```

## Notes

Initial design notes live in `literature-rss-plan.md`.
