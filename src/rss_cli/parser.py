"""RSS and Atom feed fetching and normalization."""

from __future__ import annotations

from codecs import BOM_UTF16_BE, BOM_UTF16_LE, BOM_UTF8
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import json
import re
from typing import Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


USER_AGENT = "rss-cli/0.1 (+https://example.invalid/rss-cli)"
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")
SPACE_BEFORE_PUNCT_PATTERN = re.compile(r"\s+([,.;:!?])")
XML_ENCODING_PATTERN = re.compile(br"""<\?xml[^>]*encoding=["']([^"']+)["']""", re.IGNORECASE)


def utc_now_iso() -> str:
  """Return the current UTC time as an ISO 8601 string."""
  return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def local_name(tag: str) -> str:
  """Drop any XML namespace from a tag name."""
  if "}" in tag:
    return tag.rsplit("}", 1)[-1]
  return tag


def scrub_text(value: Optional[str]) -> Optional[str]:
  """Strip markup and normalize whitespace."""
  if value is None:
    return None

  cleaned = value.strip()
  if not cleaned:
    return None

  # Some feeds double-escape HTML entities; unescaping twice is safe here.
  cleaned = unescape(unescape(cleaned))
  cleaned = TAG_PATTERN.sub(" ", cleaned)
  cleaned = WHITESPACE_PATTERN.sub(" ", cleaned).strip()
  cleaned = SPACE_BEFORE_PUNCT_PATTERN.sub(r"\1", cleaned)
  return cleaned or None


def normalize_date(value: Optional[str]) -> Optional[str]:
  """Convert common RSS/Atom date strings to ISO 8601 when possible."""
  if not value:
    return None

  trimmed = value.strip()
  if not trimmed:
    return None

  try:
    parsed = parsedate_to_datetime(trimmed)
  except (TypeError, ValueError, IndexError, OverflowError):
    parsed = None

  if parsed is None:
    iso_candidate = trimmed.replace("Z", "+00:00")
    try:
      parsed = datetime.fromisoformat(iso_candidate)
    except ValueError:
      return trimmed

  if parsed.tzinfo is None:
    parsed = parsed.replace(tzinfo=timezone.utc)

  return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_entry_datetime(entry: dict) -> Optional[datetime]:
  """Return the freshest available timestamp for a normalized entry."""
  candidates: list[datetime] = []
  for key in ("published", "updated"):
    value = entry.get(key)
    if not value:
      continue
    try:
      parsed = datetime.fromisoformat(str(value))
    except ValueError:
      continue
    if parsed.tzinfo is None:
      parsed = parsed.replace(tzinfo=timezone.utc)
    candidates.append(parsed.astimezone(timezone.utc))

  if not candidates:
    return None
  return max(candidates)


def extract_doi(*values: Optional[str]) -> Optional[str]:
  """Find a DOI in any candidate field."""
  for value in values:
    if not value:
      continue
    match = DOI_PATTERN.search(value)
    if match:
      return match.group(0)
  return None


def child_elements(element: ET.Element, tag_name: str) -> list[ET.Element]:
  """Return direct children matching a local tag name."""
  return [child for child in element if local_name(child.tag) == tag_name]


def first_child(element: ET.Element, *tag_names: str) -> Optional[ET.Element]:
  """Return the first direct child matching one of the provided tag names."""
  names = set(tag_names)
  for child in element:
    if local_name(child.tag) in names:
      return child
  return None


def element_text(element: Optional[ET.Element]) -> Optional[str]:
  """Join all text inside an XML element and scrub it."""
  if element is None:
    return None
  text = "".join(element.itertext())
  return scrub_text(text)


def first_child_text(element: ET.Element, *tag_names: str) -> Optional[str]:
  """Return the scrubbed text of the first matching direct child."""
  return element_text(first_child(element, *tag_names))


def normalize_author(value: Optional[str]) -> Optional[str]:
  """Clean common RSS author field variants."""
  cleaned = scrub_text(value)
  if not cleaned:
    return None

  if "(" in cleaned and cleaned.endswith(")"):
    _, maybe_name = cleaned.rsplit("(", 1)
    maybe_name = maybe_name[:-1].strip()
    if maybe_name:
      return maybe_name

  if "@" in cleaned and " " not in cleaned:
    return None

  return cleaned


def unique_nonempty(values: Iterable[Optional[str]]) -> list[str]:
  """Preserve order while dropping empty or duplicate values."""
  seen: set[str] = set()
  result: list[str] = []
  for value in values:
    if not value or value in seen:
      continue
    seen.add(value)
    result.append(value)
  return result


