#!/usr/bin/env python3
"""
WordPress Website Scraper
Recursively scrapes a WordPress website and creates local static HTML files.
Removes WordPress footers, admin bars, and marketing/promotional bars.
Injects a responsive viewport meta tag into every page (unless --no-responsive is set)
and optionally validates each page against the W3C Nu Markup Validator (--validate).
Moves the scraped site to ../thatspecificsound.github.io, overwriting files if needed.

Dependencies:
- Python 3.8+
- requests
- beautifulsoup4

Install with pip:
    pip install requests beautifulsoup4

Debian / Ubuntu packages:
- python3
- python3-requests
- python3-bs4

Install with apt:
    sudo apt install python3 python3-requests python3-bs4

macOS (Homebrew) packages:
- python

Install with Homebrew:
    brew install python
    pip3 install requests beautifulsoup4

Notes on the new flags:
- --no-responsive   Skip adding <meta name="viewport" content="width=device-width, initial-scale=1">
                     to pages that don't already have one. On by default, since it's the single
                     biggest lever for making a static clone behave on mobile.
- --validate         Send each rendered page to https://validator.w3.org/nu/?out=json and record
                     error/warning counts. Requires outbound internet access to validator.w3.org.
                     A JSON report is written to --validation-output (default: w3c_validation_report.json).
- --autofix          Before saving/validating a page, fix a broad-but-conservative list of common,
                     low-risk markup issues: missing <html lang>, missing <meta charset>, missing
                     <title>, missing <img alt>, duplicate id attributes, target="_blank" links
                     missing rel="noopener noreferrer", obsolete <a name>, deprecated tags
                     (<center>, <font>, <strike>, <acronym>, <big>, <tt>), and obsolete presentational
                     attributes (align, bgcolor, valign, cellpadding/cellspacing, etc.) on the tags
                     where the validator commonly flags them. Use --lang to set the lang code (default: en).
- --strict-w3c       With --validate, exit with status code 2 and print full details for any page that
                     still has validator errors after autofix, instead of finishing as if all were well.

Caveats: injecting a viewport tag makes a page *capable* of responding to screen size, but it does not
rewrite the site's CSS. If the original theme's stylesheet has no @media queries, the layout still won't
reflow on small screens — the script flags this case at the end of the run so you know to review the CSS
by hand. --autofix covers a deliberately conservative, known-safe set of patterns; it cannot guarantee a
zero-error W3C report for arbitrary source markup, since some issues (broken nesting from a plugin, invalid
attribute values, malformed inline SVG, etc.) are too content-specific to rewrite safely without a human
judgment call. --strict-w3c exists precisely so you get an honest pass/fail instead of having to trust that
autofix caught everything — run with --validate --autofix --strict-w3c and treat any reported errors as a
manual to-do list.
"""

import os
import sys
import time
import json
import platform
import subprocess
import importlib.util
import argparse
import tempfile
from urllib.parse import urljoin, urlparse, urlunparse
from pathlib import Path
from collections import deque
import shutil

# requests and bs4 are imported defensively so that --check-deps can still run
# (and explain what's missing) even on a machine where they aren't installed yet.
try:
    import requests
    from requests.adapters import HTTPAdapter, Retry
except ImportError:
    requests = None
    HTTPAdapter = None
    Retry = None

try:
    from bs4 import BeautifulSoup, Comment
except ImportError:
    BeautifulSoup = None
    Comment = None


# ----------------- Dependency / Environment Check ----------------- #
REQUIRED_PYTHON_PACKAGES = {
    'requests': 'requests',
    'bs4': 'beautifulsoup4',
}

# Best-effort mapping from detected package manager -> system package names.
# Used only for an informational cross-check; pip packages are what the script
# actually imports and run on.
SYSTEM_PACKAGE_NAMES = {
    'apt': {'requests': 'python3-requests', 'bs4': 'python3-bs4'},
    'dnf': {'requests': 'python3-requests', 'bs4': 'python3-beautifulsoup4'},
    'yum': {'requests': 'python3-requests', 'bs4': 'python3-beautifulsoup4'},
    'pacman': {'requests': 'python-requests', 'bs4': 'python-beautifulsoup4'},
}


