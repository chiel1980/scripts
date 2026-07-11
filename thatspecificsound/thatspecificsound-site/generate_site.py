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
    python generate_site.py --check-deps      # only check system packages, then exit

On every run the script does a quick, best-effort check for its
dependencies -- python3 itself, and the requests/beautifulsoup4/jinja2
libraries -- preferring your distro's own packaged versions over pip, and
prints the right install command for Debian/Ubuntu (apt) or Arch
Linux/CachyOS (pacman) if anything looks missing. This is advisory only --
it never blocks a run. If you'd rather use pip/venv instead of distro
packages, that still works fine (see README).
"""
from __future__ import annotations

import argparse
import importlib.util
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sitegen import scraper, builder
from bs4 import BeautifulSoup
from sitegen.state import ScrapeState

BASE_URL = scraper.BASE_URL
OUTPUT_DIR = ROOT / "output"

# Distro-packaged names for everything this script needs, so people can
# install with their system package manager instead of pip/venv.
# Keyed by the Python import name each dependency maps to.
_DISTRO_PACKAGES = {
    "debian": {
        "label": "Debian / Ubuntu (and derivatives)",
        "manager": "apt",
        "packages": {
            "requests": "python3-requests",
            "bs4": "python3-bs4",
            "jinja2": "python3-jinja2",
            "cv2": "python3-opencv",
            "java": "default-jre",
        },
        "install_cmd": "sudo apt update && sudo apt install {pkgs}",
    },
    "arch": {
        "label": "Arch Linux / CachyOS (and derivatives)",
        "manager": "pacman",
        "packages": {
            "requests": "python-requests",
            "bs4": "python-beautifulsoup4",
            "jinja2": "python-jinja",
            "cv2": "python-opencv",
            "java": "jdk-openjdk",
        },
        "install_cmd": "sudo pacman -S {pkgs}",
    },
}


def _detect_distro() -> str:
    """Best-effort Linux distro family detection via /etc/os-release.

    Returns "debian", "arch", or a fallback string (e.g. "darwin",
    "windows", or the raw distro ID if it's a Linux flavor we don't have
    a package mapping for).
    """
    os_release = Path("/etc/os-release")
    if not os_release.exists():
        return platform.system().lower()

    fields: dict[str, str] = {}
    for line in os_release.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key] = value.strip().strip('"')

    ident = fields.get("ID", "").lower()
    like = fields.get("ID_LIKE", "").lower()

    if ident in ("debian", "ubuntu") or "debian" in like:
        return "debian"
    if ident in ("arch", "cachyos", "manjaro", "endeavouros") or "arch" in like:
        return "arch"
    return ident or "unknown"


def check_system_requirements(want_validate: bool = False) -> bool:
    """Print a heads-up (with a copy-pasteable distro install command) for
    any missing dependency -- checking for the library itself (however it
    got installed: distro package, pip, venv, ...) rather than assuming
    any particular install method. Advisory only -- does not exit/raise.
    Returns True if everything looks present.
    """
    distro = _detect_distro()
    dmeta = _DISTRO_PACKAGES.get(distro)

    missing_import_names = []

    if shutil.which("python3") is None:
        # No python3 binary at all -- can't even map a package name usefully
        # without knowing the distro's naming, so just flag it plainly.
        print("Heads up -- python3 was not found on PATH.")
        if dmeta:
            print(f"Detected: {dmeta['label']}\nInstall with:\n  sudo {dmeta['manager']} install python3"
                  if dmeta["manager"] == "apt" else f"Detected: {dmeta['label']}\nInstall with:\n  sudo pacman -S python")
        return False

    for import_name in ("requests", "bs4", "jinja2"):
        if importlib.util.find_spec(import_name) is None:
            missing_import_names.append(import_name)

    if want_validate and shutil.which("java") is None:
        missing_import_names.append("java")

    if not missing_import_names:
        print("System requirements look OK (requests, bs4, jinja2"
              + (", java" if want_validate else "") + ").")
        if importlib.util.find_spec("cv2") is None:
            print(
                "Note: OpenCV isn't installed, so hero photos will use a "
                "fixed crop position instead of per-photo face detection. "
                "Not required, but improves photo cropping."
            )
            if dmeta and "cv2" in dmeta["packages"]:
                cmd = dmeta["install_cmd"].format(pkgs=dmeta["packages"]["cv2"])
                print(f"Install with your distro's packages:\n  {cmd}")
                print("(Or, if you prefer pip/venv instead: pip install opencv-python-headless)")
            else:
                print("Install with: pip install opencv-python-headless")
        return True

    print("Heads up -- some dependencies look missing:")
    for name in missing_import_names:
        print(f"  - {name}")

    if dmeta:
        pkgs = [dmeta["packages"][name] for name in missing_import_names if name in dmeta["packages"]]
        cmd = dmeta["install_cmd"].format(pkgs=" ".join(pkgs))
        print(f"\nDetected: {dmeta['label']}\nInstall with your distro's packages:\n  {cmd}")
        print("(Or, if you prefer pip/venv instead: pip install -r requirements.txt)")
    else:
        print(
            "\nCouldn't confidently detect your distro as Debian/Ubuntu or "
            "Arch/CachyOS -- install the equivalent packages via your "
            "package manager, or fall back to: pip install -r requirements.txt"
        )
    print()
    return False


def scrape(state: ScrapeState, fetcher: scraper.Fetcher, force: bool) -> None:
    """Discover + fetch every page, updating `state` in place."""

    def fetch_and_record(url: str, page_type: str, parse_fn):
        # A page whose cached parse predates the current PARSER_VERSION
        # needs reparsing even if nothing changed upstream -- so treat it
        # like --force for this one URL by withholding the ETag/
        # Last-Modified headers, which guarantees a real 200 + full HTML
        # body to reparse instead of a 304 that would just hand back the
        # stale cached blocks again.
        stale_parse = state.get_parser_version(url) != scraper.PARSER_VERSION
        cache_headers = {} if (force or stale_parse) else state.get_cache_headers(url)
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

        # status == "new": we got HTML, but it might still be unchanged in
        # any way that matters. Comparing raw HTML bytes isn't reliable for
        # that -- WordPress.com pages embed things like nonces, stats/ad
        # pixels, and randomized "related posts" widgets that change on
        # every single request even when the actual page content hasn't
        # changed at all. That was making home/about/interviews-index show
        # up as "updated" on every rebuild. Parsing first and hashing the
        # *parsed* content sidesteps that, since parse_fn already strips
        # all of that WordPress/Jetpack chrome out.
        parsed = parse_fn(html, url)
        title = parsed.get("title", url)
        chash = scraper.content_hash(str(parsed))
        prev_hash = state.get_content_hash(url)

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
                parser_version=scraper.PARSER_VERSION,
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
            parser_version=scraper.PARSER_VERSION,
        )
        return parsed

    print(f"Scraping {BASE_URL} ...")

    # URLs handled explicitly above/below (home, about, interviews index)
    # must never be re-processed by the generic discovery loop -- WordPress's
    # own REST API (/wp-json/wp/v2/pages) and sitemap.xml both list these
    # same URLs, and re-parsing them with parse_interview() would silently
    # overwrite their correct page_type ("about", etc.) with a generic
    # "article", which then made about.html vanish from the build with no
    # error anywhere.
    explicit_urls = {
        (BASE_URL + "/").rstrip("/") + "/",
        (BASE_URL + "/about/").rstrip("/") + "/",
        (BASE_URL + "/interviews/").rstrip("/") + "/",
    }

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

    # Drop anything that maps to a URL we already scraped explicitly above,
    # so the generic "article" fallback below can never clobber home/about/
    # interviews_index in the content cache.
    discovered = {u for u in discovered if u.rstrip("/") + "/" not in explicit_urls}

    print(f"  Found {len(discovered)} individual pages to process")

    for url in sorted(discovered):
        if not scraper.is_same_site(url):
            print(f"  ~ skipping (not same site): {url}")
            continue

        # Automatically identify interview pages instead of relying only on URL paths
        stale_parse = state.get_parser_version(url) != scraper.PARSER_VERSION
        cache_headers = {} if (force or stale_parse) else state.get_cache_headers(url)
        status, html, cache, err = fetcher.get(url, cache_headers)
        if status == "error":
            print(f"  ! failed discovery fetch {url}: {err}")
            # A failed request here does NOT mean the page was removed from
            # the source -- it just means *this run* couldn't reach it. But
            # detect_removed() at the end of scrape() deletes anything not
            # marked "seen" this run, so without this fallback a single
            # flaky/rate-limited request would silently and permanently wipe
            # a perfectly good interview out of data/content_cache.json (and
            # therefore out of the built site) even though nothing actually
            # changed on WordPress. Falling back to whatever we already have
            # cached, and marking the URL seen, keeps a transient failure
            # from ever being indistinguishable from a real deletion.
            if state.get_cached_content(url):
                state.record_unchanged(url)
            continue
        if status == "unchanged":
            print(f"  = 304 not modified (server-side cache, still trusted): {url}")
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

        # A 200 response here doesn't necessarily mean the content actually
        # changed (WordPress doesn't always send useful ETags), so compare
        # against the previously stored hash the same way fetch_and_record()
        # does above. Without this, every page discovered through this loop
        # -- i.e. every interview -- got unconditionally marked "updated" on
        # every single run, even when nothing had changed on the source.
        # That flooded data/changelog.json (and therefore changes.html) with
        # a near-complete "Updated" listing of the whole site on every
        # rebuild, which read as if the archive was reorganizing itself
        # instead of just picking up real changes.
        chash = scraper.content_hash(str(parsed))
        prev_hash = state.get_content_hash(url)
        page_status = "unchanged" if prev_hash == chash else "updated"
        title = parsed.get("title", url)
        reason = " (parser version bumped, forced reparse)" if stale_parse and not force else ""
        print(f"  {'=' if page_status == 'unchanged' else '+'} {page_status}: {title}{reason}  ({url})")

        state.record_page(
            url,
            page_type=parsed["type"],
            title=parsed.get("title", url),
            content_hash=chash,
            cache_headers=cache,
            parsed_content=parsed,
            status=page_status,
            parser_version=scraper.PARSER_VERSION,
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
    ap.add_argument(
        "--check-deps",
        action="store_true",
        help="only check for required system packages (python3/pip/venv, java for --validate), then exit",
    )
    args = ap.parse_args()

    if args.check_deps:
        check_system_requirements(want_validate=True)
        return

    check_system_requirements(want_validate=args.validate)

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
