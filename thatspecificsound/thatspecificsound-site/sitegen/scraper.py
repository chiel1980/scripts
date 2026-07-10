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

# Bump this whenever parse_interview()/parse_generic()'s parsing rules
# change in a way that would produce different output for a page whose
# *source* HTML hasn't changed. Pages are only ever reparsed when either
# their source content changes or this version has moved past what's
# recorded in state.json for them -- otherwise an unchanged source page
# just keeps re-serving whatever was parsed under an older, possibly
# buggy, version of this logic forever. See ScrapeState.get_parser_version.
PARSER_VERSION = 3

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
# and must never survive into the generated site. The source site itself
# (thatspecificsound.wordpress.com) is *not* blocked - those are normal
# internal links we want to keep (rewritten to local pages later).
#
# "wordpress.com" is matched *exactly* here, not as a subdomain suffix.
# Automattic's own chrome (the "Blog at WordPress.com" footer, sign-up/
# log-in links, etc.) always points at the bare wordpress.com domain, but
# plenty of legitimate content -- e.g. a photo credit linking to someone
# else's independent archive blog -- lives on a *.wordpress.com subdomain
# too. Blocking the whole suffix silently strips those real credit/source
# links along with the actual chrome, so subdomains are left to be judged
# on their own merits instead. The other hosts here don't have that
# problem (nobody's independent content lives on jetpack.com or
# gravatar.com), so those still block the full suffix.
BLOCKED_HOSTS_EXACT = ("wordpress.com",)
BLOCKED_HOSTS_SUFFIX = (
    "wp.me",
    "facebook.com",
    "automattic.com",
    "gravatar.com",
    "pixel.wp.com",
    "stats.wp.com",
    "jetpack.com",
)
SOURCE_HOST = urlparse(BASE_URL).netloc  # thatspecificsound.wordpress.com


def is_same_site(url: str) -> bool:
    """Whether `url` points at the source site, tolerant of http vs https
    and an optional "www." prefix -- unlike a strict `url.startswith(BASE_URL)`
    check, which silently rejects same-site URLs that differ from BASE_URL
    by only those cosmetic details (e.g. WordPress occasionally emitting
    http:// links, or a www. variant of the host). A rejected URL here
    should always be a genuinely different domain, never our own site
    spelled slightly differently -- so callers can safely drop what this
    returns False for.
    """
    if not url:
        return False
    try:
        host = urlparse(url, scheme="https").netloc.lower()
    except ValueError:
        return False
    if not host:
        return False

    def _norm(h: str) -> str:
        return h[4:] if h.startswith("www.") else h

    return _norm(host) == _norm(SOURCE_HOST)


def is_blocked_url(url: str) -> bool:
    if not url:
        return False
    host = urlparse(url, scheme="https").netloc
    if not host:
        # relative URL (e.g. "#") - never blocked, handled elsewhere
        return False
    if host == SOURCE_HOST:
        return False
    if host in BLOCKED_HOSTS_EXACT:
        return True
    return any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS_SUFFIX)


def is_emoji_image(img: Tag) -> bool:
    """WordPress (and some themes) render emoji as tiny <img> tags via a
    CDN. These aren't real content photos and must never be picked up as
    inline interview images."""
    classes = " ".join(img.get("class") or []).lower()
    if "emoji" in classes:
        return True
    src = (img.get("src") or "").lower()
    return "notoemoji" in src or "s.w.org/images/core/emoji" in src


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
        _collect_sitemap_urls(fetcher, BASE_URL + "/sitemap.xml", found, set())
    except Exception:
        pass

    return found