def detect_os():
    """Identify the OS/distro and the package manager available for it."""
    system = platform.system()
    info = {'system': system, 'distro': None, 'version': None, 'package_manager': None}

    if system == 'Linux':
        os_release = {}
        try:
            with open('/etc/os-release') as f:
                for line in f:
                    if '=' in line:
                        k, v = line.rstrip().split('=', 1)
                        os_release[k] = v.strip('"')
        except FileNotFoundError:
            pass
        info['distro'] = os_release.get('NAME', os_release.get('ID', 'Linux'))
        info['version'] = os_release.get('VERSION_ID', '')

        for manager, probe in (('apt', 'apt'), ('dnf', 'dnf'), ('yum', 'yum'), ('pacman', 'pacman')):
            if shutil.which(probe):
                info['package_manager'] = manager
                break

    elif system == 'Darwin':
        info['distro'] = 'macOS'
        info['version'] = platform.mac_ver()[0]
        if shutil.which('brew'):
            info['package_manager'] = 'brew'

    elif system == 'Windows':
        info['distro'] = 'Windows'
        info['version'] = platform.version()
        info['package_manager'] = 'pip'  # no native OS package manager ships these libs on Windows

    return info


def check_python_packages():
    """Return the list of pip package names that are importable / missing."""
    missing = []
    for module_name, pip_name in REQUIRED_PYTHON_PACKAGES.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(pip_name)
    return missing


