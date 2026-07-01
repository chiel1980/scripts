#!/usr/bin/env python3
"""
generate_site.py
=================
Builds a dark-themed, responsive static site from
https://thatspecificsound.wordpress.com, with WordPress.com and Facebook
references stripped out.

Run it again any time: it only re-fetches pages that changed on the
source (via conditional GET + content hashing), records what changed in
data/changelog.json / output/changes.html, and always re-renders the
templates so design changes show up immediately.

Usage:
    python generate_site.py                  # scrape + build
    python generate_site.py --validate        # also run W3C validation
    python generate_site.py --no-scrape       # rebuild from cache only
    python generate_site.py --force           # ignore caches, re-fetch everything
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sitegen import scraper, builder
from bs4 import BeautifulSoup
from sitegen.state import ScrapeState

BASE_URL = scraper.BASE_URL
OUTPUT_DIR = ROOT / "output"


def scrape(state: ScrapeState, fetcher: scraper.Fetcher, force: bool) -> None:
    """Discover + fetch every page, updating `state` in place."""

    def fetch_and_record(url: str, page_type: str, parse_fn):
        cache_headers = {} if force else state.get_cache_headers(url)
        status, html, new_cache, err = fetcher.get(url, cache_headers)

        if status == "error":
            print(f"  ! failed to fetch {url}: {err}")
            cached = state.get_cached_content(url)
            if cached:
                state.record_unchanged(url)
            return cached

        if status == "unchanged":
            print(f"  = unchanged: {url}")
            state.record_unchanged(url)
            return state.get_cached_content(url)

        # status == "new": we got HTML, but it might still be byte-identical
        # to what we had (servers don't always send useful ETags) - check
        # the content hash too before treating it as a real change.
        chash = scraper.content_hash(html)
        prev_hash = state.get_content_hash(url)
        parsed = parse_fn(html, url)
        title = parsed.get("title", url)

        if prev_hash == chash:
            print(f"  = unchanged (same content): {url}")
            state.record_page(
                url,
                page_type=page_type,
                title=title,
                content_hash=chash,
                cache_headers=new_cache,
                parsed_content=parsed,
                status="unchanged",
            )
            return parsed

        is_new = prev_hash is None
        print(f"  + {'new' if is_new else 'updated'}: {title}  ({url})")
        state.record_page(
            url,
            page_type=page_type,
            title=title,
            content_hash=chash,
            cache_headers=new_cache,
            parsed_content=parsed,
            status="updated",
        )
        return parsed

    print(f"Scraping {BASE_URL} ...")

    fetch_and_record(BASE_URL + "/", "home", lambda h, u: scraper.parse_home(h))
    fetch_and_record(BASE_URL + "/about/", "about", lambda h, u: scraper.parse_about(h))

    # Discover interviews from the index, REST API and sitemap. This catches
    # older interviews and future additions even if WordPress removes them
    # from the visible archive page.
    discovered = set()

    interviews_index_url = BASE_URL + "/interviews/"
    index_data = fetch_and_record(
        interviews_index_url, "interviews_index", lambda h, u: scraper.parse_interviews_index(h)
    )

    if index_data:
        for entry in index_data.get("entries", []):
            if entry.get("url"):
                discovered.add(entry["url"])

    discovered.update(scraper.discover_wordpress_content(fetcher))

    # Extra interview crawl: download every linked interview page separately.
    # Some WordPress interview pages are not returned by the REST API and
    # some older pages are only reachable through archive links.
    archive_urls = scraper.discover_interview_links(fetcher, interviews_index_url)
    discovered.update(archive_urls)

    print(f"  Found {len(discovered)} individual pages to process")

    for url in sorted(discovered):
        if not url.startswith(BASE_URL):
            continue

        # Automatically identify interview pages instead of relying only on URL paths
        status, html, cache, err = fetcher.get(url, state.get_cache_headers(url))
        if status == "error":
            print(f"  ! failed discovery fetch {url}: {err}")
            continue
        if status == "unchanged":
            state.record_unchanged(url)
            continue

        parsed = scraper.parse_interview(html, url)
        if not parsed.get("qa"):
            parsed = {
                "type": "article",
                "title": scraper.page_title(BeautifulSoup(html, "html.parser")),
                "url": url,
                "content": scraper.clean_html(html),
            }

        state.record_page(
            url,
            page_type=parsed["type"],
            title=parsed.get("title", url),
            content_hash=scraper.content_hash(str(parsed)),
            cache_headers=cache,
            parsed_content=parsed,
            status="updated",
        )

    # Anything previously scraped but no longer linked from the interviews
    # index (or home/about, which can't disappear) is "removed".
    removed = state.detect_removed()
    for r in removed:
        print(f"  - removed: {r}")


def write_changelog_markdown(state: ScrapeState) -> None:
    lines = ["# Changelog\n", "Generated automatically by generate_site.py.\n"]
    for run in reversed(state.changelog):
        lines.append(f"\n## {run['run_at']}\n")
        for key, label in (("new", "New"), ("updated", "Updated"), ("removed", "Removed")):
            items = run.get(key) or []
            if items:
                lines.append(f"\n**{label}:**\n")
                for e in items:
                    lines.append(f"- {e['title']}\n")
    (ROOT / "CHANGELOG.md").write_text("".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--validate", action="store_true", help="run the generated HTML through the W3C Nu validator")
    ap.add_argument("--no-scrape", action="store_true", help="skip scraping, rebuild from the existing cache only")
    ap.add_argument("--force", action="store_true", help="ignore ETag/Last-Modified caches and re-fetch every page")
    ap.add_argument("--output", default=str(OUTPUT_DIR), help="output directory for the generated site")
    args = ap.parse_args()

    output_dir = Path(args.output)
    state = ScrapeState()
    fetcher = scraper.Fetcher()

    if not args.no_scrape:
        scrape(state, fetcher, force=args.force)
    else:
        print("Skipping scrape, using cached content only.")

    summary = state.finish_run()
    write_changelog_markdown(state)

    print("\nBuilding site ...")
    builder.build_site(state, output_dir, fetcher)
    print(f"Site written to {output_dir}/")

    n_new, n_upd, n_rem = len(summary["new"]), len(summary["updated"]), len(summary["removed"])
    print(f"\nSummary: {n_new} new, {n_upd} updated, {n_rem} removed, {summary['unchanged_count']} unchanged.")

    if args.validate:
        print("\nValidating against the W3C Nu Html Checker (validator.w3.org) ...")
        from sitegen import validator

        results = validator.validate_site(output_dir)
        files_with_errors, total_errors, total_warnings = validator.summarize(results)
        unreachable = sum(1 for r in results if r.get("unreachable"))
        if unreachable:
            print(f"\n{unreachable} file(s) could not be validated (no internet access to validator.w3.org).")
        if total_errors == 0 and unreachable == 0:
            print(f"\nAll {len(results)} pages are W3C valid (0 errors, {total_warnings} warning(s) total).")
        elif total_errors:
            print(f"\n{files_with_errors} file(s) have a total of {total_errors} validation error(s). See details above.")

        import json

        (ROOT / "data" / "validation_report.json").write_text(
            json.dumps(results, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
