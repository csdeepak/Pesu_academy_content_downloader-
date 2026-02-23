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
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeout:
        pass

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
    logger.info("Clicking course '%s'…", course_id)

    # Call the site's own JS function to open the course detail
    try:
        await page.evaluate(f"clickOnCourseContent('{course_id}', new Event('click'))")
        logger.info("Called clickOnCourseContent('%s').", course_id)
    except Exception as e:
        logger.warning("JS call failed (%s), trying row click…", e)
        try:
            row = page.locator(f"#rowWiseCourseContent_{course_id}")
            await row.click()
        except Exception as e2:
            logger.error("Row click also failed: %s", e2)

    # Wait for the course detail page to load (Level-1 tabs)
    logger.info("Waiting for course detail page…")
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeout:
        pass

    # Click the "Course Units" tab (Level-1)
    logger.info("Looking for 'Course Units' tab…")
    course_units_tab = page.locator("a:has-text('Course Units'), li:has-text('Course Units') a").first
    try:
        await course_units_tab.wait_for(state="visible", timeout=10_000)
        await course_units_tab.click()
        logger.info("Clicked 'Course Units' tab.")
    except PlaywrightTimeout:
        logger.info("'Course Units' tab not found – may already be active.")

    # Wait for Level-2 unit tabs to appear
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeout:
        pass

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
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
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