def check_system_package(package_manager, package_name):
    """Best-effort, informational-only check of whether a system package is installed.
    Returns True/False if determinable, or None if the check itself couldn't be run."""
    try:
        if package_manager == 'apt':
            result = subprocess.run(['dpkg', '-s', package_name], capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        elif package_manager in ('dnf', 'yum'):
            result = subprocess.run(['rpm', '-q', package_name], capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        elif package_manager == 'pacman':
            result = subprocess.run(['pacman', '-Q', package_name], capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        elif package_manager == 'brew':
            result = subprocess.run(['brew', 'list', package_name], capture_output=True, text=True, timeout=10)
            return result.returncode == 0
    except Exception:
        return None
    return None


def check_dependencies(verbose=True):
    """Check Python version, OS/distro, and required dependencies (pip first, with a
    best-effort cross-check against the OS's own package manager). Returns True if the
    script has everything it needs to run."""
    if verbose:
        print("=" * 60)
        print("Environment check")
        print("=" * 60)

    py_ok = sys.version_info >= (3, 8)
    if verbose:
        print(f"Python version: {platform.python_version()} {'(OK)' if py_ok else '(requires 3.8+)'}")

    os_info = detect_os()
    if verbose:
        os_label = f"{os_info['distro']} {os_info['version']}".strip() if os_info['distro'] else os_info['system']
        print(f"Operating system: {os_label}")
        print(f"Detected package manager: {os_info['package_manager'] or 'none found — will rely on pip'}")

    missing_pip = check_python_packages()
    if verbose:
        if missing_pip:
            print(f"Missing Python packages (pip): {', '.join(missing_pip)}")
        else:
            print("Python packages: requests, beautifulsoup4 — both importable")

    pm = os_info['package_manager']
    if verbose and pm and pm in SYSTEM_PACKAGE_NAMES:
        for module_name, sys_pkg in SYSTEM_PACKAGE_NAMES[pm].items():
            status = check_system_package(pm, sys_pkg)
            if status is True:
                print(f"  [{pm}] {sys_pkg}: installed")
            elif status is False:
                print(f"  [{pm}] {sys_pkg}: not installed via {pm} (the pip package may still satisfy this)")
            else:
                print(f"  [{pm}] {sys_pkg}: could not check ({pm} command unavailable or failed)")

    all_ok = py_ok and not missing_pip

    if verbose:
        print("=" * 60)
        if all_ok:
            print("All required dependencies are satisfied.")
        else:
            print("Missing dependencies. Suggested fix:")
            if not py_ok:
                print("  Install Python 3.8 or newer.")
            if missing_pip:
                print(f"  pip install {' '.join(missing_pip)}")
                if pm == 'apt':
                    print("  # or: sudo apt install python3-requests python3-bs4")
                elif pm in ('dnf', 'yum'):
                    print(f"  # or: sudo {pm} install python3-requests python3-beautifulsoup4")
                elif pm == 'pacman':
                    print("  # or: sudo pacman -S python-requests python-beautifulsoup4")
                elif pm == 'brew':
                    print("  # macOS via Homebrew: brew install python && pip3 install requests beautifulsoup4")
        print("=" * 60)

    return all_ok


class WordPressScraper:
    def __init__(self, base_url, output_dir='scraped_site', max_pages=None, delay=1.0, remove_footer=True,
                 dry_run=False, ensure_responsive=True, validate_w3c=True, validation_output='w3c_validation_report.json',
                 autofix=True, default_lang='en', strict_w3c=True, remove_unused=True):
        self.base_url = base_url.rstrip('/')
        self.domain = urlparse(base_url).netloc
        self.output_dir = Path(output_dir)
        self.max_pages = max_pages
        self.delay = delay
        self.remove_footer = remove_footer
        self.dry_run = dry_run  # <-- new
        self.ensure_responsive = ensure_responsive  # <-- new: inject viewport meta tag if missing
        self.validate_w3c = validate_w3c  # <-- new: run pages through the W3C Nu validator
        self.validation_output = Path(validation_output)
        self.autofix = autofix  # <-- new: apply common markup fixes before saving/validating
        self.default_lang = default_lang  # <-- new: lang value used when <html> is missing one
        self.strict_w3c = strict_w3c  # <-- new: fail the run if any page still has W3C errors
        self.remove_unused = remove_unused  # <-- new: delete downloaded resources no HTML file references

        self.visited_urls = set()
        self.to_visit = deque([self.base_url])
        self.downloaded_resources = set()
        self.downloaded_resource_files = set()  # local file Paths written by download_resource
        self.found_responsive_css = False  # tracks whether any downloaded stylesheet has @media rules
        self.validation_results = []  # collected W3C validation results, one entry per validated page
        self.autofix_count = 0  # total number of individual fixes applied across the whole site

        if not self.dry_run:
            self.output_dir.mkdir(parents=True, exist_ok=True)

        # Session with retries
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount('http://', HTTPAdapter(max_retries=retries))
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    # ----------------- URL Handling ----------------- #
    def is_valid_url(self, url):
        parsed = urlparse(url)
        return parsed.netloc in ('', self.domain)

    def normalize_url(self, url):
        parsed = urlparse(url)
        normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ''))
        return normalized.rstrip('/') if normalized != self.base_url else normalized

    def url_to_filepath(self, url):
        parsed = urlparse(url)
        path = parsed.path.lstrip('/')

        if not path or path == '/':
            path = 'index.html'

        if not os.path.splitext(path)[1]:
            path = os.path.join(path, 'index.html')

        if parsed.query:
            base, ext = os.path.splitext(path)
            safe_query = parsed.query.replace('&', '_').replace('=', '-')
            path = f"{base}_{safe_query}{ext}"

        return self.output_dir / path

    def get_relative_path(self, from_url, to_url):
        from_path = self.url_to_filepath(from_url)
        to_path = self.url_to_filepath(to_url)
        try:
            return os.path.relpath(to_path, from_path.parent).replace('\\', '/')
        except ValueError:
            return str(to_path).replace('\\', '/')

    # ----------------- Resource Handling ----------------- #
    def download_resource(self, url):
        abs_url = urljoin(self.base_url, url)
        if not self.is_valid_url(abs_url):
            return
        norm_url = self.normalize_url(abs_url)
        if norm_url in self.downloaded_resources:
            return

        try:
            response = self.session.get(abs_url, timeout=30)
            response.raise_for_status()

            filepath = self.url_to_filepath(abs_url)
            if not self.dry_run:
                filepath.parent.mkdir(parents=True, exist_ok=True)
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                self.downloaded_resource_files.add(filepath.resolve())

            if filepath.suffix.lower() == '.css' and not self.found_responsive_css:
                if '@media' in response.text:
                    self.found_responsive_css = True

            self.downloaded_resources.add(norm_url)
            print(f"  Resource downloaded: {url}" if not self.dry_run else f"  [Dry-run] Would download: {url}")

        except Exception as e:
            print(f"  Failed to download {url}: {e}")

    # ----------------- HTML Cleanup ----------------- #
    def clean_wordpress_elements(self, soup):
        if not self.remove_footer:
            return soup

        selectors = [
            '#wpadminbar', '.admin-bar', 'footer', '.site-footer',
            '.footer', '#footer', '[class*="footer"]', '.site-info'
        ]
        for sel in selectors:
            for el in soup.select(sel):
                el.decompose()

        for marketing_div in soup.find_all('div', class_='marketing-bar-text'):
            text = marketing_div.get_text(strip=True).lower()
            if text.startswith('design a site like this with wordpress.com'):
                parent = marketing_div.parent
                marketing_div.decompose()
                if parent and not parent.get_text(strip=True):
                    parent.decompose()
                print("  Removed WordPress.com marketing bar (marketing-bar-text)")

        for marketing_div in soup.find_all('div', id='marketingbar'):
            classes = marketing_div.get('class', [])
            if 'marketing-bar' in classes:
                marketing_div.decompose()
                print("  Removed WordPress.com marketing bar (marketingbar id)")

        for meta in soup.find_all('meta', attrs={'name': 'generator'}):
            meta.decompose()

        for comment in soup.find_all(string=lambda s: isinstance(s, Comment) and 'wordpress' in s.lower()):
            comment.extract()

        for link in soup.find_all('a', href=True):
            if 'wordpress.org' in link['href'].lower():
                link.decompose()

        return soup

    # ----------------- Responsive Handling ----------------- #
    def ensure_viewport(self, soup):
        """Insert a mobile-friendly viewport meta tag if one isn't already present."""
        if not self.ensure_responsive:
            return soup

        head = soup.find('head')
        if head is None:
            head = soup.new_tag('head')
            if soup.html:
                soup.html.insert(0, head)
            else:
                soup.insert(0, head)

        existing = head.find('meta', attrs={'name': 'viewport'})
        if existing is None:
            meta = soup.new_tag('meta')
            meta['name'] = 'viewport'
            meta['content'] = 'width=device-width, initial-scale=1'
            head.insert(0, meta)
            print("  Added responsive viewport meta tag")

        return soup

    # ----------------- Autofix ----------------- #
    def autofix_common_issues(self, soup, url):
        """Apply a small set of safe, well-understood fixes for the markup issues the
        W3C validator flags most often. This is intentionally conservative — it won't
        try to parse and act on arbitrary validator messages, just fix known patterns."""
        if not self.autofix:
            return soup

        fixes = []

        html_tag = soup.find('html')
        if html_tag and not html_tag.get('lang'):
            html_tag['lang'] = self.default_lang
            fixes.append(f'Added lang="{self.default_lang}" to <html>')

        head = soup.find('head')
        if head is None:
            head = soup.new_tag('head')
            if soup.html:
                soup.html.insert(0, head)
            else:
                soup.insert(0, head)
            fixes.append('Added missing <head>')

        if not head.find('meta', charset=True):
            charset_meta = soup.new_tag('meta')
            charset_meta['charset'] = 'utf-8'
            head.insert(0, charset_meta)
            fixes.append('Added <meta charset="utf-8">')

        if not head.find('title'):
            title_tag = soup.new_tag('title')
            h1 = soup.find('h1')
            title_text = h1.get_text(strip=True) if h1 else urlparse(url).netloc
            title_tag.string = title_text or 'Untitled Page'
            head.append(title_tag)
            fixes.append('Added missing <title>')

        for img in soup.find_all('img'):
            if not img.has_attr('alt'):
                img['alt'] = ''
                fixes.append(f'Added empty alt attribute to <img src="{img.get("src", "")}">')

        seen_ids = {}
        for el in soup.find_all(attrs={'id': True}):
            el_id = el['id']
            seen_ids.setdefault(el_id, 0)
            seen_ids[el_id] += 1
            if seen_ids[el_id] > 1:
                new_id = f"{el_id}-{seen_ids[el_id]}"
                el['id'] = new_id
                fixes.append(f'Renamed duplicate id "{el_id}" to "{new_id}"')

        for a in soup.find_all('a', target='_blank'):
            rel = a.get('rel', [])
            if isinstance(rel, str):
                rel = rel.split()
            changed = False
            for needed in ('noopener', 'noreferrer'):
                if needed not in rel:
                    rel.append(needed)
                    changed = True
            if changed:
                a['rel'] = rel
                fixes.append('Added rel="noopener noreferrer" to a target="_blank" link')

        # <a name="x"> is obsolete in HTML5 — convert to id, drop name (unless id already set)
        for a in soup.find_all('a', attrs={'name': True}):
            name_val = a['name']
            if not a.get('id'):
                a['id'] = name_val
                fixes.append(f'Converted obsolete <a name="{name_val}"> to id="{name_val}"')
            del a['name']

        # Deprecated presentational elements: rewrite as their valid HTML5 equivalents
        # rather than just deleting them, so the visual intent isn't silently lost.
        for center in soup.find_all('center'):
            center.name = 'div'
            existing_style = center.get('style', '')
            center['style'] = (existing_style + ';' if existing_style else '') + 'text-align:center;'
            fixes.append('Rewrote <center> as <div style="text-align:center;">')

        for font in soup.find_all('font'):
            style_parts = []
            if font.get('color'):
                style_parts.append(f"color:{font['color']}")
            if font.get('face'):
                style_parts.append(f"font-family:{font['face']}")
            if font.get('size'):
                style_parts.append(f"font-size:{font['size']}")
            for attr in ('color', 'face', 'size'):
                if attr in font.attrs:
                    del font[attr]
            font.name = 'span'
            if style_parts:
                existing_style = font.get('style', '')
                font['style'] = (existing_style + ';' if existing_style else '') + ';'.join(style_parts)
            fixes.append('Rewrote <font> as <span> with equivalent inline style')

        for strike in soup.find_all('strike'):
            strike.name = 's'
            fixes.append('Renamed obsolete <strike> to <s>')

        for acronym in soup.find_all('acronym'):
            acronym.name = 'abbr'
            fixes.append('Renamed obsolete <acronym> to <abbr>')

        for tag_name in ('big', 'tt'):
            for el in soup.find_all(tag_name):
                el.unwrap()
                fixes.append(f'Removed obsolete <{tag_name}> tag (kept its content)')

        # Obsolete presentational attributes the Nu validator flags per-element.
        # Deliberately scoped per tag so we never touch attributes that are still
        # valid in that context (e.g. width/height stay on <img>, scope stays on <th>).
        attr_strip_rules = {
            'table': ['align', 'bgcolor', 'border', 'cellpadding', 'cellspacing', 'width', 'frame', 'rules'],
            'tr': ['align', 'bgcolor', 'valign'],
            'td': ['align', 'bgcolor', 'valign', 'nowrap'],
            'th': ['align', 'bgcolor', 'valign', 'nowrap'],
            'hr': ['align', 'color', 'noshade', 'size', 'width'],
            'div': ['align'],
            'p': ['align'],
            'h1': ['align'], 'h2': ['align'], 'h3': ['align'], 'h4': ['align'], 'h5': ['align'], 'h6': ['align'],
            'img': ['align', 'border', 'hspace', 'vspace'],
            'body': ['background', 'bgcolor', 'text', 'link', 'vlink', 'alink'],
        }
        for tag_name, attrs_to_strip in attr_strip_rules.items():
            for el in soup.find_all(tag_name):
                removed = [a for a in attrs_to_strip if a in el.attrs]
                for attr in removed:
                    del el[attr]
                if removed:
                    fixes.append(f'Stripped obsolete attribute(s) {", ".join(removed)} from <{tag_name}>')

        for script in soup.find_all('script', attrs={'language': True}):
            del script['language']
            fixes.append('Removed obsolete language attribute from <script>')

        if fixes:
            self.autofix_count += len(fixes)
            print(f"  Autofix applied {len(fixes)} fix(es):")
            for f in fixes:
                print(f"    - {f}")

        return soup

    def validate_html_w3c(self, html_content, url):
        """Submit rendered HTML to the W3C Nu Markup Validator and record the results."""
        if not self.validate_w3c:
            return None

        if self.dry_run:
            print(f"  [Dry-run] Would validate against W3C: {url}")
            return None

        try:
            headers = {'Content-Type': 'text/html; charset=utf-8'}
            resp = requests.post(
                'https://validator.w3.org/nu/?out=json',
                data=html_content.encode('utf-8'),
                headers=headers,
                timeout=30
            )
            resp.raise_for_status()
            result = resp.json()
            messages = result.get('messages', [])
            errors = [m for m in messages if m.get('type') == 'error']
            warnings = [m for m in messages if m.get('type') == 'info' and m.get('subType') == 'warning']

            self.validation_results.append({
                'url': url,
                'error_count': len(errors),
                'warning_count': len(warnings),
                'messages': messages
            })
            print(f"  W3C validation: {len(errors)} error(s), {len(warnings)} warning(s)")
            return result
        except Exception as e:
            print(f"  W3C validation failed for {url}: {e}")
            return None

    def write_validation_report(self):
        if not self.validate_w3c or not self.validation_results:
            return

        total_errors = sum(r['error_count'] for r in self.validation_results)
        total_warnings = sum(r['warning_count'] for r in self.validation_results)

        report = {
            'site': self.base_url,
            'pages_validated': len(self.validation_results),
            'total_errors': total_errors,
            'total_warnings': total_warnings,
            'pages': self.validation_results
        }

        with open(self.validation_output, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)

        print(f"\nW3C validation report written to: {self.validation_output.absolute()}")
        print(f"Total: {total_errors} error(s), {total_warnings} warning(s) across {len(self.validation_results)} page(s)")

    def check_strict_w3c(self):
        """If --strict-w3c is set, give a definitive pass/fail answer instead of leaving you
        to trust that autofix caught everything. This never attempts further fixes — some
        remaining issues are specific enough to a page's content that auto-rewriting them
        isn't safe, so they're surfaced for a manual look instead."""
        if not (self.validate_w3c and self.strict_w3c):
            return True

        pages_with_errors = [r for r in self.validation_results if r['error_count'] > 0]
        if not pages_with_errors:
            print("\nStrict W3C check: PASSED — zero errors across all validated pages.")
            return True

        print(f"\nStrict W3C check: FAILED — {len(pages_with_errors)} page(s) still have validator errors:")
        for r in pages_with_errors:
            print(f"\n  {r['url']}  ({r['error_count']} error(s))")
            for m in r['messages']:
                if m.get('type') == 'error':
                    line = m.get('lastLine')
                    loc = f" (line {line})" if line else ""
                    print(f"    - {m.get('message', '').strip()}{loc}")
        print(f"\nFull details in {self.validation_output.absolute()}. These remaining issues need a manual look — "
              "autofix only ever applies a known-safe, conservative set of rewrites and won't guess at fixes "
              "for content-specific markup problems.")
        return False

    def update_links(self, soup, base_url):
        for tag, attr in [('a', 'href'), ('link', 'href'), ('script', 'src'), ('img', 'src')]:
            for t in soup.find_all(tag, **{attr: True}):
                url = t[attr]
                abs_url = urljoin(base_url, url)
                if self.is_valid_url(abs_url):
                    norm_url = self.normalize_url(abs_url)
                    if tag in ('link', 'script', 'img'):
                        self.download_resource(url)
                    if tag == 'a':
                        if norm_url not in self.visited_urls and norm_url not in self.to_visit:
                            self.to_visit.append(norm_url)
                    t[attr] = self.get_relative_path(base_url, abs_url)

        for img in soup.find_all(attrs={'srcset': True}):
            srcset_items = []
            for item in img['srcset'].split(','):
                parts = item.strip().split()
                if parts:
                    url = parts[0]
                    abs_url = urljoin(base_url, url)
                    if self.is_valid_url(abs_url):
                        self.download_resource(url)
                        rel_path = self.get_relative_path(base_url, abs_url)
                        srcset_items.append(f"{rel_path} {' '.join(parts[1:])}".strip())
            img['srcset'] = ', '.join(srcset_items)

        return soup

    # ----------------- Page Scraping ----------------- #
    def scrape_page(self, url):
        print(f"\nScraping: {url}")
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, 'html.parser')
            soup = self.clean_wordpress_elements(soup)
            soup = self.update_links(soup, url)
            soup = self.ensure_viewport(soup)
            soup = self.autofix_common_issues(soup, url)

            final_html = soup.prettify()

            if self.validate_w3c:
                self.validate_html_w3c(final_html, url)

            filepath = self.url_to_filepath(url)
            if not self.dry_run:
                filepath.parent.mkdir(parents=True, exist_ok=True)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(final_html)
            print(f"Saved: {filepath}" if not self.dry_run else f"[Dry-run] Would save: {filepath}")
            return True
        except Exception as e:
            print(f"Failed to scrape {url}: {e}")
            return False

    # ----------------- Cleanup ----------------- #
    def _resolve_local_ref(self, html_file, value):
        """Resolve an href/src value found in an already-saved HTML file to a local
        Path. Returns None for anything that isn't a local file reference (external
        URLs, anchors, mailto:, data: URIs, etc.)."""
        if not value:
            return None
        if value.startswith(('http://', 'https://', '//', 'mailto:', 'tel:', 'javascript:', 'data:', '#')):
            return None
        path_part = value.split('#', 1)[0].split('?', 1)[0]
        if not path_part:
            return None
        try:
            return (html_file.parent / path_part).resolve()
        except (OSError, ValueError):
            return None

    def prune_unused_resources(self):
        """Delete downloaded resource files (CSS, JS, images, etc.) that no saved HTML
        page actually references. HTML pages themselves are never removed by this step —
        only the supporting resource files. Runs after all pages are saved so link
        rewriting has already turned every reference into a local relative path."""
        if not self.remove_unused:
            return
        if self.dry_run:
            print("\n[Dry-run] Skipping unused-resource cleanup (nothing was written to disk)")
            return

        referenced = set()
        html_files = list(self.output_dir.rglob('*.html'))
        for html_file in html_files:
            try:
                with open(html_file, 'r', encoding='utf-8') as f:
                    soup = BeautifulSoup(f.read(), 'html.parser')
            except Exception as e:
                print(f"  Could not parse {html_file} while checking for unused resources: {e}")
                continue

            for tag, attr in [('link', 'href'), ('script', 'src'), ('img', 'src'), ('a', 'href')]:
                for t in soup.find_all(tag, **{attr: True}):
                    resolved = self._resolve_local_ref(html_file, t[attr])
                    if resolved:
                        referenced.add(resolved)

            for img in soup.find_all(attrs={'srcset': True}):
                for item in img['srcset'].split(','):
                    parts = item.strip().split()
                    if parts:
                        resolved = self._resolve_local_ref(html_file, parts[0])
                        if resolved:
                            referenced.add(resolved)

        removed = []
        for path in self.output_dir.rglob('*'):
            if path.is_dir() or path.suffix.lower() == '.html':
                continue
            if path.resolve() not in referenced:
                removed.append(path)

        for path in removed:
            try:
                path.unlink()
            except OSError as e:
                print(f"  Could not remove {path}: {e}")

        # Clean up any directories left empty by the removals above.
        for d in sorted([p for p in self.output_dir.rglob('*') if p.is_dir()], reverse=True):
            try:
                if not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass

        print()
        if removed:
            print(f"Removed {len(removed)} unused resource file(s) not referenced by any saved HTML page:")
            for p in removed:
                print(f"  - {p.relative_to(self.output_dir)}")
        else:
            print("Unused-resource check: every downloaded resource is referenced by at least one saved page.")

    # ----------------- Move Output ----------------- #
    def move_output(self, target_dir='../thatspecificsound.github.io'):
        target_path = Path(target_dir).resolve()
        if self.dry_run:
            print(f"[Dry-run] Would move scraped site from {self.output_dir} to {target_path}")
            return

        target_path.mkdir(parents=True, exist_ok=True)
        print(f"Moving scraped site from {self.output_dir} to {target_path}")

        for item in self.output_dir.iterdir():
            dest = target_path / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

        if not any(self.output_dir.iterdir()):
            self.output_dir.rmdir()
        print("Move complete!")

    # ----------------- Main Scraper Loop ----------------- #
    def scrape(self):
        print(f"Starting scrape: {self.base_url}")
        print(f"Output directory: {self.output_dir.absolute()}\n")

        pages_scraped = 0
        while self.to_visit:
            if self.max_pages and pages_scraped >= self.max_pages:
                print(f"\nReached page limit ({self.max_pages})")
                break

            url = self.to_visit.popleft()
            if url in self.visited_urls:
                continue

            self.visited_urls.add(url)
            if self.scrape_page(url):
                pages_scraped += 1
            time.sleep(self.delay)

        print(f"\n{'=' * 60}")
        print("Scraping complete!")
        print(f"Pages scraped: {pages_scraped}")
        print(f"Resources downloaded: {len(self.downloaded_resources)}")
        print(f"Output directory: {self.output_dir.absolute()}")
        if self.ensure_responsive:
            if self.found_responsive_css:
                print("Responsive check: at least one downloaded stylesheet contains @media rules.")
            else:
                print("Responsive check: NO @media rules found in downloaded stylesheets — "
                      "viewport meta tags were added, but the site's CSS may not adapt to small screens. "
                      "Manual review recommended.")
        if self.autofix:
            print(f"Autofix: {self.autofix_count} fix(es) applied across {pages_scraped} page(s)")
        print(f"{'=' * 60}")

        self.prune_unused_resources()
        self.write_validation_report()
        strict_ok = self.check_strict_w3c()
        self.move_output()
        return strict_ok


