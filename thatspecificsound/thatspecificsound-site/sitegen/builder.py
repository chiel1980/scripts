"""
builder.py
----------
Renders the cleaned, structured content (from content_cache.json) into a
static, responsive, dark-themed HTML site using Jinja2 templates.

The whole site is re-rendered every run (it's cheap and keeps templates
and re-themes in sync everywhere); only the *scraping/downloading* step
upstream is incremental.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .assets import ensure_image, local_image_path
from .scraper import Fetcher, slug_from_url, BASE_URL

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"

LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def linkify(text: str) -> str:
    """Turns our internal [label](url) markers into safe <a> tags.
    Runs *after* Jinja's autoescaping by being marked safe at call sites
    that already escaped the surrounding text manually."""
    from markupsafe import Markup, escape

    out = []
    pos = 0
    for m in LINK_PATTERN.finditer(text):
        out.append(escape(text[pos : m.start()]))
        label, href = m.group(1), m.group(2)
        external = href.startswith("http") and "thatspecificsound" not in href
        rel = ' rel="noopener noreferrer" target="_blank"' if external else ""
        out.append(Markup(f'<a href="{escape(href)}"{rel}>{escape(label)}</a>'))
        pos = m.end()
    out.append(escape(text[pos:]))
    return Markup("").join(out)


def get_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["linkify"] = linkify
    env.globals["changelog_entry_href"] = changelog_entry_href
    return env



def fix_asset_paths(html):
    """Fix all absolute asset references for pages inside /interviews/."""
    replacements = {
        'src="/assets/': 'src="../assets/',
        'src=\'/assets/': "src='../assets/",
        'href="/assets/': 'href="../assets/',
        'href=\'/assets/': "href='../assets/",
        'srcset="/assets/': 'srcset="../assets/',
        'srcset=\'/assets/': "srcset='../assets/",
    }
    for a,b in replacements.items():
        html = html.replace(a,b)
    return html


def localize_inline_images(blocks: list[dict], images_dir: Path, fetcher: Fetcher) -> None:
    """Downloads every inline "image" block's photo into assets/images/
    and records the local path on the block for the template to use."""
    for b in blocks:
        if b.get("kind") == "image":
            b["local_src"] = ensure_image(b.get("src"), images_dir, fetcher)


def resolve_source_link(url: str, interviews: list) -> str | None:
    """Maps a URL on the source site back to the corresponding local page,
    so inline links in scraped body text (e.g. "Check the Interviews
    section...", "See the About page...") point at this archive's own
    pages instead of sending readers back out to the original WordPress
    site. Returns None for anything that isn't one of our own pages
    (external links, or a source URL we don't recognize), in which case
    the caller should leave the link pointing at the source as a safe
    fallback rather than risk producing a broken local link."""
    if not url:
        return None
    normalized = url.rstrip("/")
    base = BASE_URL.rstrip("/")
    if normalized == base:
        return "index.html"
    if normalized == base + "/about":
        return "about.html"
    if normalized == base + "/interviews":
        return "interviews/index.html"
    for iv in interviews:
        if iv.get("url", "").rstrip("/") == normalized:
            return f"interviews/{iv['filename']}"
    return None


def localize_body_links(paragraphs: list, interviews: list) -> list:
    """Rewrites the href half of every [label](url) marker in a list of
    paragraphs (see resolve_source_link) in place, returning a new list."""

    def _rewrite(m: "re.Match") -> str:
        label, href = m.group(1), m.group(2)
        local = resolve_source_link(href, interviews)
        return f"[{label}]({local})" if local else m.group(0)

    return [LINK_PATTERN.sub(_rewrite, p) for p in paragraphs]


def changelog_entry_href(entry: dict) -> str | None:
    """Maps a changelog entry back to the local page it corresponds to,
    so change-log listings can link straight to the page. Returns None
    for entries with no page to link to (e.g. removed pages)."""
    if entry.get("status") == "removed":
        return None
    page_type = entry.get("type")
    if page_type == "home":
        return "index.html"
    if page_type == "about":
        return "about.html"
    if page_type == "interviews_index":
        return "interviews/index.html"
    if page_type == "interview":
        return f"interviews/{slug_from_url(entry['url'])}.html"
    return None


def build_site(state, output_dir: Path, fetcher: Fetcher) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    env = get_env()
    images_dir = output_dir / "assets" / "images"

    pages = state.content_cache  # url -> parsed dict
    home = next((p for p in pages.values() if p.get("type") == "home"), None)
    about = next((p for p in pages.values() if p.get("type") == "about"), None)
    interviews_index = next((p for p in pages.values() if p.get("type") == "interviews_index"), None)
    interviews = sorted(
        (p for p in pages.values() if p.get("type") == "interview"),
        key=lambda p: p.get("title", ""),
    )

    for iv in interviews:
        iv["slug"] = slug_from_url(iv["url"])
        iv["filename"] = iv["slug"] + ".html"
        iv["hero_image_local"] = ensure_image(iv.get("hero_image"), images_dir, fetcher)

        # Download every inline photo embedded in the Q&A body (previously
        # only the hero image was ever fetched, so every other photo in
        # the interview silently disappeared).
        localize_inline_images(iv.get("intro", []), images_dir, fetcher)
        for unit in iv.get("qa", []):
            localize_inline_images(unit.get("answers", []), images_dir, fetcher)

        # Download and rewrite every image inside interview content
        if iv.get("full_html"):
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(iv["full_html"], "html.parser")
            for img in soup.find_all("img", src=True):
                local = ensure_image(img["src"], images_dir, fetcher)
                if local:
                    img["src"] = "../" + local if not local.startswith("../") else local

            for source in soup.find_all("source", srcset=True):
                parts = []
                for item in source["srcset"].split(","):
                    url = item.strip().split(" ")[0]
                    local = ensure_image(url, images_dir, fetcher)
                    if local:
                        item = item.replace(url, "../" + local if not local.startswith("../") else local)
                    parts.append(item)
                source["srcset"] = ", ".join(parts)

            iv["full_html"] = fix_asset_paths(str(soup))

    nav = [
        {"label": "Home", "href": "index.html"},
        {"label": "Interviews", "href": "interviews/index.html"},
        {"label": "About", "href": "about.html"},
        {"label": "Changes", "href": "changes.html"},
    ]

    common = {
        "nav": nav,
        "site_title": "That Specific Sound",
        "site_tagline": (home or {}).get(
            "tagline",
            "The gear and rigs behind hardcore and metal's most distinctive guitar tones.",
        ),
        "generated_at": datetime.now().strftime("%-d %B %Y"),
    }

    # ---- home ----
    home_page = dict(home) if home else {}
    if home_page.get("paragraphs"):
        home_page["paragraphs"] = localize_body_links(home_page["paragraphs"], interviews)
    (output_dir / "index.html").write_text(
        env.get_template("home.html").render(
            **common, page=home_page, interviews=interviews[:6], active="Home"
        ),
        encoding="utf-8",
    )

    # ---- about ----
    if about:
        (output_dir / "about.html").write_text(
            env.get_template("about.html").render(**common, page=about, active="About"),
            encoding="utf-8",
        )
    else:
        print(
            "  ! WARNING: no page with type 'about' found in the content cache -- "
            "about.html was NOT written to the output. Run with --force to re-fetch "
            "https://thatspecificsound.wordpress.com/about/ from scratch."
        )

    # ---- interviews index ----
    interviews_dir = output_dir / "interviews"
    interviews_dir.mkdir(exist_ok=True)
    (interviews_dir / "index.html").write_text(
        env.get_template("interviews.html").render(
            **common,
            page=interviews_index or {},
            interviews=interviews,
            active="Interviews",
            path_prefix="../",
        ),
        encoding="utf-8",
    )

    # ---- individual interviews ----
    for iv in interviews:
        (interviews_dir / f"{iv['slug']}.html").write_text(
            env.get_template("interview.html").render(
                **common, page=iv, active="Interviews", path_prefix="../"
            ),
            encoding="utf-8",
        )

    # ---- changelog page ----
    (output_dir / "changes.html").write_text(
        env.get_template("changes.html").render(
            **common, changelog=list(reversed(state.changelog)), active="Changes"
        ),
        encoding="utf-8",
    )

    # ---- static assets (css/js) ----
    out_static = output_dir / "static"
    if out_static.exists():
        shutil.rmtree(out_static)
    shutil.copytree(STATIC_DIR, out_static)