def sort_entries_by_recency(entries: list[dict]) -> list[dict]:
  """Sort entries from newest to oldest using the freshest parsed timestamp."""
  indexed_entries = list(enumerate(entries))

  def sort_key(item: tuple[int, dict]) -> tuple[int, float, int]:
    original_index, entry = item
    parsed = parse_entry_datetime(entry)
    if parsed is None:
      return (1, 0.0, original_index)
    return (0, -parsed.timestamp(), original_index)

  return [entry for _, entry in sorted(indexed_entries, key=sort_key)]


def parse_atom_link(element: ET.Element) -> Optional[str]:
  """Return the preferred Atom entry/feed link."""
  links = child_elements(element, "link")
  if not links:
    return None

  for link in links:
    rel = link.attrib.get("rel", "alternate")
    href = scrub_text(link.attrib.get("href"))
    if rel == "alternate" and href:
      return href

  for link in links:
    href = scrub_text(link.attrib.get("href"))
    if href:
      return href

  return None


def parse_categories(element: ET.Element) -> list[str]:
  """Collect categories from RSS or Atom items."""
  categories: list[str] = []
  for child in element:
    if local_name(child.tag) != "category":
      continue
    term = scrub_text(child.attrib.get("term")) or element_text(child)
    if term:
      categories.append(term)
  return unique_nonempty(categories)


def parse_rss_authors(item: ET.Element) -> list[str]:
  """Collect RSS author-like fields."""
  authors: list[str] = []
  for child in item:
    if local_name(child.tag) not in {"author", "creator"}:
      continue
    author = normalize_author("".join(child.itertext()))
    if author:
      authors.append(author)
  return unique_nonempty(authors)


def parse_atom_authors(entry: ET.Element) -> list[str]:
  """Collect Atom author names."""
  authors: list[str] = []
  for child in child_elements(entry, "author"):
    name = first_child_text(child, "name") or element_text(child)
    author = normalize_author(name)
    if author:
      authors.append(author)
  return unique_nonempty(authors)


def normalize_rss_item(item: ET.Element, feed_title: Optional[str], source_url: str) -> dict:
  """Convert an RSS item into the stable output schema."""
  title = first_child_text(item, "title")
  link = first_child_text(item, "link")
  entry_id = first_child_text(item, "guid", "id", "identifier")
  summary = first_child_text(item, "description", "summary")
  content_text = first_child_text(item, "encoded", "content")
  published_raw = first_child_text(item, "pubDate", "published", "date", "publicationDate")
  updated_raw = first_child_text(item, "updated", "lastBuildDate", "modified")
  doi = extract_doi(link, entry_id, summary, content_text)

  return {
    "entry_id": entry_id or link or title,
    "title": title,
    "link": link,
    "doi": doi,
    "authors": parse_rss_authors(item),
    "summary": summary or content_text,
    "content_text": content_text,
    "published": normalize_date(published_raw),
    "published_raw": published_raw,
    "updated": normalize_date(updated_raw),
    "updated_raw": updated_raw,
    "categories": parse_categories(item),
    "source_feed_title": feed_title,
    "source_feed_url": source_url,
  }


def normalize_atom_entry(entry: ET.Element, feed_title: Optional[str], source_url: str) -> dict:
  """Convert an Atom entry into the stable output schema."""
  title = first_child_text(entry, "title")
  link = parse_atom_link(entry)
  entry_id = first_child_text(entry, "id")
  summary = first_child_text(entry, "summary")
  content_text = first_child_text(entry, "content")
  published_raw = first_child_text(entry, "published")
  updated_raw = first_child_text(entry, "updated", "modified")
  doi = extract_doi(link, entry_id, summary, content_text)

  return {
    "entry_id": entry_id or link or title,
    "title": title,
    "link": link,
    "doi": doi,
    "authors": parse_atom_authors(entry),
    "summary": summary or content_text,
    "content_text": content_text,
    "published": normalize_date(published_raw),
    "published_raw": published_raw,
    "updated": normalize_date(updated_raw),
    "updated_raw": updated_raw,
    "categories": parse_categories(entry),
    "source_feed_title": feed_title,
    "source_feed_url": source_url,
  }


