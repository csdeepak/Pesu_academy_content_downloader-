"""
navigator.py — Navigate PESU Academy to discover courses, units and content.

Real page structure (discovered via debug inspection):
  - After login  → studentProfilePESU (Profile | Home)
  - Click "My Courses" sidebar link (href=javascript:void(0))
  - Courses page  → select#semesters, course rows in div[id^='rowWiseCourseContent_']
  - Click a course → studentCourseDetailsSemWise page
      Level-1 tabs: Introduction | Course Units | Objectives | …
      Level-2 tabs: unit names (horizontal, under Course Units)
      Level-3: content table with columns Class | AV Summary | Live Videos | Slides | Notes | …
"""

from __future__ import annotations

import os
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

# Where to save debug screenshots
_DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "downloads" / "debug"


# ──────────────────────────────────────────────────────────────
# Debug helper
# ──────────────────────────────────────────────────────────────

async def debug_page(page: Page, label: str) -> None:
    """Log URL + title and save a screenshot for debugging."""
    try:
        _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        url = page.url
        title = await page.title()
        print(f"[debug] [{label}] URL : {url}", flush=True)
        print(f"[debug] [{label}] Title: {title}", flush=True)
        path = _DEBUG_DIR / f"debug_{label}.png"
        await page.screenshot(path=str(path), full_page=True)
        print(f"[debug] [{label}] Screenshot → {path}", flush=True)
    except Exception as exc:
        print(f"[debug] [{label}] screenshot failed: {exc}", flush=True)


# ──────────────────────────────────────────────────────────────
# 1. go_to_my_courses
# ──────────────────────────────────────────────────────────────

async def go_to_my_courses(page: Page) -> None:
    """Click the sidebar "My Courses" link and wait for the listing."""
    print("[nav] Navigating to My Courses…", flush=True)

    link = page.locator("a:has-text('My Courses')").first
    await link.wait_for(state="visible", timeout=10_000)
    await link.click()
    print("[nav] Clicked 'My Courses' link.", flush=True)

    # Wait for the courses table or the semester dropdown to appear
    await page.wait_for_selector(
        "div[id^='rowWiseCourseContent_'], select#semesters",
        state="visible", timeout=15_000,
    )
    # Let the AJAX content settle
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeout:
        pass

    await debug_page(page, "my_courses")
    print("[nav] My Courses page loaded.", flush=True)


# ──────────────────────────────────────────────────────────────
# 2. get_courses
# ──────────────────────────────────────────────────────────────

async def get_courses(page: Page) -> list[dict]:
    """Scrape all visible courses on the My Courses page.

    The courses are ``<tr id="rowWiseCourseContent_NNNNN">`` rows inside
    a table within ``#getStudentSubjectsBasedOnSemesters``.  Each row has
    ``onclick="clickOnCourseContent('NNNNN', event)"``.

    Returns [{"id": "21631",
              "name": "UE23CS320B — Capstone Project Phase - II"}, …]
    """
    print("[nav] Scraping course list…", flush=True)

    courses: list[dict] = await page.evaluate("""() => {
        // The rows are <tr id="rowWiseCourseContent_21631" onclick="clickOnCourseContent('21631', event)">
        const rows = document.querySelectorAll("tr[id^='rowWiseCourseContent_']");
        return Array.from(rows).map(row => {
            // Extract subject ID from the row id: rowWiseCourseContent_21631 → 21631
            const sid = row.id.replace('rowWiseCourseContent_', '');
            const cells = row.querySelectorAll('td');
            let code = '', title = '';
            if (cells.length >= 2) {
                code  = (cells[0].innerText || '').trim();
                title = (cells[1].innerText || '').trim();
            }
            const display = code && title ? code + ' \u2014 ' + title : (title || code);
            return { id: sid, name: display };
        });
    }""")

    courses = [c for c in courses if c.get("name")]
    print(f"[nav] Found {len(courses)} course(s).", flush=True)
    for c in courses:
        print(f"[nav]   • {c['name']}", flush=True)
    return courses


# ──────────────────────────────────────────────────────────────
# 3. get_units  (click course → Course Units tab → scrape unit tabs)
# ──────────────────────────────────────────────────────────────

