#!/usr/bin/env python3
import html
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable


DEFAULT_RSS_URL = "https://jobs.dou.ua/vacancies/feeds/?descr=1&category=Android"


@dataclass(frozen=True)
class FeedItem:
    item_id: str
    title: str
    link: str
    published: str
    summary: str


def getenv_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def getenv_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        logging.warning("Invalid %s=%r, using %s", name, value, default)
        return default


def http_get(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "dou-rss-notifier/1.0 (+https://jobs.dou.ua/)",
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def text_or_empty(element: ET.Element, path: str) -> str:
    found = element.find(path)
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def strip_markup(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<br\s*/?>", "\n", value)
    value = re.sub(r"(?s)</p\s*>", "\n", value)
    value = re.sub(r"(?s)<.*?>", " ", value)
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"\n\s+", "\n", value)
    return value.strip()


def normalize_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return value
    return parsed.strftime("%Y-%m-%d %H:%M %Z").strip()


def parse_feed(payload: bytes) -> list[FeedItem]:
    root = ET.fromstring(payload)
    items = root.findall("./channel/item")

    parsed_items: list[FeedItem] = []
    for item in items:
        title = text_or_empty(item, "title")
        link = text_or_empty(item, "link")
        guid = text_or_empty(item, "guid")
        published = normalize_date(text_or_empty(item, "pubDate"))
        description = strip_markup(text_or_empty(item, "description"))
        item_id = guid or link or title

        if not item_id:
            continue

        parsed_items.append(
            FeedItem(
                item_id=item_id,
                title=title or "New vacancy",
                link=link,
                published=published,
                summary=description,
            )
        )

    return parsed_items


def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logging.warning("Could not read state file %s: %s", path, exc)
        return set()

    if isinstance(raw, list):
        return {str(item) for item in raw}

    logging.warning("State file %s has unexpected format, starting fresh", path)
    return set()


def save_seen(path: Path, seen: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(sorted(set(seen)), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def build_message(item: FeedItem, max_summary_chars: int) -> str:
    lines = [
        f"<b>{html.escape(item.title)}</b>",
    ]

    if item.published:
        lines.append(html.escape(item.published))

    if item.link:
        escaped_link = html.escape(item.link, quote=True)
        lines.append(f'<a href="{escaped_link}">Open vacancy</a>')

    summary = item.summary.strip()
    if summary and max_summary_chars > 0:
        if len(summary) > max_summary_chars:
            summary = summary[: max_summary_chars - 1].rstrip() + "..."
        lines.append("")
        lines.append(html.escape(summary))

    return "\n".join(lines)


def send_telegram(message: str, timeout: int) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logging.info("Telegram is not configured; would send:\n%s", message)
        return

    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }
    ).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def run_once(
    rss_url: str,
    state_file: Path,
    first_run_send_existing: bool,
    max_items_per_poll: int,
    max_summary_chars: int,
    http_timeout: int,
) -> None:
    seen = load_seen(state_file)
    payload = http_get(rss_url, timeout=http_timeout)
    items = parse_feed(payload)

    if not items:
        logging.info("No items found in RSS feed")
        return

    logging.info("Fetched %s items from RSS feed", len(items))

    if not seen and not first_run_send_existing:
        save_seen(state_file, {item.item_id for item in items})
        logging.info(
            "First run: saved %s existing items without sending notifications",
            len(items),
        )
        return

    new_items = [item for item in items if item.item_id not in seen]
    if max_items_per_poll > 0:
        new_items = new_items[:max_items_per_poll]

    if not new_items:
        logging.info("No new vacancies")
        return

    for item in reversed(new_items):
        message = build_message(item, max_summary_chars=max_summary_chars)
        send_telegram(message, timeout=http_timeout)
        seen.add(item.item_id)
        save_seen(state_file, seen)
        logging.info("Sent notification for: %s", item.title)


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    rss_url = os.getenv("RSS_URL", DEFAULT_RSS_URL).strip() or DEFAULT_RSS_URL
    state_file = Path(os.getenv("STATE_FILE", "/data/seen.json"))
    poll_interval = getenv_int("POLL_INTERVAL_SECONDS", 300)
    http_timeout = getenv_int("HTTP_TIMEOUT_SECONDS", 20)
    max_items_per_poll = getenv_int("MAX_ITEMS_PER_POLL", 20)
    max_summary_chars = getenv_int("MAX_SUMMARY_CHARS", 1200)
    first_run_send_existing = getenv_bool("FIRST_RUN_SEND_EXISTING", False)
    run_once_only = getenv_bool("RUN_ONCE", False)

    logging.info("Watching RSS feed: %s", rss_url)

    while True:
        try:
            run_once(
                rss_url=rss_url,
                state_file=state_file,
                first_run_send_existing=first_run_send_existing,
                max_items_per_poll=max_items_per_poll,
                max_summary_chars=max_summary_chars,
                http_timeout=http_timeout,
            )
        except (ET.ParseError, urllib.error.URLError, TimeoutError, OSError) as exc:
            logging.exception("Polling failed: %s", exc)

        if run_once_only:
            return 0

        time.sleep(max(30, poll_interval))


if __name__ == "__main__":
    sys.exit(main())
