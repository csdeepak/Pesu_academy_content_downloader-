"""
navigator.py — Navigate PESU Academy pages to discover semesters, subjects, and units.
"""

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout


# ---------------------------------------------------------------------------
# 1. get_semesters
# ---------------------------------------------------------------------------

async def get_semesters(page: Page) -> list[dict]:
    """Navigate to My Courses and return all semester options.

    Returns a list of dicts: [{"value": "...", "label": "..."}, ...]
    """
    try:
        # Navigate to the courses / dashboard section
        print("[navigator] Navigating to My Courses...")
        courses_selector = "a[href*='Courses'], a:has-text('Courses'), .menu-link:has-text('Course')"
        try:
            await page.wait_for_selector(courses_selector, state="visible", timeout=10000)
            await page.click(courses_selector)
            print("[navigator] Clicked on Courses link.")
        except PlaywrightTimeout:
            print("[navigator] Courses link not found — may already be on courses page.")

        await page.wait_for_load_state("domcontentloaded", timeout=15000)

        # Locate the semester dropdown
        print("[navigator] Looking for semester dropdown...")
        dropdown_selector = "select#semesterSubId, select[name='semesterSubId'], select.semester-dropdown"
        try:
            await page.wait_for_selector(dropdown_selector, state="visible", timeout=10000)
        except PlaywrightTimeout:
            print("[navigator] Semester dropdown not found.")
            return []

        print("[navigator] Semester dropdown found. Extracting options...")

        options = await page.eval_on_selector_all(
            f"{dropdown_selector} option",
            """(elements) => elements.map(el => ({
                value: el.value,
                label: el.textContent.trim()
            }))""",
        )

        # Filter out placeholder / empty options
        semesters = [opt for opt in options if opt.get("value")]
        print(f"[navigator] Found {len(semesters)} semester(s): {[s['label'] for s in semesters]}")
        return semesters

    except PlaywrightTimeout as e:
        print(f"[navigator] Timeout in get_semesters: {e}")
        return []
    except Exception as e:
        print(f"[navigator] Error in get_semesters: {e}")
        return []


# ---------------------------------------------------------------------------
# 2. get_subjects
# ---------------------------------------------------------------------------

async def get_subjects(page: Page, semester_value: str) -> list[dict]:
    """Select a semester from the dropdown and return the list of subjects.

    Returns a list of dicts: [{"id": "...", "name": "..."}, ...]
    """
    try:
        # Select the semester
        print(f"[navigator] Selecting semester '{semester_value}'...")
        dropdown_selector = "select#semesterSubId, select[name='semesterSubId'], select.semester-dropdown"
        try:
            await page.wait_for_selector(dropdown_selector, state="visible", timeout=10000)
        except PlaywrightTimeout:
            print("[navigator] Semester dropdown not found.")
            return []

        await page.select_option(dropdown_selector, value=semester_value)
        print(f"[navigator] Semester '{semester_value}' selected.")

        # Wait for the subject list to update dynamically
        print("[navigator] Waiting for subject list to load...")
        subject_container_selector = (
            ".course-listing, .subject-list, "
            "div[class*='course'], div[class*='subject'], "
            "table.table tbody tr"
        )
        try:
            await page.wait_for_selector(subject_container_selector, state="visible", timeout=15000)
        except PlaywrightTimeout:
            print("[navigator] Subject list did not appear after selecting semester.")
            return []

        print("[navigator] Subject list visible. Extracting subjects...")

        # Try extracting from table rows first (common PESU pattern)
        subjects = await page.eval_on_selector_all(
            subject_container_selector,
            """(elements) => elements.map((el, index) => {
                const id = el.getAttribute('data-id')
                          || el.getAttribute('id')
                          || el.querySelector('a')?.getAttribute('data-id')
                          || String(index);
                const name = el.textContent.trim();
                return { id: id, name: name };
            })""",
        )

        # Filter out empty entries
        subjects = [s for s in subjects if s.get("name")]
        print(f"[navigator] Found {len(subjects)} subject(s): {[s['name'] for s in subjects]}")
        return subjects

    except PlaywrightTimeout as e:
        print(f"[navigator] Timeout in get_subjects: {e}")
        return []
    except Exception as e:
        print(f"[navigator] Error in get_subjects: {e}")
        return []


# ---------------------------------------------------------------------------
# 3. get_units
# ---------------------------------------------------------------------------

async def get_units(page: Page, subject_id: str) -> list[dict]:
    """Click on a subject and return the list of units / tabs.

    Returns a list of dicts: [{"id": "...", "name": "..."}, ...]
    """
    try:
        # Click the subject element
        print(f"[navigator] Clicking subject with id '{subject_id}'...")
        subject_selector = (
            f"[data-id='{subject_id}'], "
            f"#{subject_id}, "
            f"a[data-id='{subject_id}'], "
            f"tr[data-id='{subject_id}']"
        )
        try:
            await page.wait_for_selector(subject_selector, state="visible", timeout=10000)
            await page.click(subject_selector)
            print("[navigator] Subject clicked.")
        except PlaywrightTimeout:
            # Fallback: try clicking by index (subject_id might be a numeric index)
            print(f"[navigator] Selector not found. Trying to click by row index...")
            row_selector = f"table.table tbody tr:nth-child({int(subject_id) + 1})"
            try:
                await page.wait_for_selector(row_selector, state="visible", timeout=5000)
                await page.click(row_selector)
                print("[navigator] Subject row clicked via index fallback.")
            except (PlaywrightTimeout, ValueError):
                print("[navigator] Could not locate the subject element.")
                return []

        # Wait for unit tabs / sections to load
        print("[navigator] Waiting for unit tabs to load...")
        unit_selector = (
            ".nav-tabs li, .unit-tab, "
            "ul.nav li a, "
            "div[class*='unit'], div[class*='tab']"
        )
        try:
            await page.wait_for_selector(unit_selector, state="visible", timeout=15000)
        except PlaywrightTimeout:
            print("[navigator] Unit tabs did not appear.")
            return []

        print("[navigator] Unit tabs visible. Extracting units...")

        units = await page.eval_on_selector_all(
            unit_selector,
            """(elements) => elements.map((el, index) => {
                const id = el.getAttribute('data-id')
                          || el.getAttribute('id')
                          || el.querySelector('a')?.getAttribute('data-id')
                          || String(index);
                const name = (el.textContent || '').trim();
                return { id: id, name: name };
            })""",
        )

        # Filter out empty entries
        units = [u for u in units if u.get("name")]
        print(f"[navigator] Found {len(units)} unit(s): {[u['name'] for u in units]}")
        return units

    except PlaywrightTimeout as e:
        print(f"[navigator] Timeout in get_units: {e}")
        return []
    except Exception as e:
        print(f"[navigator] Error in get_units: {e}")
        return []
