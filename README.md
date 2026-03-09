# rss-cli

CLI tool for fetching RSS feeds and scrubbing the latest entries into a clean, machine-friendly output.

## Overview

`rss-cli` is a small command-line project for reading one or more RSS feeds, pulling the most recent items, and normalizing or sanitizing those entries for downstream processing. The current goal is to support academic literature feeds such as arXiv and journal RSS sources while letting the user choose how many recent entries to inspect, with `50` as the default target.

## Planned Features

- Read RSS and Atom feeds from one or more URLs.
- Limit processing to the most recent `N` entries per run.
- Scrub titles, summaries, links, and metadata into a consistent schema.
- Support safe downstream export for later ingestion or deduplication.

## Installation

Project scaffolding is in progress. A Python CLI layout is the assumed starting point.

## Usage

Expected interface:

```bash
rss-cli --feed https://rss.arxiv.org/rss/physics.flu-dyn --limit 50
```

Possible future multi-feed usage:

```bash
rss-cli --feed https://rss.arxiv.org/rss/physics.flu-dyn \
  --feed https://feeds.aps.org/rss/recent/prfluids.xml \
  --limit 50
```

## Notes

Initial design notes live in `literature-rss-plan.md`.
