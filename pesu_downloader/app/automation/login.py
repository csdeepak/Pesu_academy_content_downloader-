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
        print("[login] Navigating to PESU Academy...")
        await page.goto(PESU_URL, wait_until="domcontentloaded")
        print("[login] Page loaded.")

        # 2. Wait for the username input field
        print("[login] Waiting for username field...")
        username_selector = "input#j_scriptusername"
        await page.wait_for_selector(username_selector, state="visible", timeout=15000)
        print("[login] Username field visible.")

        # 3. Fill in credentials
        print("[login] Entering username...")
        await page.fill(username_selector, username)

        print("[login] Entering password...")
        password_selector = "input[name='j_password']"
        await page.wait_for_selector(password_selector, state="visible", timeout=10000)
        await page.fill(password_selector, password)
        print("[login] Credentials filled.")

        # 4. Click the login / submit button
        print("[login] Clicking login button...")
        submit_selector = "input#postloginform\\#702b"
        try:
            await page.wait_for_selector(submit_selector, state="visible", timeout=5000)
            await page.click(submit_selector)
        except PlaywrightTimeout:
            # Fallback: try a generic form-submit button
            print("[login] Primary submit selector not found, trying fallback...")
            fallback_selector = "form#loginForm input[type='submit'], form#loginForm button[type='submit']"
            await page.wait_for_selector(fallback_selector, state="visible", timeout=5000)
            await page.click(fallback_selector)

        print("[login] Login button clicked.")

        # 5. Wait for navigation to complete
        print("[login] Waiting for navigation after login...")
        await page.wait_for_load_state("domcontentloaded", timeout=20000)
        print("[login] Navigation complete.")

        # 6. Verify login success by checking for a known dashboard element
        print("[login] Verifying login success...")
        dashboard_selector = "a.menu-link, .navbar, .dashboard, .profile-menu"
        try:
            await page.wait_for_selector(dashboard_selector, state="visible", timeout=15000)
            print("[login] Dashboard element detected — login successful.")
            return True
        except PlaywrightTimeout:
            print("[login] Dashboard element not found — login may have failed.")
            return False

    except PlaywrightTimeout as e:
        print(f"[login] Timeout during login: {e}")
        return False
    except Exception as e:
        print(f"[login] Unexpected error during login: {e}")
        return False
