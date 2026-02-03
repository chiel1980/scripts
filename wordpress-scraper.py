#!/usr/bin/env python3
"""
WordPress Website Scraper
Recursively scrapes a WordPress website and creates local static HTML files.
Removes WordPress footers, admin bars, and marketing/promotional bars.
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
"""

import os
import time
import argparse
from urllib.parse import urljoin, urlparse, urlunparse
from pathlib import Path
from collections import deque
import shutil

import requests
from requests.adapters import HTTPAdapter, Retry
from bs4 import BeautifulSoup, Comment


class WordPressScraper:
    def __init__(self, base_url, output_dir='scraped_site', max_pages=None, delay=1.0, remove_footer=True):
        self.base_url = base_url.rstrip('/')
        self.domain = urlparse(base_url).netloc
        self.output_dir = Path(output_dir)
        self.max_pages = max_pages
        self.delay = delay
        self.remove_footer = remove_footer

        self.visited_urls = set()
        self.to_visit = deque([self.base_url])
        self.downloaded_resources = set()

        # Create output directory
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
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'wb') as f:
                f.write(response.content)

            self.downloaded_resources.add(norm_url)
            print(f"  Resource downloaded: {url}")

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

    # ----------------- HTML Link Updates ----------------- #
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

            filepath = self.url_to_filepath(url)
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(soup.prettify())

            print(f"Saved: {filepath}")
            return True
        except Exception as e:
            print(f"Failed to scrape {url}: {e}")
            return False

    # ----------------- Move Output ----------------- #
    def move_output(self, target_dir='../thatspecificsound.github.io'):
        target_path = Path(target_dir).resolve()
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
        print(f"{'=' * 60}")

        self.move_output()


# ----------------- CLI ----------------- #
def main():
    parser = argparse.ArgumentParser(description="Recursively scrape a WordPress website into static HTML.")
    parser.add_argument('url', nargs='?', help='Base URL of the WordPress site to scrape')
    parser.add_argument('-o', '--output', default='scraped_site', help='Output directory')
    parser.add_argument('-m', '--max-pages', type=int, default=None, help='Maximum pages to scrape')
    parser.add_argument('-d', '--delay', type=float, default=1.0, help='Delay between requests (seconds)')
    parser.add_argument('--keep-footer', action='store_true', help='Keep WordPress footer and attribution')

    args = parser.parse_args()

    if not args.url:
        args.url = input("Enter WordPress site URL: ").strip()
    if not args.url.startswith(('http://', 'https://')):
        args.url = 'https://' + args.url

    scraper = WordPressScraper(
        base_url=args.url,
        output_dir=args.output,
        max_pages=args.max_pages,
        delay=args.delay,
        remove_footer=not args.keep_footer
    )
    scraper.scrape()


if __name__ == '__main__':
    main()

