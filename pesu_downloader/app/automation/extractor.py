"""
extractor.py — Extract downloadable file links from PESU Academy unit tabs.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, unquote

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout


# File extensions we consider downloadable
_DOWNLOADABLE_EXT = re.compile(
    r"\.(pdf|pptx?|docx?|xlsx?|zip|rar|7z|txt|csv|png|jpe?g|gif|mp4|mkv|avi)$",
    re.IGNORECASE,
)


def _filename_from_url(url: str) -> str:
    """Best-effort filename extraction from a URL."""
    path = unquote(urlparse(url).path)
    return path.rsplit("/", 1)[-1] or "unknown"


def _is_real_file_url(url: str) -> bool:
    """Return True if the URL looks like a direct file link rather than a
    viewer wrapper."""
    if not url:
        return False
    # Reject obvious viewer / wrapper pages
    viewer_patterns = ("docs.google.com/viewer", "drive.google.com/file",
                       "/ViewContent", "/viewContent")
    if any(vp in url for vp in viewer_patterns):
        return False
    return True


async def _extract_links_from_dom(page: Page) -> list[dict]:
    """Scan the visible DOM for downloadable anchors / buttons / embedded
    file links and return a list of {name, url} dicts."""

    results: list[dict] = []

    # 1. Anchor tags with href
    anchors = await page.eval_on_selector_all(
        "a[href]",
        """(els) => els.map(el => ({
            href: el.href,
            text: (el.textContent || '').trim(),
            download: el.getAttribute('download') || ''
        }))""",
    )
    for a in anchors:
        href = a.get("href", "")
        if not href or href.startswith("javascript:") or href == "#":
            continue
        name = a.get("download") or a.get("text") or _filename_from_url(href)
        results.append({"name": name, "url": href})

    # 2. Embedded objects / iframes pointing at files
    embeds = await page.eval_on_selector_all(
        "iframe[src], embed[src], object[data]",
        """(els) => els.map(el => ({
            src: el.src || el.getAttribute('data') || ''
        }))""",
    )
    for em in embeds:
        src = em.get("src", "")
        if src and _DOWNLOADABLE_EXT.search(src):
            results.append({"name": _filename_from_url(src), "url": src})

    # 3. Buttons / elements with onclick containing URLs
    onclick_els = await page.eval_on_selector_all(
        "[onclick]",
        """(els) => els.map(el => ({
            onclick: el.getAttribute('onclick') || '',
            text: (el.textContent || '').trim()
        }))""",
    )
    url_in_onclick = re.compile(r"""(?:window\.open|location\.href)\s*[=(]\s*['"]([^'"]+)['"]""")
    for oc in onclick_els:
        match = url_in_onclick.search(oc.get("onclick", ""))
        if match:
            url = match.group(1)
            name = oc.get("text") or _filename_from_url(url)
            results.append({"name": name, "url": url})

    return results


async def _intercept_xhr_files(page: Page, action) -> list[dict]:
    """Run *action* (an async callable) while listening for network
    responses that look like file downloads.  Returns a list of
    {name, url} dicts captured via XHR / fetch."""

    captured: list[dict] = []

    async def _on_response(response):
        url = response.url
        content_type = response.headers.get("content-type", "")
        content_disp = response.headers.get("content-disposition", "")

        is_file = (
            _DOWNLOADABLE_EXT.search(url)
            or "application/octet-stream" in content_type
            or "application/pdf" in content_type
            or "attachment" in content_disp
        )
        if is_file:
            name = _filename_from_url(url)
            # Try to pull a better name from Content-Disposition
            cd_match = re.search(r'filename\*?=["\']?([^"\';\r\n]+)', content_disp)
            if cd_match:
                name = unquote(cd_match.group(1).strip())
            captured.append({"name": name, "url": url})

    page.on("response", _on_response)
    try:
        await action()
    finally:
        page.remove_listener("response", _on_response)

    return captured


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract_links(
    page: Page,
    unit_id: str,
    content_types: list[str],
) -> list[dict]:
    """Iterate over *content_types* tabs inside a unit and extract all
    downloadable file links.

    Returns::

        [
            {
                "content_type": "Slides",
                "files": [{"name": "file.pdf", "url": "https://..."}]
            },
            ...
        ]
    """
    all_content: list[dict] = []

    for ctype in content_types:
        print(f"[extractor] Processing content type: {ctype}...")
        files: list[dict] = []

        try:
            # --- Locate and click the tab for this content type --------
            # Try several common selector patterns
            tab_selector = (
                f"a:has-text('{ctype}'), "
                f"li:has-text('{ctype}') a, "
                f"button:has-text('{ctype}'), "
                f"div.tab:has-text('{ctype}'), "
                f"span:has-text('{ctype}')"
            )
            try:
                await page.wait_for_selector(tab_selector, state="visible", timeout=5000)
            except PlaywrightTimeout:
                print(f"[extractor] Tab '{ctype}' not found — skipping.")
                all_content.append({"content_type": ctype, "files": []})
                continue

            # Click while intercepting network responses
            async def _click_tab():
                await page.click(tab_selector)
                # Wait for content area to settle
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except PlaywrightTimeout:
                    # networkidle can be flaky; fall back to a shorter wait
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)

            print(f"[extractor] Clicking '{ctype}' tab and intercepting network requests...")
            xhr_files = await _intercept_xhr_files(page, _click_tab)
            if xhr_files:
                print(f"[extractor]   Captured {len(xhr_files)} file(s) via network interception.")
                files.extend(xhr_files)

            # --- Extract links from the DOM after tab content loads -----
            print(f"[extractor] Scanning DOM for downloadable links...")
            dom_files = await _extract_links_from_dom(page)

            # Keep only real file URLs and deduplicate
            seen_urls: set[str] = {f["url"] for f in files}
            for f in dom_files:
                if f["url"] not in seen_urls and _is_real_file_url(f["url"]):
                    files.append(f)
                    seen_urls.add(f["url"])

            if files:
                print(f"[extractor]   Total files found for '{ctype}': {len(files)}")
            else:
                print(f"[extractor]   No files found for '{ctype}'.")

        except PlaywrightTimeout as e:
            print(f"[extractor] Timeout while processing '{ctype}': {e}")
        except Exception as e:
            print(f"[extractor] Error while processing '{ctype}': {e}")

        all_content.append({"content_type": ctype, "files": files})

    print(f"[extractor] Extraction complete. {sum(len(c['files']) for c in all_content)} file(s) across {len(all_content)} content type(s).")
    return all_content
