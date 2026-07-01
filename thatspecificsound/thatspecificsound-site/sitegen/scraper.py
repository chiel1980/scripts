"""
scraper.py
----------
Fetches pages from the source WordPress.com site and parses the
"Archivist" theme markup into plain structured data (dicts / lists of
strings), with no WordPress- or Facebook-specific markup surviving.

Networking uses conditional GET (If-None-Match / If-Modified-Since) so
that re-running the script does not re-download pages that have not
changed on the source since the last run.
"""
from __future__ import annotations

import hashlib
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

BASE_URL = "https://thatspecificsound.wordpress.com"
USER_AGENT = (
    "ThatSpecificSoundArchiver/1.0 "
    "(+static site generator; respectful crawl, low frequency)"
)
REQUEST_DELAY = 1.0  # seconds between requests, be polite to the source site


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Fetcher:
    """Thin wrapper around requests with conditional GET + rate limiting."""

    def __init__(self, delay: float = REQUEST_DELAY):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.delay = delay
        self._last_request = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def get(self, url: str, cache_headers: dict | None = None, timeout: int = 20):
        """Returns (status, html, new_cache_headers).
        status is one of: 'new', 'unchanged', 'error'
        """
        headers = {}
        if cache_headers:
            if cache_headers.get("etag"):
                headers["If-None-Match"] = cache_headers["etag"]
            if cache_headers.get("last_modified"):
                headers["If-Modified-Since"] = cache_headers["last_modified"]

        self._throttle()
        try:
            resp = self.session.get(url, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            return "error", None, cache_headers or {}, str(exc)
        finally:
            self._last_request = time.time()

        if resp.status_code == 304:
            return "unchanged", None, cache_headers or {}, None
        if resp.status_code != 200:
            return "error", None, cache_headers or {}, f"HTTP {resp.status_code}"

        new_cache = {
            "etag": resp.headers.get("ETag"),
            "last_modified": resp.headers.get("Last-Modified"),
        }
        return "new", resp.text, new_cache, None

    def download_binary(self, url: str, timeout: int = 30) -> bytes | None:
        self._throttle()
        try:
            resp = self.session.get(url, timeout=timeout)
            self._last_request = time.time()
            if resp.status_code == 200:
                return resp.content
        except requests.RequestException:
            pass
        return None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

# Anything under these hosts/paths is WordPress.com or Facebook plumbing
# and must never survive into the generated site.
# Anything under these hosts/paths is WordPress.com or Facebook plumbing
# and must never survive into the generated site. The source site itself
# (thatspecificsound.wordpress.com) is *not* blocked - those are normal
# internal links we want to keep (rewritten to local pages later).
BLOCKED_HOSTS = (
    "wordpress.com",
    "wp.me",
    "facebook.com",
    "automattic.com",
    "gravatar.com",
    "pixel.wp.com",
    "stats.wp.com",
    "jetpack.com",
)
SOURCE_HOST = urlparse(BASE_URL).netloc  # thatspecificsound.wordpress.com


def is_blocked_url(url: str) -> bool:
    if not url:
        return False
    host = urlparse(url, scheme="https").netloc
    if not host:
        # relative URL (e.g. "#") - never blocked, handled elsewhere
        return False
    if host == SOURCE_HOST:
        return False
    return any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS)


def find_main_content(soup: BeautifulSoup) -> Tag | None:
    """Locate the WordPress 'Archivist' theme's article body."""
    for selector in (
        "article .entry-content",
        ".entry-content",
        "article",
        "main",
    ):
        node = soup.select_one(selector)
        if node:
            return node
    return None


def page_title(soup: BeautifulSoup) -> str:
    h1 = soup.select_one("article h1.entry-title") or soup.select_one("h1")
    if h1:
        return clean_text(h1.get_text(" ", strip=True))
    if soup.title:
        return clean_text(soup.title.get_text().split("–")[0])
    return "Untitled"


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def slug_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    return path.split("/")[-1] if path else "index"


def absolutize(url: str | None) -> str | None:
    if not url:
        return None
    return urljoin(BASE_URL, url)


