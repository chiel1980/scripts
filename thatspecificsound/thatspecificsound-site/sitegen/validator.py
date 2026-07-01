"""
validator.py
-------------
Validates every generated HTML file against the W3C Nu Html Checker —
the exact engine that powers validator.w3.org.

Two modes, tried in order:

1. Local/offline: if Java + the `vnujar` pip package (which bundles
   vnu.jar) are available, we shell out to it directly. This is fast,
   has no rate limits, and needs no internet access at all.
2. Public API fallback: POSTs each file to validator.w3.org/nu/?out=json.
   Requires internet access; used only if the local checker isn't
   available.

Install the offline checker with:  pip install vnujar --break-system-packages
(also requires a Java runtime on PATH)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import requests

VALIDATOR_URL = "https://validator.w3.org/nu/?out=json"
REQUEST_DELAY = 2.0  # be polite to the free public validator service


def _local_vnu_jar() -> Path | None:
    try:
        import vnujar  # noqa: F401
    except ImportError:
        return None
    jar = Path(vnujar.__file__).parent / "vnu.jar"
    return jar if jar.exists() else None


def _java_available() -> bool:
    return shutil.which("java") is not None


def validate_site_local(output_dir: Path) -> list[dict] | None:
    """Validate every *.html under output_dir in a single vnu.jar
    invocation. Returns None if the local checker isn't available."""
    jar = _local_vnu_jar()
    if not jar or not _java_available():
        return None

    html_files = sorted(output_dir.rglob("*.html"))
    if not html_files:
        return []

    cmd = ["java", "-jar", str(jar), "--format", "json", "--exit-zero-always"] + [
        str(p) for p in html_files
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        payload = json.loads(proc.stderr or proc.stdout)
    except json.JSONDecodeError:
        return None

    by_file: dict[str, list[dict]] = {}
    for msg in payload.get("messages", []):
        by_file.setdefault(msg.get("url", "").replace("file:", ""), []).append(msg)

    results = []
    for path in html_files:
        msgs = by_file.get(str(path), [])
        errors = [m for m in msgs if m.get("type") == "error"]
        warnings = [m for m in msgs if m.get("type") == "info" and m.get("subType") == "warning"]
        results.append({"file": str(path), "ok": True, "errors": errors, "warnings": warnings})
        n_err, n_warn = len(errors), len(warnings)
        status = "OK" if n_err == 0 else f"{n_err} error(s)"
        print(f"  - {path.relative_to(output_dir)}: {status}, {n_warn} warning(s)")
        for e in errors:
            print(f"      error (line {e.get('lastLine', '?')}): {e.get('message')}")
    return results


def validate_file_remote(path: Path) -> dict:
    html = path.read_bytes()
    try:
        resp = requests.post(
            VALIDATOR_URL,
            data=html,
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "User-Agent": "ThatSpecificSoundArchiver/1.0 (site validation)",
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        return {"file": str(path), "ok": False, "unreachable": True, "error": str(exc)}

    messages = payload.get("messages", [])
    errors = [m for m in messages if m.get("type") == "error"]
    warnings = [m for m in messages if m.get("type") == "info" and m.get("subType") == "warning"]
    return {"file": str(path), "ok": True, "errors": errors, "warnings": warnings}


def validate_site_remote(output_dir: Path, delay: float = REQUEST_DELAY) -> list[dict]:
    results = []
    html_files = sorted(output_dir.rglob("*.html"))
    for i, path in enumerate(html_files):
        result = validate_file_remote(path)
        results.append(result)
        if result.get("unreachable"):
            print(f"  ! could not reach validator.w3.org for {path.name}: {result['error']}")
            continue
        n_err, n_warn = len(result["errors"]), len(result["warnings"])
        status = "OK" if n_err == 0 else f"{n_err} error(s)"
        print(f"  - {path.relative_to(output_dir)}: {status}, {n_warn} warning(s)")
        for e in result["errors"]:
            print(f"      error (line {e.get('lastLine', '?')}): {e.get('message')}")
        if i < len(html_files) - 1:
            time.sleep(delay)
    return results


def validate_site(output_dir: Path) -> list[dict]:
    local = validate_site_local(output_dir)
    if local is not None:
        print("  (using local offline Nu Html Checker)")
        return local
    print("  (local checker unavailable, falling back to validator.w3.org)")
    return validate_site_remote(output_dir)


def summarize(results: list[dict]) -> tuple[int, int, int]:
    """Returns (files_with_errors, total_errors, total_warnings)."""
    reachable = [r for r in results if r.get("ok")]
    files_with_errors = sum(1 for r in reachable if r["errors"])
    total_errors = sum(len(r["errors"]) for r in reachable)
    total_warnings = sum(len(r["warnings"]) for r in reachable)
    return files_with_errors, total_errors, total_warnings
