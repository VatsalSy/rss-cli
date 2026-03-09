"""Command-line interface for rss-cli."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
import math
from pathlib import Path
import sys
from typing import Optional

from .parser import dump_json, fetch_and_parse_feed, parse_entry_datetime, utc_now_iso


def parse_row_limit(value: str, default_limit: int, row_number: int) -> int:
  """Parse an optional per-row limit from CSV input."""
  cleaned = value.strip()
  if not cleaned:
    return default_limit

  try:
    limit = int(cleaned)
  except ValueError as exc:
    raise ValueError(f"row {row_number}: invalid limit value {cleaned!r}") from exc

  if limit < 1:
    raise ValueError(f"row {row_number}: limit must be at least 1")
  return limit


def parse_hours_value(value: str, row_number: Optional[int] = None) -> float:
  """Parse an hour-window value from CLI or CSV input."""
  cleaned = value.strip()
  try:
    hours = float(cleaned)
  except ValueError as exc:
    prefix = f"row {row_number}: " if row_number is not None else ""
    raise ValueError(f"{prefix}invalid hours value {cleaned!r}") from exc

  if not math.isfinite(hours):
    prefix = f"row {row_number}: " if row_number is not None else ""
    raise ValueError(f"{prefix}hours must be a finite number")

  if hours <= 0:
    prefix = f"row {row_number}: " if row_number is not None else ""
    raise ValueError(f"{prefix}hours must be greater than 0")
  return hours


def parse_row_hours(value: str, default_hours: Optional[float], row_number: int) -> Optional[float]:
  """Parse an optional per-row hour window from CSV input."""
  cleaned = value.strip()
  if not cleaned:
    return default_hours
  return parse_hours_value(cleaned, row_number=row_number)


def parse_entry_timestamp(entry: dict) -> Optional[datetime]:
  """Return the best available parsed timestamp for an entry."""
  return parse_entry_datetime(entry)


def filter_feed_entries(feed_payload: dict, hours: Optional[float], reference_time: datetime) -> tuple[dict, int]:
  """Apply an optional last-X-hours filter to a parsed feed payload."""
  if hours is None:
    return feed_payload, 0

  window_start = reference_time - timedelta(hours=hours)
  filtered_entries = []
  skipped_undated = 0

  for entry in feed_payload.get("entries", []):
    entry_time = parse_entry_timestamp(entry)
    if entry_time is None:
      skipped_undated += 1
      continue
    if entry_time >= window_start:
      filtered_entries.append(entry)

  updated_payload = dict(feed_payload)
  updated_payload["entries"] = filtered_entries
  updated_payload["entry_count"] = len(filtered_entries)
  updated_payload["requested_hours"] = hours
  updated_payload["window_start"] = window_start.replace(microsecond=0).isoformat()
  updated_payload["skipped_undated_entries"] = skipped_undated
  return updated_payload, skipped_undated


def load_csv_requests(csv_path: Path, default_limit: int, default_hours: Optional[float]) -> list[dict[str, object]]:
  """Load feed requests from a CSV file."""
  with csv_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    fieldnames = reader.fieldnames or []
    normalized_names = {name.strip().lower(): name for name in fieldnames}

    if "feed" not in normalized_names:
      raise ValueError("CSV input must include a 'feed' column")

    feed_column = normalized_names["feed"]
    limit_column: Optional[str] = normalized_names.get("limit")
    hours_column: Optional[str] = normalized_names.get("hours")

    requests: list[dict[str, object]] = []
    for row_number, row in enumerate(reader, start=2):
      feed_url = (row.get(feed_column) or "").strip()
      if not feed_url:
        continue

      row_limit_value = row.get(limit_column, "") if limit_column else ""
      row_hours_value = row.get(hours_column, "") if hours_column else ""
      requests.append(
        {
          "feed_url": feed_url,
          "limit": parse_row_limit(str(row_limit_value), default_limit, row_number),
          "hours": parse_row_hours(str(row_hours_value), default_hours, row_number),
          "row_number": row_number,
          "input_source": str(csv_path),
        }
      )

  return requests


def build_requests(args: argparse.Namespace) -> list[dict[str, object]]:
  """Combine direct feeds and CSV rows into one request list."""
  requests = [
    {
      "feed_url": feed_url,
      "limit": args.limit,
      "hours": args.hours,
      "row_number": None,
      "input_source": "cli",
    }
    for feed_url in args.feed_flags + args.feeds
  ]

  if args.csv:
    requests.extend(load_csv_requests(args.csv, args.limit, args.hours))

  return requests


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
  """Parse CLI arguments."""
  parser = argparse.ArgumentParser(
    prog="rss-cli",
    description="Fetch RSS or Atom feeds and scrub recent entries into normalized JSON.",
  )
  parser.add_argument(
    "feeds",
    nargs="*",
    help="Feed URLs. You can also pass feeds with repeated --feed flags.",
  )
  parser.add_argument(
    "--feed",
    action="append",
    default=[],
    dest="feed_flags",
    help="RSS or Atom feed URL. Repeat for multiple feeds.",
  )
  parser.add_argument(
    "--csv",
    type=Path,
    help="CSV file with a required 'feed' column and optional per-row 'limit' column.",
  )
  parser.add_argument(
    "--limit",
    type=int,
    default=50,
    help="Default maximum number of recent entries to keep per feed. Default: 50.",
  )
  parser.add_argument(
    "--hours",
    type=float,
    help="Keep only entries published or updated within the last X hours.",
  )
  parser.add_argument(
    "--timeout",
    type=float,
    default=20.0,
    help="Per-feed network timeout in seconds. Default: 20.",
  )
  parser.add_argument(
    "--output",
    type=Path,
    help="Write JSON output to a file instead of stdout.",
  )
  parser.add_argument(
    "--pretty",
    action="store_true",
    help="Pretty-print JSON output.",
  )
  return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
  """Run the CLI."""
  args = parse_args(argv)

  if args.limit < 1:
    print("rss-cli: --limit must be at least 1", file=sys.stderr)
    return 2

  if args.hours is not None:
    try:
      args.hours = parse_hours_value(str(args.hours))
    except ValueError as exc:
      print(f"rss-cli: {exc}", file=sys.stderr)
      return 2

  try:
    requests = build_requests(args)
  except Exception as exc:
    print(f"rss-cli: {exc}", file=sys.stderr)
    return 2

  if not requests:
    print("rss-cli: provide at least one feed URL via --feed, positional arguments, or --csv", file=sys.stderr)
    return 2

  payload = {
    "fetched_at": utc_now_iso(),
    "default_limit_per_feed": args.limit,
    "default_hours_window": args.hours,
    "feed_count": len(requests),
    "feeds": [],
    "errors": [],
  }
  fetched_at = datetime.fromisoformat(payload["fetched_at"])

  exit_code = 0
  for request in requests:
    feed_url = str(request["feed_url"])
    limit = int(request["limit"])
    hours = request["hours"]
    row_number = request["row_number"]
    input_source = str(request["input_source"])

    try:
      feed_payload = fetch_and_parse_feed(feed_url, limit=limit, timeout=args.timeout)
      feed_payload, _ = filter_feed_entries(feed_payload, hours, fetched_at)
      feed_payload["requested_limit"] = limit
      feed_payload["requested_hours"] = hours
      feed_payload["input_source"] = input_source
      if row_number is not None:
        feed_payload["row_number"] = row_number
      payload["feeds"].append(feed_payload)
    except Exception as exc:  # pragma: no cover - exercised through CLI behavior
      error_payload = {
        "feed_url": feed_url,
        "requested_limit": limit,
        "requested_hours": hours,
        "input_source": input_source,
        "error": str(exc),
      }
      if row_number is not None:
        error_payload["row_number"] = row_number
      payload["errors"].append(error_payload)
      exit_code = 1

  rendered = dump_json(payload, pretty=args.pretty)
  if args.output:
    args.output.write_text(rendered, encoding="utf-8")
  else:
    sys.stdout.write(rendered)

  return exit_code
