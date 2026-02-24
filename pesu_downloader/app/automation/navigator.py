"""
navigator.py — Navigate PESU Academy to discover courses, units and content.

Real page structure (discovered via inspection):
  - After login  → studentProfilePESU (Profile | Home)
  - Click "My Courses" sidebar link (href=javascript:void(0))
  - Courses page  → select#semesters, course rows in div[id^='rowWiseCourseContent_']
  - Click a course → studentCourseDetailsSemWise page
      Level-1 tabs: Introduction | Course Units | Objectives | …
      Level-2 tabs: unit names (horizontal, under Course Units)
      Level-3: content table with columns Class | AV Summary | Live Videos | Slides | Notes | …
"""

from __future__ import annotations

import asyncio
import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 1. go_to_my_courses
# ──────────────────────────────────────────────────────────────

async def go_to_my_courses(page: Page) -> None:
    """Click the sidebar "My Courses" link and wait for the listing."""
    logger.info("Navigating to My Courses…")

    link = page.locator("a:has-text('My Courses')").first
    await link.wait_for(state="visible", timeout=10_000)
    await link.click()
    logger.info("Clicked 'My Courses' link.")

    # Wait for the courses table or the semester dropdown to appear
    await page.wait_for_selector(
        "div[id^='rowWiseCourseContent_'], select#semesters",
        state="visible", timeout=15_000,
    )
    # Let the AJAX content settle
    try:
        await page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeout:
        pass

    # The semester dropdown may appear before course rows are loaded.
    # Wait explicitly for at least one course row to show up.
    try:
        await page.wait_for_selector(
            "tr[id^='rowWiseCourseContent_']",
            state="visible", timeout=8_000,
        )
    except PlaywrightTimeout:
        # Course rows didn't appear — possibly needs a semester to be selected,
        # or they're still loading.  Give extra time.
        logger.warning("No course rows yet — waiting a bit longer…")
        await asyncio.sleep(2)

    logger.info("My Courses page loaded.")


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
    logger.info("Scraping course list…")

    # Retry up to 3 times (AJAX may still be loading)
    for attempt in range(3):
        courses: list[dict] = await page.evaluate("""() => {
            const rows = document.querySelectorAll("tr[id^='rowWiseCourseContent_']");
            return Array.from(rows).map(row => {
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
        if courses:
            break
        logger.warning("Attempt %d: 0 courses found, waiting 2s…", attempt + 1)

        # Log what we DO see on the page for diagnostics
        if attempt == 0:
            diag = await page.evaluate("""() => {
                const url = window.location.href;
                const semSel = document.querySelector('select#semesters');
                const semVal = semSel ? semSel.value : 'N/A';
                const semOpts = semSel ? Array.from(semSel.options).map(o => o.text) : [];
                const divs = document.querySelectorAll("div[id^='rowWiseCourseContent_']");
                const trs = document.querySelectorAll("tr[id^='rowWiseCourseContent_']");
                const tables = document.querySelectorAll("table");
                return {
                    url, semVal, semOpts: semOpts.slice(0, 10),
                    divCount: divs.length, trCount: trs.length, tableCount: tables.length,
                    bodySnippet: document.body.innerText.substring(0, 500)
                };
            }""")
            logger.info("Page diagnostics: %s", diag)

        await asyncio.sleep(2)
    logger.info("Found %d course(s).", len(courses))
    for c in courses:
        logger.debug("  • %s", c['name'])
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
    logger.info("Loading units for course '%s'…", course_id)

    # ── Step 0: Make sure we're on the My Courses page ──
    # If the course row doesn't exist in the DOM, we're on a different page
    # (e.g. a previously-selected course detail). Navigate back first.
    row_exists = await page.evaluate(
        f"!!document.getElementById('rowWiseCourseContent_{course_id}')"
    )
    if not row_exists:
        logger.info("Course row not in DOM — navigating back to My Courses…")
        await go_to_my_courses(page)
        # Re-check after navigating
        row_exists = await page.evaluate(
            f"!!document.getElementById('rowWiseCourseContent_{course_id}')"
        )
        if not row_exists:
            logger.error("Course row still not found after navigating to My Courses!")
            return []

    # ── Step 1: Click the course row using Playwright's real mouse click ──
    # Playwright's locator.click() dispatches a real mouse event at the center
    # of the element, hitting a <td> inside the <tr>.  This gives the site's
    # clickOnCourseContent() a proper event.target with a tagName.
    logger.info("Clicking course row '%s'…", course_id)
    row = page.locator(f"#rowWiseCourseContent_{course_id}")
    await row.click(timeout=5_000)

    # Wait for the course detail page to load
    await asyncio.sleep(1.5)
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeout:
        pass

    # ── Step 2: Click the "Course Units" tab (Level-1) ──
    course_units_tab = page.locator("a:has-text('Course Units'), li:has-text('Course Units') a").first
    try:
        await course_units_tab.wait_for(state="visible", timeout=5_000)
        await course_units_tab.click()
        logger.info("Clicked 'Course Units' tab.")
    except PlaywrightTimeout:
        logger.info("'Course Units' tab not found – may already be active.")

    # Wait for the unit tabs to appear
    try:
        await page.wait_for_selector("#courselistunit", state="visible", timeout=8_000)
    except PlaywrightTimeout:
        pass
    await asyncio.sleep(0.5)

    # ── Step 3: Scrape all Level-2 unit tabs from ul#courselistunit ──
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
    logger.info("Found %d unit(s).", len(units))
    for u in units:
        logger.debug("  • [%s] %s", u['id'], u['name'])
    return units


# ──────────────────────────────────────────────────────────────
# 4. click_unit  (click a Level-2 tab and wait for content table)
# ──────────────────────────────────────────────────────────────

async def click_unit(page: Page, unit_index: int) -> dict:
    """Click the unit tab at *unit_index* and return a mapping of
    content-type column headers to their column indices.

    Returns e.g. {"Slides": 3, "Notes": 4, "Assignments": 5, …}
    """
    logger.info("Clicking unit tab index %d…", unit_index)

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
        logger.warning("Unit tab at index %d not found!", unit_index)
        return {}

    # Wait for the content table to appear
    await asyncio.sleep(0.5)
    try:
        await page.wait_for_load_state("networkidle", timeout=6_000)
    except PlaywrightTimeout:
        pass

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

    logger.info("Content table columns: %s", col_map)
    return col_map