def _collect_sitemap_urls(fetcher, sitemap_url: str, found: set, seen_sitemaps: set) -> None:
    """Fetches a sitemap and adds real page URLs to `found`.

    WordPress.com's top-level /sitemap.xml is normally a *sitemap index*
    (a <sitemapindex> of <sitemap><loc> entries pointing at other sitemap
    files - e.g. wp-sitemap-posts-post-1.xml, wp-sitemap-taxonomies-
    category-1.xml - each of which is itself a <urlset> of <url><loc>
    entries for actual pages). Both levels use the same <loc> tag name,
    so naively collecting every <loc> in the top-level document treats
    the *sub-sitemap files themselves* as if they were content pages:
    they get fetched and parsed as articles, which produces "Untitled"
    entries in the changelog since a sitemap XML file has no <h1> or
    <title> for page_title() to find. Recursing here so only genuine
    <url><loc> page entries end up in `found` fixes that at the source.
    """
    if sitemap_url in seen_sitemaps:
        return
    seen_sitemaps.add(sitemap_url)

    status, html, _, _ = fetcher.get(sitemap_url)
    if status != "new" or not html:
        return

    soup = BeautifulSoup(html, "xml")

    # A sitemap index: each <loc> here is another sitemap, not a page.
    for loc in soup.select("sitemapindex > sitemap > loc"):
        sub_url = loc.text.strip()
        if is_same_site(sub_url):
            _collect_sitemap_urls(fetcher, sub_url, found, seen_sitemaps)

    # A urlset: each <loc> here is a real page.
    for loc in soup.select("urlset > url > loc"):
        url = loc.text.strip()
        if is_same_site(url):
            found.add(url)



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
            if not href or not is_same_site(href):
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
            txt = strip_inline_links(p)
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
    # Track every image URL already used (the hero) so it isn't *also*
    # duplicated inline further down the article.
    seen_images = {hero_image} if hero_image else set()

    if content:
        # Include "img" in the same document-order walk as the text
        # elements. This catches every photo in the article body - not
        # just the first/hero one - including images that WordPress
        # wraps in <figure>/<div class="wp-caption"> containers (which
        # aren't in the p/h2/h3/li/blockquote list themselves, but their
        # <img> children still match here since find_all searches all
        # descendants regardless of nesting).
        for el in content.find_all(["p","h2","h3","li","blockquote","img"], recursive=True):
            if el.name == "img":
                src = el.get("src")
                if not src or is_blocked_url(src) or is_emoji_image(el):
                    continue
                abs_src = absolutize(src)
                if abs_src in seen_images:
                    continue
                seen_images.add(abs_src)
                blocks.append({
                    "kind": "image",
                    "src": abs_src,
                    "alt": clean_text(el.get("alt", "")),
                })
                continue

            text=clean_text(el.get_text(" ", strip=True))
            if not text:
                continue

            # Preserve any links inside this element (e.g. "check them out
            # on Instagram/YouTube" lines, which are commonly the last
            # paragraph of an interview) as [label](url) markers, which the
            # `linkify` template filter turns back into real <a> tags.
            linked_text = strip_inline_links(el)

            lower=text.lower()
            if lower.startswith(("photo credit", "copyright", "picture from")):
                # The credit line almost always stands entirely on its own
                # paragraph. On a handful of older posts, though, it was
                # written in the very same paragraph as the first question
                # with no line break in between (e.g. "Copyright \u2013 When
                # did you start playing guitar...?"), which made the credit
                # swallow the entire first question. Split those apart at
                # the dash so both the credit line and the question survive,
                # instead of only recognizing a credit that's fully alone.
                m = re.match(r"^(.*?)\s+[\u2013\u2014-]\s+(.+)$", linked_text)
                if m and m.group(2).strip().endswith("?"):
                    photo_credit = m.group(1).strip()
                    linked_text = m.group(2).strip()
                    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", linked_text).strip()
                else:
                    photo_credit=linked_text
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
                blocks.append({"kind":"answer","text":linked_text})

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
    # interview/article instead of losing content. In this branch
    # `full_html` below already carries the original markup (images
    # included), so drop image blocks here to avoid rendering every photo
    # twice.
    if not qa:
        intro = [b for b in blocks if b["kind"] != "image"]

    # Every interview ends with a short sign-off paragraph after the final
    # Q&A pair (e.g. "Check Bo's Instagram page..."), rather than another
    # question. Because it's just a plain, un-headed <p> like any other
    # answer text, the loop above was gluing it onto the end of the last
    # question's answer list -- reading as if the final answer just kept
    # rambling on into a plug for the artist's socials. Pull that trailing
    # sign-off out into its own `outro` block (rendered by the template as
    # a separate, distinctly-styled closing section) instead. Heuristic:
    # it's the very last block of the whole article, itself short and
    # containing a link -- and we only take it if the question still has
    # another answer block left over afterwards, so we never strip a
    # question down to no answer at all.
    outro = []
    if qa and len(qa[-1]["answers"]) > 1:
        last_block = qa[-1]["answers"][-1]
        if (
            last_block["kind"] == "answer"
            and "](" in last_block["text"]
            and len(last_block["text"]) < 400
        ):
            outro.append(qa[-1]["answers"].pop())

    return {
        "type":"interview" if qa else "article",
        "title":title,
        "url":url,
        "hero_image":hero_image,
        "photo_credit":photo_credit,
        "intro":intro,
        "qa":qa,
        "outro":outro,
        "full_html": clean_html(str(content)) if content and not qa else ""
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
            if is_emoji_image(node):
                return ""
            alt = node.get("alt", "")
            if alt and not is_blocked_url(node.get("src", "")):
                return alt
            return ""
        if node.name == "br":
            return " "
        return "".join(walk(child) for child in node.children)

    return clean_text(walk(el))