async def get_units(page: Page, course_id: str) -> list[dict]:
    """Click the course row, click 'Course Units' tab, then scrape
    the unit tabs that appear underneath.

    *course_id* is a subject numeric id, e.g. ``"21631"``.
    The page has ``onclick="clickOnCourseContent('21631', event)"``.

    Returns [{"id": "0", "name": "Introduction to Deep Learning"}, …]
    """
    print(f"[nav] Clicking course '{course_id}'…", flush=True)

    # Call the site's own JS function to open the course detail
    try:
        await page.evaluate(f"clickOnCourseContent('{course_id}', new Event('click'))")
        print(f"[nav] Called clickOnCourseContent('{course_id}').", flush=True)
    except Exception as e:
        print(f"[nav] JS call failed ({e}), trying row click…", flush=True)
        try:
            row = page.locator(f"#rowWiseCourseContent_{course_id}")
            await row.click()
        except Exception as e2:
            print(f"[nav] Row click also failed: {e2}", flush=True)

    # Wait for the course detail page to load (Level-1 tabs)
    print("[nav] Waiting for course detail page…", flush=True)
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeout:
        pass

    await debug_page(page, "course_detail")

    # Click the "Course Units" tab (Level-1)
    print("[nav] Looking for 'Course Units' tab…", flush=True)
    course_units_tab = page.locator("a:has-text('Course Units'), li:has-text('Course Units') a").first
    try:
        await course_units_tab.wait_for(state="visible", timeout=10_000)
        await course_units_tab.click()
        print("[nav] Clicked 'Course Units' tab.", flush=True)
    except PlaywrightTimeout:
        print("[nav] 'Course Units' tab not found – may already be active.", flush=True)

    # Wait for Level-2 unit tabs to appear
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeout:
        pass

    await debug_page(page, "course_units")

    # Scrape all Level-2 unit tabs from ul#courselistunit
    # This is the specific container inside the "Course Units" tab pane (#course_3)
    # Each tab: <a data-toggle="tab" href="#courseUnit_65658" onclick="handleclassUnit('65658')">
    units: list[dict] = await page.evaluate("""() => {
        const unitList = document.getElementById('courselistunit');
        if (!unitList) return [];
        const links = unitList.querySelectorAll('li a');
        return Array.from(links).map((a, idx) => ({
            id: String(idx),
            name: (a.innerText || '').trim()
        }));
    }""")

    units = [u for u in units if u.get("name")]
    print(f"[nav] Found {len(units)} unit(s).", flush=True)
    for u in units:
        print(f"[nav]   • [{u['id']}] {u['name']}", flush=True)
    return units


# ──────────────────────────────────────────────────────────────
# 4. click_unit  (click a Level-2 tab and wait for content table)
# ──────────────────────────────────────────────────────────────

async def click_unit(page: Page, unit_index: int) -> dict:
    """Click the unit tab at *unit_index* and return a mapping of
    content-type column headers to their column indices.

    Returns e.g. {"Slides": 3, "Notes": 4, "Assignments": 5, …}
    """
    print(f"[nav] Clicking unit tab index {unit_index}…", flush=True)

    # Re-discover the unit tabs from ul#courselistunit and click the one at unit_index
    clicked = await page.evaluate("""(idx) => {
        const unitList = document.getElementById('courselistunit');
        if (!unitList) return false;
        const links = Array.from(unitList.querySelectorAll('li a'));
        if (idx < links.length) {
            links[idx].click();
            return true;
        }
        return false;
    }""", unit_index)

    if not clicked:
        print(f"[nav] Unit tab at index {unit_index} not found!", flush=True)
        return {}

    # Wait for the content table to appear
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeout:
        pass

    await debug_page(page, f"unit_{unit_index}")

    # Read the table headers to build a column mapping
    col_map: dict = await page.evaluate("""() => {
        const tables = document.querySelectorAll('table');
        for (const table of tables) {
            const ths = table.querySelectorAll('thead th, tr:first-child th');
            if (ths.length > 2) {
                const map = {};
                ths.forEach((th, i) => {
                    const text = (th.innerText || '').trim();
                    if (text) map[text] = i;
                });
                return map;
            }
        }
        return {};
    }""")

    print(f"[nav] Content table columns: {col_map}", flush=True)
    return col_map