def parse_rss_feed(root: ET.Element, source_url: str, limit: int) -> dict:
  """Parse an RSS feed document."""
  channel = first_child(root, "channel") or root
  feed_title = first_child_text(channel, "title")
  feed_link = first_child_text(channel, "link") or source_url
  feed_description = first_child_text(channel, "description")
  items = child_elements(channel, "item")
  if not items:
    items = [item for item in root.iter() if local_name(item.tag) == "item"]

  entries = [normalize_rss_item(item, feed_title, source_url) for item in items]
  entries = sort_entries_by_recency(entries)[:limit]
  return {
    "feed_title": feed_title,
    "feed_url": source_url,
    "site_url": feed_link,
    "description": feed_description,
    "entry_count": len(entries),
    "entries": entries,
  }


def parse_atom_feed(root: ET.Element, source_url: str, limit: int) -> dict:
  """Parse an Atom feed document."""
  feed_title = first_child_text(root, "title")
  feed_link = parse_atom_link(root) or source_url
  feed_description = first_child_text(root, "subtitle")
  entries = [
    normalize_atom_entry(entry, feed_title, source_url)
    for entry in child_elements(root, "entry")
  ]
  entries = sort_entries_by_recency(entries)[:limit]
  return {
    "feed_title": feed_title,
    "feed_url": source_url,
    "site_url": feed_link,
    "description": feed_description,
    "entry_count": len(entries),
    "entries": entries,
  }


def parse_feed_document(xml_text: str, source_url: str, limit: int = 50) -> dict:
  """Parse feed XML into a normalized structure."""
  if limit < 1:
    raise ValueError("limit must be at least 1")

  try:
    root = ET.fromstring(xml_text)
  except ET.ParseError as exc:
    raise ValueError(f"could not parse feed XML: {exc}") from exc

  root_name = local_name(root.tag)
  if root_name == "feed":
    return parse_atom_feed(root, source_url, limit)
  if root_name in {"rss", "RDF"}:
    return parse_rss_feed(root, source_url, limit)

  if first_child(root, "channel") is not None or any(local_name(node.tag) == "item" for node in root.iter()):
    return parse_rss_feed(root, source_url, limit)

  raise ValueError(f"unsupported feed root element: {root_name}")


def detect_xml_encoding(payload: bytes) -> Optional[str]:
  """Inspect BOMs and XML declarations for a declared document encoding."""
  if payload.startswith(BOM_UTF8):
    return "utf-8-sig"
  if payload.startswith(BOM_UTF16_LE):
    return "utf-16-le"
  if payload.startswith(BOM_UTF16_BE):
    return "utf-16-be"

  head = payload[:256]
  match = XML_ENCODING_PATTERN.search(head)
  if not match:
    return None
  try:
    return match.group(1).decode("ascii")
  except UnicodeDecodeError:
    return None


def decode_feed_payload(payload: bytes, http_charset: Optional[str]) -> str:
  """Decode feed bytes, honoring HTTP charset first and XML encoding second."""
  candidate_encodings = []
  if http_charset:
    candidate_encodings.append(http_charset)

  declared_encoding = detect_xml_encoding(payload)
  if declared_encoding and declared_encoding not in candidate_encodings:
    candidate_encodings.append(declared_encoding)

  for encoding in candidate_encodings:
    try:
      return payload.decode(encoding)
    except (LookupError, UnicodeDecodeError):
      continue

  return payload.decode("utf-8", errors="replace")


def fetch_feed_xml(url: str, timeout: float = 20.0) -> str:
  """Fetch raw feed XML from a URL."""
  request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})

  try:
    with urlopen(request, timeout=timeout) as response:
      payload = response.read()
      charset = response.headers.get_content_charset()
  except HTTPError as exc:
    raise RuntimeError(f"HTTP {exc.code} while fetching {url}") from exc
  except URLError as exc:
    raise RuntimeError(f"network error while fetching {url}: {exc.reason}") from exc

  return decode_feed_payload(payload, charset)


def fetch_and_parse_feed(url: str, limit: int = 50, timeout: float = 20.0) -> dict:
  """Fetch a feed URL and return normalized data."""
  xml_text = fetch_feed_xml(url, timeout=timeout)
  return parse_feed_document(xml_text, source_url=url, limit=limit)


def dump_json(data: dict, pretty: bool = False) -> str:
  """Serialize results as JSON."""
  if pretty:
    return json.dumps(data, indent=2, ensure_ascii=True) + "\n"
  return json.dumps(data, separators=(",", ":"), ensure_ascii=True) + "\n"
