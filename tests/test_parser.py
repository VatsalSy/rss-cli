"""Tests for feed parsing and scrubbing."""

import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rss_cli import cli
from rss_cli.parser import decode_feed_payload, parse_entry_datetime, parse_feed_document


RSS_SAMPLE = """\
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Example RSS</title>
    <link>https://example.com</link>
    <description>Example feed</description>
    <item>
      <title>First &amp;lt;b&amp;gt;Entry&amp;lt;/b&amp;gt;</title>
      <link>https://doi.org/10.1234/example.1</link>
      <description><![CDATA[<p>Summary <b>one</b>.</p>]]></description>
      <content:encoded><![CDATA[<div>Full <i>content</i>.</div>]]></content:encoded>
      <dc:creator>Author One</dc:creator>
      <category>Physics</category>
      <guid>item-1</guid>
      <pubDate>Mon, 09 Mar 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second Entry</title>
      <link>https://example.com/2</link>
      <description>Summary two</description>
      <guid>item-2</guid>
      <pubDate>Mon, 09 Mar 2026 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


RDF_SAMPLE = """\
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns="http://purl.org/rss/1.0/">
  <channel rdf:about="https://example.net/journal">
    <title>Example RDF Feed</title>
    <link>https://example.net/journal</link>
    <description>Example RDF description</description>
  </channel>
  <item rdf:about="https://example.net/article">
    <title>RDF Entry</title>
    <link>https://example.net/article</link>
    <description>RDF summary</description>
    <dc:creator>RDF Author</dc:creator>
    <dc:date>2026-03-09T10:00:00+00:00</dc:date>
    <dc:identifier>doi:10.1103/example-doi</dc:identifier>
  </item>
</rdf:RDF>
"""


ATOM_SAMPLE = """\
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Atom</title>
  <link rel="alternate" href="https://example.org" />
  <subtitle>Atom subtitle</subtitle>
  <entry>
    <title>Atom Entry</title>
    <id>tag:example.org,2026:1</id>
    <link rel="alternate" href="https://example.org/entry" />
    <summary type="html">&lt;p&gt;Atom &lt;b&gt;summary&lt;/b&gt;.&lt;/p&gt;</summary>
    <author><name>Atom Author</name></author>
    <category term="Research" />
    <published>2026-03-09T12:00:00Z</published>
    <updated>2026-03-09T12:30:00Z</updated>
  </entry>
</feed>
"""


OUT_OF_ORDER_RSS_SAMPLE = """\
<rss version="2.0">
  <channel>
    <title>Out of Order RSS</title>
    <item>
      <title>Older</title>
      <link>https://example.com/older</link>
      <pubDate>Mon, 09 Mar 2026 08:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Newest</title>
      <link>https://example.com/newest</link>
      <pubDate>Mon, 09 Mar 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Middle</title>
      <link>https://example.com/middle</link>
      <pubDate>Mon, 09 Mar 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class ParseFeedDocumentTests(unittest.TestCase):
  def test_rss_limit_and_scrub(self) -> None:
    parsed = parse_feed_document(RSS_SAMPLE, source_url="https://example.com/rss", limit=1)

    self.assertEqual(parsed["feed_title"], "Example RSS")
    self.assertEqual(parsed["entry_count"], 1)
    entry = parsed["entries"][0]
    self.assertEqual(entry["title"], "First Entry")
    self.assertEqual(entry["summary"], "Summary one.")
    self.assertEqual(entry["content_text"], "Full content.")
    self.assertEqual(entry["authors"], ["Author One"])
    self.assertEqual(entry["categories"], ["Physics"])
    self.assertEqual(entry["doi"], "10.1234/example.1")
    self.assertEqual(entry["published"], "2026-03-09T10:00:00+00:00")

  def test_atom_scrub(self) -> None:
    parsed = parse_feed_document(ATOM_SAMPLE, source_url="https://example.org/feed", limit=50)

    self.assertEqual(parsed["feed_title"], "Example Atom")
    self.assertEqual(parsed["description"], "Atom subtitle")
    self.assertEqual(parsed["entry_count"], 1)
    entry = parsed["entries"][0]
    self.assertEqual(entry["title"], "Atom Entry")
    self.assertEqual(entry["summary"], "Atom summary.")
    self.assertEqual(entry["authors"], ["Atom Author"])
    self.assertEqual(entry["categories"], ["Research"])
    self.assertEqual(entry["link"], "https://example.org/entry")
    self.assertEqual(entry["published"], "2026-03-09T12:00:00+00:00")

  def test_rdf_rss_uses_dc_date(self) -> None:
    parsed = parse_feed_document(RDF_SAMPLE, source_url="https://example.net/feed", limit=50)

    self.assertEqual(parsed["feed_title"], "Example RDF Feed")
    self.assertEqual(parsed["entry_count"], 1)
    entry = parsed["entries"][0]
    self.assertEqual(entry["title"], "RDF Entry")
    self.assertEqual(entry["authors"], ["RDF Author"])
    self.assertEqual(entry["published"], "2026-03-09T10:00:00+00:00")
    self.assertEqual(entry["doi"], "10.1103/example-doi")

  def test_limit_keeps_most_recent_entries_even_if_feed_is_unsorted(self) -> None:
    parsed = parse_feed_document(OUT_OF_ORDER_RSS_SAMPLE, source_url="https://example.com/rss", limit=2)

    self.assertEqual([entry["title"] for entry in parsed["entries"]], ["Newest", "Middle"])

  def test_decode_feed_payload_honors_xml_declared_encoding_without_http_charset(self) -> None:
    payload = b'<?xml version="1.0" encoding="ISO-8859-1"?><rss><channel><title>caf\xe9</title></channel></rss>'

    decoded = decode_feed_payload(payload, http_charset=None)

    self.assertIn("café", decoded)


