"""
login.py — PESU Academy login automation.
"""

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

PESU_URL = "https://www.pesuacademy.com/Academy/"


async def login(page: Page, username: str, password: str) -> bool:
    """Log in to PESU Academy using the provided Playwright *page*.

    Returns True on success, False on failure.
    """
    try:
        # 1. Navigate to the login page
        print("[login] Navigating to PESU Academy...", flush=True)
        await page.goto(PESU_URL, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=15000)
        print("[login] Page loaded.", flush=True)

        # 2. Wait for the username input field
        print("[login] Waiting for username field...", flush=True)
        username_sel = "input#j_scriptusername"
        await page.wait_for_selector(username_sel, state="visible", timeout=15000)

        # 3. Fill in credentials
        print("[login] Entering credentials...", flush=True)
        await page.fill(username_sel, username)

        password_sel = "input[name='j_password']"
        await page.wait_for_selector(password_sel, state="visible", timeout=10000)
        await page.fill(password_sel, password)
        print("[login] Credentials filled.", flush=True)

        # 4. Click the Sign In button
        #    Actual id: "postloginform#/Academy/j_spring_security_check"
        #    It has onclick="javascript:loadUserData();"
        print("[login] Clicking Sign In button...", flush=True)
        sign_in_btn = "button#postloginform\\#\\/Academy\\/j_spring_security_check"
        try:
            await page.wait_for_selector(sign_in_btn, timeout=5000)
            await page.click(sign_in_btn)
        except PlaywrightTimeout:
            # Fallback: click by text
            print("[login] CSS selector failed, trying text selector...", flush=True)
            await page.click("button:has-text('Sign In')")

        print("[login] Sign In clicked.", flush=True)

        # 5. Wait for navigation / post-login page load
        print("[login] Waiting for post-login navigation...", flush=True)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except PlaywrightTimeout:
            pass  # some pages never fully settle

        # 6. Verify login success
        current_url = page.url
        print(f"[login] Current URL: {current_url}", flush=True)

        # Quick-fail: PESU redirects to ?authfailed=<code> on bad credentials
        if "authfailed" in current_url:
            print("[login] URL contains 'authfailed' — invalid credentials.", flush=True)
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
            print("[login] Dashboard element detected — login successful!", flush=True)
            return True
        except PlaywrightTimeout:
            # Extra check: look for error messages on the login page
            error_text = await page.text_content(".login-error, .error-msg, .alert-danger") or ""
            if error_text.strip():
                print(f"[login] Login error displayed: {error_text.strip()}", flush=True)
            else:
                # Dump a snippet of the page so we can debug further
                title = await page.title()
                print(f"[login] Page title: {title}", flush=True)
                print(f"[login] URL: {page.url}", flush=True)
            print("[login] Dashboard element not found — login failed.", flush=True)
            return False

    except PlaywrightTimeout as e:
        print(f"[login] Timeout during login: {e}", flush=True)
        return False
    except Exception as e:
        print(f"[login] Unexpected error during login: {type(e).__name__}: {e}", flush=True)
        return False
