"""Synthetic RSS feeds for tests. These are test fixtures only; nothing here is ever shown as real data."""
from __future__ import annotations

from datetime import datetime, timedelta
from email.utils import format_datetime
from datetime import timezone
from xml.sax.saxutils import escape

NS = ('xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:podcast="https://podcastindex.org/namespace/1.0" '
      'xmlns:content="http://purl.org/rss/1.0/modules/content/"')


def make_feed(title: str = "Test Show", n: int = 6, *, lang: str | None = "en", newest: datetime | None = None, gap_days: float = 7,
              desc: str = "A weekly show about gardening, cooking and community.", ep_desc=None, ep_title=None, podcast_guid: str | None = None,
              new_feed_url: str | None = None, transcripts: dict[int, str] | None = None, guests: bool = False, hosts: list[str] | None = None,
              categories: list[str] | None = None, skip_guids: set[str] | None = None, duration: str = "00:30:00", explicit: str = "no",
              guid_prefix: str = "ep", malformed: bool = False) -> bytes:
    newest = newest or datetime.utcnow() - timedelta(days=1)
    cats = "".join(f'<itunes:category text="{escape(c)}"/>' for c in (categories or ["Society &amp; Culture".replace("&amp;", "&")]))
    items = []
    for i in range(n):
        guid = f"{guid_prefix}-{i}"
        if skip_guids and guid in skip_guids:
            continue
        d = newest - timedelta(days=gap_days * i)
        t = ep_title(i) if ep_title else f"Episode {n - i}: topic {i}" + (" with Jane Smith" if guests else "")
        body = ep_desc(i) if ep_desc else f"In this episode we talk about topic {i}. <b>Welcome</b> friends, today we chat about local gardens and community."
        extra = ""
        if transcripts and i in transcripts:
            extra += f'<podcast:transcript url="{transcripts[i]}" type="text/plain"/>'
        if guests:
            extra += '<podcast:person role="guest">Jane Smith</podcast:person>'
        items.append(f"""<item><title>{escape(t)}</title><guid isPermaLink="false">{guid}</guid>
<pubDate>{format_datetime(d.replace(tzinfo=timezone.utc))}</pubDate><description><![CDATA[{body}]]></description>
<enclosure url="https://example.invalid/{guid}.mp3" type="audio/mpeg" length="123"/><itunes:duration>{duration}</itunes:duration>
<itunes:explicit>{explicit}</itunes:explicit>{extra}</item>""")
    head = f"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" {NS}><channel><title>{escape(title)}</title>
<link>https://example.invalid/{escape(title).replace(' ', '')}</link><description>{escape(desc)}</description>
{f'<language>{lang}</language>' if lang else ''}<itunes:explicit>{explicit}</itunes:explicit><itunes:author>Host Person</itunes:author>{cats}
{f'<podcast:guid>{podcast_guid}</podcast:guid>' if podcast_guid else ''}{f'<itunes:new-feed-url>{new_feed_url}</itunes:new-feed-url>' if new_feed_url else ''}
{''.join(f'<podcast:person role="host">{escape(h)}</podcast:person>' for h in (hosts or []))}
"""
    xml = head + "".join(items) + "</channel></rss>"
    if malformed:
        xml = xml.replace("</channel></rss>", "<broken").replace("<b>Welcome</b>", "<b>Welcome")  # truncated + unclosed tags
    return xml.encode()
