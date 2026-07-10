# That Specific Sound — static archive generator

Builds a dark-themed, responsive, W3C-valid static website from the
content of [thatspecificsound.wordpress.com](https://thatspecificsound.wordpress.com),
with every WordPress.com and Facebook reference stripped out (tracking
pixels, sign-up/log-in links, "Blog at WordPress.com" footer, `fb:app_id`
meta tags, etc.). Re-running the script only re-fetches pages that have
actually changed on the source site, and keeps a changelog of what's new.

## What it does

1. **Scrapes** the homepage, the About page, the interviews index, and
   every individual interview page, using polite, rate-limited requests
   with conditional GET (`If-None-Match` / `If-Modified-Since`) so repeat
   runs don't re-download pages that haven't changed.
2. **Cleans** the markup: removes anything linking to `wordpress.com`,
   `wp.me`, `facebook.com`, `automattic.com`, `gravatar.com` or
   `jetpack.com`, drops tracking pixels and the WordPress.com marketing
   footer, and downloads photos into the site's own `assets/images/`
   folder so it never depends on the wordpress.com domain to display
   correctly.
3. **Tracks state** in `data/state.json` and `data/content_cache.json` —
   every URL's content hash, ETag and Last-Modified are remembered, so a
   second run only touches pages that are genuinely new or edited.
   `data/changelog.json` (and the generated site's own **Changes** page)
   records what was added, updated or removed on every run.
4. **Renders** a new dark, responsive template (not the original
   WordPress theme) called *Archivist Amp* — condensed display type,
   serif body copy, monospace gear-spec lists, and a "signal chain"
   motif used as a section divider. Mobile-first CSS, no JS framework,
   one small vanilla-JS file for the mobile nav toggle.
5. **Validates** the output against the real W3C Nu Html Checker (the
   engine behind validator.w3.org) — offline via a bundled `vnu.jar` if
   you install the optional `vnujar` package + have Java, or against the
   public API otherwise.

## Setup

Option A -- distro packages (no venv needed):

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install python3-requests python3-bs4 python3-jinja2

# Arch Linux / CachyOS
sudo pacman -S python-requests python-beautifulsoup4 python-jinja
```

Option B -- pip/venv:

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Either way, run `python generate_site.py --check-deps` any time to verify
what's installed -- it detects Debian/Ubuntu vs. Arch/CachyOS and prints
the right install command for whatever's missing.

Java is only needed if you want fully offline validation (`default-jre`
on Debian/Ubuntu, `jdk-openjdk` on Arch, or `pip install vnujar`).
Without it, `--validate` will use the public validator.w3.org API instead
(requires internet either way for the actual site content).

## Usage

```bash
# First run: scrapes everything, builds output/
python generate_site.py

# Re-run any time later: only fetches pages that changed
python generate_site.py

# Also run the page output through the W3C validator
python generate_site.py --validate

# Ignore all caches and re-fetch every page from scratch
python generate_site.py --force

# Rebuild the HTML from the existing cache without hitting the network
python generate_site.py --no-scrape
```

Open `output/index.html` in a browser, or serve the folder:

```bash
python3 -m http.server -d output 8000
```

## Project layout

```
generate_site.py        entry point / CLI
sitegen/
  scraper.py             fetching (conditional GET) + HTML parsing/cleaning
  assets.py               downloads & caches interview photos locally
  state.py                state.json / content_cache.json / changelog.json
  builder.py               renders Jinja2 templates -> output/
  validator.py             W3C Nu Html Checker (offline + API fallback)
templates/                Jinja2 templates (edit these to restyle the site)
static/css/style.css      the dark "Archivist Amp" design system
static/js/main.js         mobile nav toggle (the only JS on the site)
data/                     created at runtime: state, cache, changelog
output/                   created at runtime: the generated site
```

## Customizing the design

Colors, type and spacing are all CSS custom properties at the top of
`static/css/style.css` (`--bg`, `--accent`, `--font-display`, etc.) — change
those and the whole site re-themes consistently. Page structure lives in
`templates/*.html`; they're plain Jinja2, no build step required.

## Notes

- The scraper is intentionally rate-limited (1 request/second) and
  identifies itself with a descriptive `User-Agent`. Please keep it that
  way if you increase the crawl frequency.
- If the source site's theme markup changes significantly, the parsing
  in `sitegen/scraper.py` (look for `find_main_content`, `parse_interview`,
  etc.) may need small tweaks — it's written defensively but isn't
  immune to a full theme redesign upstream.
## Self-testing without hitting the live site

A small offline harness (fixtures/ + dev_test.py) replays canned HTML through the whole pipeline — scrape -> clean -> incremental diff -> render — across three simulated runs (first build, no changes, then an edit + a new interview), so you can sanity-check the tool after editing it without crawling the real site:

```bash
python dev_test.py
```

