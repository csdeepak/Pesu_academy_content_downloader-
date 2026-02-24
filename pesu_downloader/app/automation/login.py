"""
login.py — PESU Academy login automation.
"""

import logging

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

PESU_URL = "https://www.pesuacademy.com/Academy/"


async def login(page: Page, username: str, password: str) -> bool:
    """Log in to PESU Academy using the provided Playwright *page*.

    Returns True on success, False on failure.
    """
    try:
        # 1. Navigate to the login page
        logger.info("Navigating to PESU Academy...")
        await page.goto(PESU_URL, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=15000)
        logger.info("Page loaded.")

        # 2. Wait for the username input field
        logger.info("Waiting for username field...")
        username_sel = "input#j_scriptusername"
        await page.wait_for_selector(username_sel, state="visible", timeout=15000)

        # 3. Fill in credentials
        logger.info("Entering credentials...")
        await page.fill(username_sel, username)

        password_sel = "input[name='j_password']"
        await page.wait_for_selector(password_sel, state="visible", timeout=10000)
        await page.fill(password_sel, password)
        logger.info("Credentials filled.")

        # 4. Click the Sign In button
        #    Actual id: "postloginform#/Academy/j_spring_security_check"
        #    It has onclick="javascript:loadUserData();"
        logger.info("Clicking Sign In button...")
        sign_in_btn = "button#postloginform\\#\\/Academy\\/j_spring_security_check"
        try:
            await page.wait_for_selector(sign_in_btn, timeout=5000)
            await page.click(sign_in_btn)
        except PlaywrightTimeout:
            # Fallback: click by text
            logger.warning("CSS selector failed, trying text selector...")
            await page.click("button:has-text('Sign In')")

        logger.info("Sign In clicked.")

        # 5. Wait for navigation / post-login page load
        logger.info("Waiting for post-login navigation...")
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except PlaywrightTimeout:
            pass  # some pages never fully settle

        # 6. Verify login success
        current_url = page.url
        logger.info(f"Current URL: {current_url}")

        # Quick-fail: PESU redirects to ?authfailed=<code> on bad credentials
        if "authfailed" in current_url:
            logger.warning("URL contains 'authfailed' — invalid credentials.")
            return False

        # Look for known post-login elements (semester dropdown, menu, profile, etc.)
        dashboard_selectors = [
            "#menuTab",                         # main menu tabs
            ".menu-item",                       # menu items
            "a.menu-link",                      # nav links
            ".navbar-nav",                      # bootstrap nav
            "#sideNavbar",                      # side nav
            "#semesterSubId",                   # semester dropdown (courses page)
            "select[name='semesterSubId']",     # semester dropdown alt
            ".profile-img",                     # profile picture
            ".fa-power-off",                    # logout icon
        ]
        combined_sel = ", ".join(dashboard_selectors)
        try:
            await page.wait_for_selector(combined_sel, state="visible", timeout=15000)
            logger.info("Dashboard element detected — login successful!")
            return True
        except PlaywrightTimeout:
            # Extra check: look for error messages on the login page
            error_text = await page.text_content(".login-error, .error-msg, .alert-danger") or ""
            if error_text.strip():
                logger.error(f"Login error displayed: {error_text.strip()}")
            else:
                # Dump a snippet of the page so we can debug further
                title = await page.title()
                logger.info(f"Page title: {title}")
                logger.info(f"URL: {page.url}")
            logger.warning("Dashboard element not found — login failed.")
            return False

    except PlaywrightTimeout as e:
        logger.error(f"Timeout during login: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during login: {type(e).__name__}: {e}")
        return False