if __name__ == "__main__":
  unittest.main()


class CliCsvTests(unittest.TestCase):
  def test_load_csv_requests_uses_row_limit_or_default(self) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
      csv_path = Path(tmp_dir) / "feeds.csv"
      csv_path.write_text(
        "feed,limit,hours\n"
        "https://example.com/feed-a,3,12\n"
        "https://example.com/feed-b,,\n",
        encoding="utf-8",
      )

      requests = cli.load_csv_requests(csv_path, default_limit=50, default_hours=24.0)

    self.assertEqual(
      requests,
      [
        {
          "feed_url": "https://example.com/feed-a",
          "limit": 3,
          "hours": 12.0,
          "row_number": 2,
          "input_source": str(csv_path),
        },
        {
          "feed_url": "https://example.com/feed-b",
          "limit": 50,
          "hours": 24.0,
          "row_number": 3,
          "input_source": str(csv_path),
        },
      ],
    )

  def test_main_supports_csv_input(self) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
      csv_path = Path(tmp_dir) / "feeds.csv"
      csv_path.write_text("feed,limit,hours\nhttps://example.com/feed-a,2,6\n", encoding="utf-8")

      def fake_fetch(feed_url: str, limit: int, timeout: float) -> dict:
        return {
          "feed_title": "Example Feed",
          "feed_url": feed_url,
          "site_url": feed_url,
          "description": None,
          "entry_count": limit,
          "entries": [{"entry_id": "x", "published": "2026-03-09T11:00:00+00:00", "updated": None}],
        }

      with mock.patch("rss_cli.cli.fetch_and_parse_feed", side_effect=fake_fetch):
        with mock.patch("sys.stdout.write") as stdout_write:
          with mock.patch("rss_cli.cli.utc_now_iso", return_value="2026-03-09T12:00:00+00:00"):
            exit_code = cli.main(["--csv", str(csv_path), "--pretty"])

    self.assertEqual(exit_code, 0)
    rendered = "".join(call.args[0] for call in stdout_write.call_args_list)
    payload = json.loads(rendered)
    self.assertEqual(payload["feed_count"], 1)
    self.assertEqual(payload["default_limit_per_feed"], 50)
    self.assertIsNone(payload["default_hours_window"])
    self.assertEqual(payload["feeds"][0]["feed_url"], "https://example.com/feed-a")
    self.assertEqual(payload["feeds"][0]["requested_limit"], 2)
    self.assertEqual(payload["feeds"][0]["requested_hours"], 6.0)
    self.assertEqual(payload["feeds"][0]["row_number"], 2)
    self.assertEqual(payload["feeds"][0]["input_source"], str(csv_path))
    self.assertEqual(payload["feeds"][0]["window_start"], "2026-03-09T06:00:00+00:00")

  def test_filter_feed_entries_keeps_only_recent_entries(self) -> None:
    feed_payload = {
      "entries": [
        {"entry_id": "recent", "published": "2026-03-09T10:30:00+00:00", "updated": None},
        {"entry_id": "old", "published": "2026-03-09T02:00:00+00:00", "updated": None},
        {"entry_id": "undated", "published": None, "updated": None},
      ],
      "entry_count": 3,
    }

    filtered, skipped_undated = cli.filter_feed_entries(
      feed_payload,
      hours=4.0,
      reference_time=datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc),
    )

    self.assertEqual(filtered["entry_count"], 1)
    self.assertEqual([entry["entry_id"] for entry in filtered["entries"]], ["recent"])
    self.assertEqual(filtered["requested_hours"], 4.0)
    self.assertEqual(filtered["window_start"], "2026-03-09T08:00:00+00:00")
    self.assertEqual(filtered["skipped_undated_entries"], 1)
    self.assertEqual(skipped_undated, 1)

  def test_parse_entry_timestamp_prefers_newer_updated_time(self) -> None:
    entry = {
      "published": "2026-03-09T08:00:00+00:00",
      "updated": "2026-03-09T11:00:00+00:00",
    }

    parsed = cli.parse_entry_timestamp(entry)

    self.assertEqual(parsed, datetime(2026, 3, 9, 11, 0, tzinfo=timezone.utc))
    self.assertEqual(parse_entry_datetime(entry), parsed)

  def test_parse_hours_value_rejects_non_finite_numbers(self) -> None:
    with self.assertRaisesRegex(ValueError, "finite number"):
      cli.parse_hours_value("nan")

    with self.assertRaisesRegex(ValueError, "finite number"):
      cli.parse_hours_value("inf")
