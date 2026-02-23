"""
downloader.py — Download extracted files to the local filesystem.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import aiohttp
import yarl

# Root downloads directory — uses the system's default Downloads folder
DOWNLOADS_DIR = Path.home() / "Downloads" / "PESU_Downloads"


def _sanitise_name(name: str, max_len: int = 80) -> str:
    """Remove or replace characters that are illegal in file / folder names.
    Also truncate to *max_len* to avoid exceeding Windows MAX_PATH."""
    name = name.strip()
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_. ")
    if len(name) > max_len:
        name = name[:max_len].rstrip("_. ")
    return name or "unnamed"


def _filename_from_response(url: str, headers: dict) -> str:
    """Derive a filename from Content-Disposition or the URL path."""
    # Try Content-Disposition first
    cd = headers.get("Content-Disposition", "")
    match = re.search(r'filename\*?=["\']?([^"\';\r\n]+)', cd)
    if match:
        return _sanitise_name(unquote(match.group(1).strip()))

    # Fall back to URL path
    path = unquote(urlparse(url).path)
    basename = path.rsplit("/", 1)[-1]
    return _sanitise_name(basename) if basename else "download"


async def download_files(
    files_data: list[dict],
    subject_name: str,
    unit_name: str,
    cookies: list[dict] | None = None,
) -> dict:
    """Download every file described in *files_data* (the output of
    ``extract_links``) into organised folders under ``downloads/``.

    Parameters
    ----------
    files_data : list[dict]
        Each element has the shape::

            {"content_type": "Slides",
             "files": [{"name": "file.pdf", "url": "https://..."}]}

    subject_name : str
        Human-readable subject name (used as a folder name).
    unit_name : str
        Human-readable unit name (used as a folder name).
    cookies : list[dict], optional
        Playwright-format cookies to send with requests (for authenticated downloads).

    Returns
    -------
    dict
        ``{"downloaded": int, "skipped": int, "failed": int}``
    """

    downloaded = 0
    skipped = 0
    failed = 0

    # Build a cookie jar from Playwright cookies
    jar = aiohttp.CookieJar()
    if cookies:
        for c in cookies:
            jar.update_cookies(
                {c["name"]: c["value"]},
                response_url=yarl.URL(f"https://{c.get('domain', 'www.pesuacademy.com')}"),
            )

    async with aiohttp.ClientSession(cookie_jar=jar) as session:
        for group in files_data:
            content_type = group.get("content_type", "General")
            files = group.get("files", [])

            if not files:
                print(f"[downloader] No files for '{content_type}' — skipping group.")
                continue

            # Build target directory
            target_dir = (
                DOWNLOADS_DIR
                / _sanitise_name(subject_name)
                / _sanitise_name(unit_name)
                / _sanitise_name(content_type)
            )
            # Use \\?\ prefix on Windows to support long paths
            target_dir = Path(f"\\\\?\\{target_dir.resolve()}")
            target_dir.mkdir(parents=True, exist_ok=True)
            print(f"[downloader] Saving '{content_type}' files to: {target_dir}")

            for file_info in files:
                url = file_info.get("url", "")
                name = _sanitise_name(file_info.get("name", "")) or "download"

                if not url:
                    print(f"[downloader]   Skipping entry with empty URL.")
                    skipped += 1
                    continue

                dest = target_dir / name

                # Duplicate check
                if dest.exists():
                    print(f"[downloader]   '{name}' already exists — skipped.")
                    skipped += 1
                    continue

                # Download
                print(f"[downloader]   Downloading {name}...", end=" ", flush=True)
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                        if resp.status != 200:
                            print(f"HTTP {resp.status} — failed.")
                            failed += 1
                            continue

                        # Always try to get a better filename from Content-Disposition
                        better_name = _filename_from_response(url, dict(resp.headers))
                        if better_name not in ("download", "unnamed"):
                            # Use the server-provided name but keep our prefix
                            # e.g. "classname — server_name.pdf"
                            ext = Path(better_name).suffix
                            if ext and not Path(name).suffix:
                                name = name + ext
                                dest = target_dir / _sanitise_name(name)
                        elif name in ("download", "unnamed"):
                            name = better_name
                            dest = target_dir / _sanitise_name(name)

                        if dest.exists():
                            print(f"'{_sanitise_name(name)}' already exists — skipped.")
                            skipped += 1
                            continue

                        # Stream to disk
                        with open(dest, "wb") as f:
                            async for chunk in resp.content.iter_chunked(8192):
                                f.write(chunk)

                    print("Done.")
                    downloaded += 1

                except Exception as e:
                    print(f"Error: {e}")
                    failed += 1
                    # Clean up partial file
                    if dest.exists():
                        try:
                            os.remove(dest)
                        except OSError:
                            pass

    summary = {"downloaded": downloaded, "skipped": skipped, "failed": failed}
    print(
        f"[downloader] Finished — downloaded: {downloaded}, "
        f"skipped: {skipped}, failed: {failed}"
    )
    return summary