def strip_wp_chrome(node: Tag) -> None:
    """Remove WordPress/Facebook navigation, tracking and marketing chrome
    from a parsed content node, in place."""
    if node is None:
        return

    # Remove elements linking to blocked hosts (sign up / log in / report /
    # subscribe / "Blog at WordPress.com" / Facebook publisher links, etc).
    for a in node.find_all("a", href=True):
        if is_blocked_url(a["href"]):
            # If the link is the only thing in its parent <p>/<li>, drop the
            # whole parent; otherwise just unwrap the anchor.
            parent = a.parent
            if parent and parent.name in ("p", "li") and parent.get_text(strip=True) == a.get_text(strip=True):
                parent.decompose()
            else:
                a.decompose()

    # Tracking pixels / blavatar images
    for img in node.find_all("img", src=True):
        if is_blocked_url(img["src"]):
            img.decompose()

    # Comment forms / "Loading Comments" / login-to-comment widgets
    for el in node.select("#comments, .comments-area, .jetpack-comment-likes"):
        el.decompose()


# ---------------------------------------------------------------------------
# Page-specific parsers -> plain dict output (no soup objects survive)
# ---------------------------------------------------------------------------


def discover_wordpress_content(fetcher):
    """Discover posts/pages/interviews through WordPress APIs and sitemap."""
    found = set()

    for endpoint in ("/wp-json/wp/v2/posts", "/wp-json/wp/v2/pages"):
        page = 1
        while True:
            status, html, _, _ = fetcher.get(BASE_URL + endpoint + f"?per_page=100&page={page}")
            if status != "new" or not html:
                break
            try:
                import json
                for item in json.loads(html):
                    if item.get("link"):
                        found.add(item["link"])
            except Exception:
                break
            page += 1

    try:
        status, html, _, _ = fetcher.get(BASE_URL + "/sitemap.xml")
        if status == "new" and html:
            soup = BeautifulSoup(html, "xml")
            for loc in soup.find_all("loc"):
                url = loc.text.strip()
                if url.startswith(BASE_URL):
                    found.add(url)
    except Exception:
        pass

    return found



def discover_interview_links(fetcher, start_url):
    """Crawl interview archive pages and collect every interview URL."""
    found = set()
    queue = [start_url]
    seen = set()

    while queue:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)

        status, html, _, _ = fetcher.get(url)
        if status != "new" or not html:
            continue

        soup = BeautifulSoup(html, "html.parser")

        for a in soup.find_all("a", href=True):
            href = absolutize(a["href"])
            if not href or not href.startswith(BASE_URL):
                continue

            path = urlparse(href).path.lower()

            # Collect individual interviews
            if "/interview" in path and href.rstrip("/") != start_url.rstrip("/"):
                found.add(href)

            # Follow pagination/archive pages
            if "interview" in path and href not in seen:
                if href not in queue:
                    queue.append(href)

    return found