DEFAULT_URL = 'https://thatspecificsound.wordpress.com'
# The scrape is a temporary working copy (the real destination is the
# ../thatspecificsound.github.io move at the end), so it belongs in /tmp rather
# than cluttering whatever directory the script happens to be run from.
DEFAULT_OUTPUT_DIR = str(Path(tempfile.gettempdir()) / 'wordpress_scraper_output')


def build_scraper(args, dry_run):
    """Construct a WordPressScraper from parsed CLI args, with dry_run forced to the
    given value (used so the preview pass and the real pass each get a clean instance)."""
    return WordPressScraper(
        base_url=args.url,
        output_dir=args.output,
        max_pages=args.max_pages,
        delay=args.delay,
        remove_footer=not args.keep_footer,
        dry_run=dry_run,
        ensure_responsive=not args.no_responsive,
        validate_w3c=not args.no_validate,
        validation_output=args.validation_output,
        autofix=not args.no_autofix,
        default_lang=args.lang,
        strict_w3c=not args.no_strict_w3c,
        remove_unused=not args.keep_unused_resources
    )


def print_options_summary(args):
    """Verbose summary of every option in effect for this run, and whether it's at its
    default or was explicitly overridden, so nothing is silently on/off."""
    def line(label, value, is_default):
        tag = "(default)" if is_default else "(overridden)"
        print(f"  {label:<28}: {value:<6} {tag}")

    print("=" * 60)
    print("Run configuration")
    print("=" * 60)
    print(f"  {'Target URL':<28}: {args.url} {'(default)' if args.url == DEFAULT_URL else '(overridden)'}")
    print(f"  {'Output directory':<28}: {args.output} {'(default)' if args.output == DEFAULT_OUTPUT_DIR else '(overridden)'}")
    line("Responsive viewport fix", "ON" if not args.no_responsive else "OFF", not args.no_responsive)
    line("Autofix", "ON" if not args.no_autofix else "OFF", not args.no_autofix)
    line("W3C validation", "ON" if not args.no_validate else "OFF", not args.no_validate)
    line("Strict W3C check", "ON" if not args.no_strict_w3c else "OFF", not args.no_strict_w3c)
    line("Remove unused resources", "ON" if not args.keep_unused_resources else "OFF", not args.keep_unused_resources)
    line("Keep WordPress footer", "ON" if args.keep_footer else "OFF", not args.keep_footer)
    print(f"  {'Max pages':<28}: {args.max_pages if args.max_pages else 'unlimited':<6} "
          f"{'(default)' if args.max_pages is None else '(overridden)'}")
    print(f"  {'Request delay (s)':<28}: {args.delay:<6} {'(default)' if args.delay == 1.0 else '(overridden)'}")
    print("=" * 60)


