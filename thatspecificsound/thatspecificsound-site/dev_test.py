"""Dev-only harness to exercise the full pipeline offline using the HTML
fixtures in fixtures/, simulating a first run and then a second run with
one new interview + one changed page, to prove incremental tracking works.
Not part of the shipped tool - just used to validate this implementation.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sitegen import scraper, builder
from sitegen.state import ScrapeState

FIXTURES = ROOT / "fixtures"
BASE = scraper.BASE_URL

PAGES = {
    BASE + "/": FIXTURES / "home.html",
    BASE + "/about/": FIXTURES / "about.html",
    BASE + "/interviews/": FIXTURES / "interviews.html",
    BASE + "/interview-scott-crouse-earth-crisis-sect/": FIXTURES / "interview-scott-crouse.html",
    BASE + "/interview-bo-lueders-harms-way/": FIXTURES / "interview-bo-lueders.html",
}


class FakeFetcher(scraper.Fetcher):
    def __init__(self, pages):
        super().__init__(delay=0)
        self.pages = pages
        self.served_etags = {}

    def get(self, url, cache_headers=None, timeout=20):
        path = self.pages.get(url)
        if not path:
            return "error", None, {}, "404 (fixture missing)"
        html = path.read_text(encoding="utf-8")
        etag = f'"{hash(html) & 0xffffffff}"'
        if cache_headers and cache_headers.get("etag") == etag:
            return "unchanged", None, cache_headers, None
        return "new", html, {"etag": etag, "last_modified": None}, None

    def download_binary(self, url, timeout=30):
        return None  # no real network in the test harness


def run(output_dir, pages, label):
    print(f"\n===== {label} =====")
    state = ScrapeState()
    fetcher = FakeFetcher(pages)

    import generate_site as gs

    gs.scrape(state, fetcher, force=False)
    summary = state.finish_run()
    print("summary:", {k: (v if not isinstance(v, list) else [e['title'] for e in v]) for k, v in summary.items()})

    builder.build_site(state, output_dir, fetcher)
    return summary


if __name__ == "__main__":
    out = ROOT / "output"
    if out.exists():
        shutil.rmtree(out)
    data = ROOT / "data"
    if data.exists():
        shutil.rmtree(data)

    run(out, PAGES, "RUN 1 (first build, everything is new)")

    # Run 2: nothing changes -> everything should be reported unchanged.
    run(out, PAGES, "RUN 2 (no changes on source)")

    # Run 3: edit the about page content and add a third interview.
    about2 = FIXTURES / "about2.html"
    about2.write_text(
        (FIXTURES / "about.html").read_text(encoding="utf-8").replace(
            "lifelong love for hardcore and metal bands from the 90s up to today.",
            "lifelong love for hardcore and metal bands from the 90s up to today, especially Earth Crisis.",
        ),
        encoding="utf-8",
    )
    interviews2 = FIXTURES / "interviews2.html"
    interviews2.write_text(
        (FIXTURES / "interviews.html").read_text(encoding="utf-8").replace(
            "More interviews to come",
            '&#8211; <a href="https://thatspecificsound.wordpress.com/interview-third-guitarist/">Third Guitarist &#8211; Some Band</a></p>\n<p>More interviews to come',
        ),
        encoding="utf-8",
    )
    third = FIXTURES / "interview-third.html"
    third.write_text(
        """<!DOCTYPE html><html lang="en-US"><head><meta charset="UTF-8">
<title>Interview - Third Guitarist - That specific sound</title></head><body>
<main id="content"><article><div class="entry-content">
<h1 class="entry-title">Interview - Third Guitarist - Some Band</h1>
<p><strong>What's in your rig?</strong></p>
<p>Just a clean Twin Reverb and a fuzz pedal, kept simple on purpose.</p>
</div></article></main></body></html>""",
        encoding="utf-8",
    )

    pages3 = dict(PAGES)
    pages3[BASE + "/about/"] = about2
    pages3[BASE + "/interviews/"] = interviews2
    pages3[BASE + "/interview-third-guitarist/"] = third

    run(out, pages3, "RUN 3 (about edited + new interview added)")

    print("\nOutput files:")
    for p in sorted(out.rglob("*")):
        if p.is_file():
            print(" ", p.relative_to(out))