def parse_home(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    content = find_main_content(soup)
    strip_wp_chrome(content)

    tagline_el = soup.select_one(".site-description, .tagline")
    tagline = clean_text(tagline_el.get_text(" ", strip=True)) if tagline_el else ""

    paragraphs = []
    links = {}
    if content:
        for p in content.find_all("p"):
            txt = clean_text(p.get_text(" ", strip=True))
            if not txt:
                continue
            paragraphs.append(txt)
        for a in content.find_all("a", href=True):
            href = absolutize(a["href"])
            if href and href.startswith(BASE_URL):
                label = clean_text(a.get_text(" ", strip=True))
                if label:
                    links[label] = href

    return {
        "type": "home",
        "title": "That Specific Sound",
        "tagline": tagline,
        "paragraphs": paragraphs,
        "links": links,
    }


def parse_about(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    content = find_main_content(soup)
    strip_wp_chrome(content)
    title = page_title(soup)

    paragraphs = []
    if content:
        for p in content.find_all("p"):
            txt = clean_text(p.get_text(" ", strip=True))
            if txt:
                paragraphs.append(txt)

    return {"type": "about", "title": title, "paragraphs": paragraphs}


def parse_interviews_index(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    content = find_main_content(soup)
    strip_wp_chrome(content)
    title = page_title(soup)

    intro = []
    entries = []
    if content:
        for el in content.children:
            if isinstance(el, NavigableString):
                continue
            if el.name == "ul":
                for li in el.find_all("li", recursive=False):
                    a = li.find("a", href=True)
                    if a:
                        entries.append(
                            {
                                "title": clean_text(a.get_text(" ", strip=True)).lstrip("\u2013- "),
                                "url": absolutize(a["href"]),
                            }
                        )
            elif el.name == "p":
                txt = clean_text(el.get_text(" ", strip=True))
                a = el.find("a", href=True)
                if a and txt.lstrip("\u2013- ").startswith(clean_text(a.get_text(" ", strip=True))):
                    entries.append(
                        {
                            "title": clean_text(a.get_text(" ", strip=True)),
                            "url": absolutize(a["href"]),
                        }
                    )
                elif txt:
                    intro.append(txt)

    return {"type": "interviews_index", "title": title, "intro": intro, "entries": entries}


def clean_html(html: str) -> str:
    """Remove scripts, tracking, and WordPress/Facebook references."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    for tag in soup.find_all(href=True):
        href = tag.get("href", "")
        if "wordpress.com" in href or "facebook.com" in href:
            tag.decompose()

    for text in soup.find_all(string=True):
        if text.parent.name not in ["script", "style"]:
            text.replace_with(
                text.replace("WordPress", "")
                    .replace("Facebook", "")
            )

    return str(soup)


def parse_interview(html: str, url: str) -> dict:
    """Parse complete interviews.

    The original parser only looked at direct children of the article body.
    Many WordPress interview pages wrap questions/answers inside divs,
    blockquotes, headings or nested paragraphs. This version flattens the
    article content while preserving images, lists and Q&A structure.
    """
    soup = BeautifulSoup(html, "html.parser")
    content = find_main_content(soup)
    strip_wp_chrome(content)
    title = page_title(soup)

    hero_image = None
    if content:
        img = content.find("img")
        if img and img.get("src") and not is_blocked_url(img["src"]):
            hero_image = absolutize(img["src"])

    meta = soup.select_one('meta[property="og:image"]')
    if not hero_image and meta and meta.get("content"):
        hero_image = absolutize(meta["content"])

    blocks=[]
    photo_credit=None

    if content:
        for el in content.find_all(["p","h2","h3","li","blockquote"], recursive=True):
            text=clean_text(el.get_text(" ", strip=True))
            if not text:
                continue

            lower=text.lower()
            if lower.startswith("photo credit"):
                photo_credit=text
                continue

            # Questions are normally bold, uppercase, or end with ?
            strong=el.find("strong")
            is_question=(
                bool(strong)
                and clean_text(strong.get_text(" ", strip=True)) == text
            ) or text.endswith("?")

            if is_question:
                blocks.append({"kind":"question","text":text})
            else:
                blocks.append({"kind":"answer","text":text})

    qa=[]
    intro=[]
    current=None

    for b in blocks:
        if b["kind"]=="question":
            current={"question":b["text"],"answers":[]}
            qa.append(current)
        elif current:
            current["answers"].append(b)
        else:
            intro.append(b)

    # If this is a long article without obvious Q&A, still preserve it as an
    # interview/article instead of losing content.
    if not qa:
        intro = blocks

    return {
        "type":"interview" if qa else "article",
        "title":title,
        "url":url,
        "hero_image":hero_image,
        "photo_credit":photo_credit,
        "intro":intro,
        "qa":qa,
        "outro":[],
        "full_html": clean_html(str(content)) if content else ""
    }


def strip_inline_links(el: Tag) -> str:
    """Render an element's text with [label](href) markers preserved as
    a simple list the template can turn into real <a> tags, while
    dropping any blocked (WP/FB) links and emoji tracking images. Walks
    the full subtree so links nested inside <em>/<strong> etc. survive."""

    def walk(node) -> str:
        if isinstance(node, NavigableString):
            return str(node)
        if not isinstance(node, Tag):
            return ""
        if node.name == "a" and node.get("href"):
            href = node["href"]
            if is_blocked_url(href):
                return node.get_text(" ", strip=True)
            label = node.get_text(" ", strip=True)
            return f"[{label}]({absolutize(href)})"
        if node.name == "img":
            alt = node.get("alt", "")
            if alt and not is_blocked_url(node.get("src", "")):
                return alt
            return ""
        return "".join(walk(child) for child in node.children)

    return clean_text(walk(el))
