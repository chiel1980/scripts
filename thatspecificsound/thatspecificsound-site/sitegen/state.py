"""
state.py
--------
Persists what has already been scraped so repeat runs are incremental:

- data/state.json          one record per source URL: HTTP caching tokens
                            (ETag / Last-Modified), a content hash, and
                            timestamps for "first seen" / "last changed".
- data/content_cache.json  the cleaned, parsed content for every page we
                            know about, keyed by URL. This is what lets us
                            re-render the *whole* site every run (cheap)
                            without re-downloading pages that haven't
                            changed on the source (the expensive part).
- data/changelog.json      an append-only log of new/updated/removed pages,
                            one entry per run. Also rendered as a human
                            readable CHANGELOG.md and a /changes.html page
                            on the generated site.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_FILE = DATA_DIR / "state.json"
CACHE_FILE = DATA_DIR / "content_cache.json"
CHANGELOG_FILE = DATA_DIR / "changelog.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, data) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)


class ScrapeState:
    """In-memory view of state.json + content_cache.json with save()."""

    def __init__(self):
        raw = load_json(STATE_FILE, {"pages": {}, "last_run": None})
        self.pages: dict = raw.get("pages", {})
        self.last_run: str | None = raw.get("last_run")
        self.content_cache: dict = load_json(CACHE_FILE, {})
        self.changelog: list = load_json(CHANGELOG_FILE, [])
        # per-run bookkeeping
        self.run_events: list[dict] = []
        self.seen_urls: set[str] = set()

    # ---- per-page bookkeeping -------------------------------------------------

    def get_cache_headers(self, url: str) -> dict:
        rec = self.pages.get(url)
        if not rec:
            return {}
        return {"etag": rec.get("etag"), "last_modified": rec.get("last_modified")}

    def get_content_hash(self, url: str) -> str | None:
        rec = self.pages.get(url)
        return rec.get("content_hash") if rec else None

    def get_cached_content(self, url: str) -> dict | None:
        return self.content_cache.get(url)

    def record_unchanged(self, url: str) -> None:
        self.seen_urls.add(url)

    def record_page(
        self,
        url: str,
        *,
        page_type: str,
        title: str,
        content_hash: str,
        cache_headers: dict,
        parsed_content: dict,
        status: str,  # "new" | "updated"
    ) -> None:
        self.seen_urls.add(url)
        rec = self.pages.get(url, {})
        is_new = url not in self.pages
        rec.update(
            {
                "type": page_type,
                "title": title,
                "content_hash": content_hash,
                "etag": cache_headers.get("etag"),
                "last_modified": cache_headers.get("last_modified"),
                "last_changed": _now(),
                "first_seen": rec.get("first_seen", _now()),
            }
        )
        self.pages[url] = rec
        self.content_cache[url] = parsed_content
        self.run_events.append(
            {
                "url": url,
                "title": title,
                "type": page_type,
                "status": "new" if is_new else status,
            }
        )

    def detect_removed(self) -> list[str]:
        """URLs we knew about previously but did not encounter this run."""
        removed = [u for u in self.pages if u not in self.seen_urls]
        for u in removed:
            rec = self.pages.pop(u)
            self.content_cache.pop(u, None)
            self.run_events.append(
                {"url": u, "title": rec.get("title", u), "type": rec.get("type", "page"), "status": "removed"}
            )
        return removed

    # ---- persistence ------------------------------------------------------

    def finish_run(self) -> dict:
        """Call once at the end of a run. Writes everything to disk and
        returns a summary dict describing what changed."""
        summary = {
            "new": [e for e in self.run_events if e["status"] == "new"],
            "updated": [e for e in self.run_events if e["status"] == "updated"],
            "removed": [e for e in self.run_events if e["status"] == "removed"],
            "unchanged_count": len(self.seen_urls) - len(
                [e for e in self.run_events if e["status"] in ("new", "updated")]
            ),
            "run_at": _now(),
        }
        if summary["new"] or summary["updated"] or summary["removed"]:
            self.changelog.append(summary)

        self.last_run = _now()
        save_json(STATE_FILE, {"pages": self.pages, "last_run": self.last_run})
        save_json(CACHE_FILE, self.content_cache)
        save_json(CHANGELOG_FILE, self.changelog)
        return summary
