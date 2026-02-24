"""
extractor.py — Extract downloadable file links from PESU Academy content tables.

PESU Academy content flow:
  1. Content table has rows (classes) with columns (AV Summary, Slides, Notes, …)
  2. Non-empty cells have onclick: handleclasscoursecontentunit(classId, subjectId, unitId, classOrder, typeId, event)
  3. Clicking navigates to a CLASS DETAIL page with content-type tabs
  4. Inside each tab, files are listed as: <div onclick="downloadcoursedoc('uuid')">filename</div>
  5. downloadcoursedoc() opens: referenceMeterials/downloadcoursedoc/{uuid}

Strategy:
  - Extract onclick params from every cell in one pass
  - For each class that has at least one requested content type, navigate once
  - On the detail page, click each requested content type tab
  - Extract all downloadcoursedoc UUIDs and file names
  - Build full download URLs
  - Navigate back to the content table

Everything runs in Playwright's dedicated event loop.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


# Content-type name → numeric ID as used by PESU Academy
_CONTENT_TYPE_IDS: dict[str, int] = {
    "AV Summary": 1,
    "Slides": 2,
    "Notes": 3,
    "Forums": 4,
    "Assignments": 5,
    "QB": 6,
    "QA": 7,
    "MCQs": 8,
    "References": 9,
    "Live Videos": 10,
}


# ──────────────────────────────────────────────────────────────
# Step 1 — Scan the content table for onclick parameters
# ──────────────────────────────────────────────────────────────

async def _scan_table_cells(
    page: Page,
    col_map: dict[str, int],
    content_types: list[str],
) -> list[dict]:
    """Extract onclick parameters from every non-empty cell.

    Returns a list of dicts:
    [
        {
            "rowIdx": 0,
            "className": "Introduction to TDL",
            "contentType": "Slides",
            "onclick": "handleclasscoursecontentunit('uuid','21642','65658','1',2,event)"
        }, …
    ]
    """
    # Build {colIdx: contentType} for the requested content types
    col_to_type: dict[int, str] = {}
    for ct in content_types:
        idx = col_map.get(ct)
        if idx is not None:
            col_to_type[idx] = ct

    if not col_to_type:
        logger.warning("None of the requested content types are in the table.")
        return []

    cells_data = await page.evaluate("""(colToType) => {
        const tables = document.querySelectorAll('table');
        const results = [];
        for (const table of tables) {
            const ths = table.querySelectorAll('thead th, tr:first-child th');
            if (ths.length <= 2) continue;

            const rows = table.querySelectorAll('tbody tr');
            for (let r = 0; r < rows.length; r++) {
                const cells = rows[r].querySelectorAll('td');
                const className = cells.length > 0 ? (cells[0].innerText || '').trim() : '';
                for (const [colIdxStr, contentType] of Object.entries(colToType)) {
                    const colIdx = parseInt(colIdxStr);
                    if (colIdx >= cells.length) continue;
                    const cell = cells[colIdx];
                    const text = (cell.innerText || '').trim();
                    if (text === '-' || text === '') continue;

                    // Get the onclick from the <a> inside the cell
                    const link = cell.querySelector('a[onclick]');
                    if (!link) continue;
                    const onclick = link.getAttribute('onclick') || '';
                    if (!onclick) continue;

                    results.push({ rowIdx: r, className, contentType, onclick });
                }
            }
            break;  // only process the first matching table
        }
        return results;
    }""", {str(k): v for k, v in col_to_type.items()})

    logger.info(f"Found {len(cells_data)} non-empty cell(s) across {len(content_types)} content type(s).")
    return cells_data


# ──────────────────────────────────────────────────────────────
# Step 2 — Navigate to a class detail page and extract files
# ──────────────────────────────────────────────────────────────

async def _extract_files_from_detail_page(
    page: Page,
    content_type: str,
) -> list[dict]:
    """On the class detail page, click the *content_type* tab and
    extract all downloadcoursedoc UUIDs and file names.

    Returns [{name, url}, …]
    """
    type_id = _CONTENT_TYPE_IDS.get(content_type)
    if type_id is None:
        logger.warning(f"Unknown content type: {content_type}")
        return []

    # Click the correct content type tab
    tab_selector = f"#contentType_{type_id}"
    try:
        tab = page.locator(tab_selector)
        if await tab.count() > 0:
            await tab.click()
            await asyncio.sleep(1)
            try:
                await page.wait_for_load_state("networkidle", timeout=8_000)
            except PlaywrightTimeout:
                pass
    except Exception as e:
        logger.error(f"Could not click tab {tab_selector}: {e}")

    # Extract downloadcoursedoc UUIDs and file names from the active content
    files = await page.evaluate("""() => {
        const origin = window.location.origin;
        const basePath = '/Academy/s/referenceMeterials/downloadcoursedoc/';
        const results = [];

        // Find all elements with onclick containing 'downloadcoursedoc'
        const allElements = document.querySelectorAll('[onclick*="downloadcoursedoc"]');
        for (const el of allElements) {
            // Only consider visible elements
            if (el.offsetParent === null) continue;

            const onclick = el.getAttribute('onclick') || '';
            const match = onclick.match(/downloadcoursedoc\\(['"]([^'"]+)['"]/);
            if (match) {
                const uuid = match[1];
                const name = (el.innerText || el.textContent || '').trim() || uuid;
                results.push({
                    name: name,
                    url: origin + basePath + uuid
                });
            }
        }

        return results;
    }""")

    return files


# ──────────────────────────────────────────────────────────────
# Step 3 — Navigate back to the content table
# ──────────────────────────────────────────────────────────────

async def _navigate_back_to_units(
    page: Page,
    subject_id: str,
    unit_index: int,
) -> None:
    """Go back to the content table from the class detail page.

    Calls courseContentinfo(subjectId) to return to the course page,
    then clicks the unit tab at *unit_index* to show the content table.
    """
    logger.info(f"Navigating back to units (subject {subject_id}, unit {unit_index})…")

    # Call courseContentinfo to return to the course page
    try:
        await page.evaluate(f"courseContentinfo('{subject_id}')")
        await asyncio.sleep(1.5)
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except PlaywrightTimeout:
            pass
    except Exception as e:
        logger.error(f"courseContentinfo failed: {e}")

    # Wait for Course Units tab and click it
    try:
        course_units_tab = page.locator("a:has-text('Course Units')").first
        await course_units_tab.wait_for(state="visible", timeout=5_000)
        await course_units_tab.click()
        await asyncio.sleep(0.5)
    except Exception:
        pass

    # Click the unit tab
    try:
        await page.evaluate("""(idx) => {
            const unitList = document.getElementById('courselistunit');
            if (unitList) {
                const links = unitList.querySelectorAll('li a');
                if (idx < links.length) links[idx].click();
            }
        }""", unit_index)
        await asyncio.sleep(1)
        try:
            await page.wait_for_load_state("networkidle", timeout=8_000)
        except PlaywrightTimeout:
            pass
    except Exception as e:
        logger.error(f"Failed to click unit tab: {e}")


# ──────────────────────────────────────────────────────────────
# Public API — extract_content_from_table
# ──────────────────────────────────────────────────────────────

async def extract_content_from_table(
    page: Page,
    col_map: dict[str, int],
    content_types: list[str],
    unit_index: int = 0,
) -> list[dict]:
    """Extract downloadable links from the content table that is
    currently visible on the page.

    *col_map*: ``{"Class": 0, "Slides": 3, "Notes": 4, …}``
      — column-name → index mapping (from navigator.click_unit).
    *content_types*: list of column names to extract, e.g.
      ``["Slides", "Notes"]``.
    *unit_index*: index of the currently active unit tab (for navigating back).

    Returns::

        [
            {
                "content_type": "Slides",
                "files": [{"name": "Lecture_1.pdf", "url": "https://…"}, …]
            },
            …
        ]
    """
    # Step 1: Scan all cells for onclick data
    cells_data = await _scan_table_cells(page, col_map, content_types)

    if not cells_data:
        logger.info("No content found in the table.")
        return [{"content_type": ct, "files": []} for ct in content_types]

    # Extract subjectId from the first onclick
    subject_id = ""
    first_onclick = cells_data[0].get("onclick", "")
    # Pattern: handleclasscoursecontentunit('classUUID','subjectId','unitId',...)
    sid_match = re.search(r"handleclasscoursecontentunit\([^,]+,\s*'(\d+)'", first_onclick)
    if sid_match:
        subject_id = sid_match.group(1)
    logger.info(f"Subject ID: {subject_id}")

    # Group cells by (rowIdx, className) so we visit each class once
    # and collect all content types for that class in one visit
    classes: dict[int, dict] = {}  # rowIdx -> {className, types: {contentType: onclick}}
    for cell in cells_data:
        row = cell["rowIdx"]
        if row not in classes:
            classes[row] = {"className": cell["className"], "types": {}}
        classes[row]["types"][cell["contentType"]] = cell["onclick"]

    logger.info(f"Will visit {len(classes)} class(es).")

    # Collect files per content type
    files_by_type: dict[str, list[dict]] = {ct: [] for ct in content_types}

    for row_idx, class_info in sorted(classes.items()):
        class_name = class_info["className"]
        types_to_extract = class_info["types"]

        logger.info(f"Visiting class [{row_idx}] '{class_name}' ({len(types_to_extract)} type(s))…")

        # Navigate to the class detail page using the first available onclick
        # Replace 'event' with a dummy event object since we're calling from evaluate()
        first_onclick_js = next(iter(types_to_extract.values()))
        safe_js = first_onclick_js.replace(",event)", ",new Event('click'))")
        safe_js = safe_js.replace(", event)", ", new Event('click'))")
        try:
            await page.evaluate(safe_js)
            await asyncio.sleep(2)
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except PlaywrightTimeout:
                pass
        except Exception as e:
            logger.error(f"Failed to navigate to class: {e}")
            continue

        # For each content type in this class, click the tab and extract files
        for ctype, onclick in types_to_extract.items():
            logger.info(f"Extracting '{ctype}'…")
            try:
                found_files = await _extract_files_from_detail_page(page, ctype)
                # Prefix file names with class name
                for f in found_files:
                    f["name"] = f"{class_name} — {f['name']}"
                files_by_type[ctype].extend(found_files)
                logger.info(f"Found {len(found_files)} file(s).")
            except Exception as e:
                logger.error(f"Error extracting '{ctype}': {e}")

        # Navigate back to the content table
        await _navigate_back_to_units(page, subject_id, unit_index)

    # Build result
    all_content = []
    for ct in content_types:
        files = files_by_type.get(ct, [])
        all_content.append({"content_type": ct, "files": files})
        logger.info(f"'{ct}': {len(files)} file(s).")

    total = sum(len(c["files"]) for c in all_content)
    logger.info(f"Extraction complete. {total} file(s) total.")
    return all_content