# ----------------- CLI ----------------- #
def main():
    parser = argparse.ArgumentParser(description="Recursively scrape a WordPress website into static HTML.")
    parser.add_argument('url', nargs='?', default=DEFAULT_URL,
                         help=f'Base URL of the WordPress site to scrape (default: {DEFAULT_URL})')
    parser.add_argument('-o', '--output', default=DEFAULT_OUTPUT_DIR,
                         help=f'Output directory for the temporary scraped copy (default: {DEFAULT_OUTPUT_DIR})')
    parser.add_argument('-m', '--max-pages', type=int, default=None, help='Maximum pages to scrape')
    parser.add_argument('-d', '--delay', type=float, default=1.0, help='Delay between requests (seconds)')
    parser.add_argument('--keep-footer', action='store_true', help='Keep WordPress footer and attribution')
    parser.add_argument('--dry-run', action='store_true',
                         help='Only run the dry-run preview (no confirmation prompt, no real scrape)')
    parser.add_argument('-y', '--yes', action='store_true',
                         help='Skip the "continue?" confirmation after the dry-run preview')
    parser.add_argument('--no-responsive', action='store_true',
                         help='Skip injecting a responsive viewport meta tag into pages (on by default)')
    parser.add_argument('--no-validate', action='store_true',
                         help='Skip W3C Nu Markup Validator checks (on by default; requires internet access)')
    parser.add_argument('--validation-output', default='w3c_validation_report.json',
                         help='Path to write the W3C validation report JSON')
    parser.add_argument('--no-strict-w3c', action='store_true',
                         help='Do not fail the run if W3C errors remain after autofix (strict checking is on by default)')
    parser.add_argument('--no-autofix', action='store_true',
                         help='Skip automatic markup fixes (lang/charset/title/alt, duplicate ids, deprecated tags, '
                              'obsolete presentational attributes, etc. — on by default)')
    parser.add_argument('--lang', default='en',
                         help='Language code to use when adding a missing lang attribute (default: en)')
    parser.add_argument('--keep-unused-resources', action='store_true',
                         help='Do not delete downloaded resource files that no saved HTML page references '
                              '(cleanup is on by default)')
    parser.add_argument('--check-deps', action='store_true',
                         help='Check Python version, OS/distro, and required dependencies via the appropriate '
                              'package manager, then exit without scraping')
    parser.add_argument('--skip-dep-check', action='store_true',
                         help='Skip the automatic dependency check that normally runs before scraping')

    args = parser.parse_args()

    if args.check_deps:
        ok = check_dependencies(verbose=True)
        sys.exit(0 if ok else 1)

    if not args.skip_dep_check:
        if not check_dependencies(verbose=True):
            print("\nFix the issues above, or re-run with --skip-dep-check to proceed anyway "
                  "(the script will fail immediately if requests/beautifulsoup4 are actually missing).")
            sys.exit(1)

    if requests is None or BeautifulSoup is None:
        print("requests and/or beautifulsoup4 are not installed. Run with --check-deps for details, or:")
        print("  pip install requests beautifulsoup4")
        sys.exit(1)

    if not args.url.startswith(('http://', 'https://')):
        args.url = 'https://' + args.url

    print_options_summary(args)

    if args.dry_run:
        print("\n--dry-run was passed: running the preview only, no confirmation, no real scrape.\n")
        preview = build_scraper(args, dry_run=True)
        preview.scrape()
        return

    print("\nRunning a dry-run preview first (no files will be written yet)...\n")
    preview = build_scraper(args, dry_run=True)
    preview.scrape()

    if not args.yes:
        answer = input("\nProceed with the actual scrape now? [y/N]: ").strip().lower()
        if answer not in ('y', 'yes'):
            print("Aborted — no files were written.")
            return

    print("\nStarting the real scrape...\n")
    real = build_scraper(args, dry_run=False)
    success = real.scrape()
    if not args.no_strict_w3c and not success:
        sys.exit(2)


if __name__ == '__main__':
    main()

