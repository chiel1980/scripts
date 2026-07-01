"""
assets.py
---------
Downloads referenced images (interview hero photos) into the output site's
own /assets/images/ folder so the generated site never depends on the
wordpress.com domain, and skips re-downloading images already on disk.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse

from .scraper import Fetcher

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def local_image_path(url: str, images_dir: Path) -> tuple[str, Path]:
    """Returns (relative_path_for_html, absolute_path_on_disk)."""
    parsed = urlparse(url)
    name = Path(parsed.path).name or "image"
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        ext = ".jpg"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    stem = Path(name).stem or "image"
    filename = f"{stem}-{digest}{ext}"
    return f"assets/images/{filename}", images_dir / filename


def ensure_image(url: str | None, images_dir: Path, fetcher: Fetcher) -> str | None:
    if not url:
        return None
    rel_path, abs_path = local_image_path(url, images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    if abs_path.exists():
        return rel_path
    data = fetcher.download_binary(url)
    if data:
        abs_path.write_bytes(data)
        return rel_path
    return None
