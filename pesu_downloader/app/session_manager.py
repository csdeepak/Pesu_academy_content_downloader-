"""
session_manager.py — Manages Playwright browser sessions keyed by UUID.
"""

from playwright.async_api import async_playwright

# Global dictionary: session_id (str) → session dict
active_sessions: dict[str, dict] = {}


async def create_session(session_id: str) -> dict | None:
    """Launch Playwright, open a headless Chromium browser, create a context
    and page, then store everything in active_sessions under *session_id*.

    Returns the session dict on success, or None on failure.
    """
    try:
        print(f"[session_manager] Creating session {session_id}...")

        print(f"[session_manager] Launching Playwright...")
        playwright = await async_playwright().start()

        print(f"[session_manager] Launching Chromium (headless)...")
        browser = await playwright.chromium.launch(headless=True)

        print(f"[session_manager] Creating browser context...")
        context = await browser.new_context()

        print(f"[session_manager] Opening new page...")
        page = await context.new_page()

        session = {
            "playwright": playwright,
            "browser": browser,
            "context": context,
            "page": page,
        }

        active_sessions[session_id] = session
        print(f"[session_manager] Session {session_id} created successfully.")
        return session

    except Exception as e:
        print(f"[session_manager] Error creating session {session_id}: {e}")
        return None


async def get_session(session_id: str) -> dict | None:
    """Return the session dict for *session_id*, or None if it doesn't exist."""
    try:
        session = active_sessions.get(session_id)
        if session is None:
            print(f"[session_manager] Session {session_id} not found.")
        else:
            print(f"[session_manager] Session {session_id} retrieved.")
        return session

    except Exception as e:
        print(f"[session_manager] Error retrieving session {session_id}: {e}")
        return None


async def close_session(session_id: str) -> bool:
    """Close the browser (which also closes context/page) and stop the
    Playwright instance, then remove the session from the dict.

    Returns True on success, False on failure or if the session wasn't found.
    """
    try:
        session = active_sessions.get(session_id)
        if session is None:
            print(f"[session_manager] Session {session_id} not found — nothing to close.")
            return False

        print(f"[session_manager] Closing browser for session {session_id}...")
        await session["browser"].close()

        print(f"[session_manager] Stopping Playwright for session {session_id}...")
        await session["playwright"].stop()

        del active_sessions[session_id]
        print(f"[session_manager] Session {session_id} closed and removed.")
        return True

    except Exception as e:
        print(f"[session_manager] Error closing session {session_id}: {e}")
        # Best-effort cleanup
        active_sessions.pop(session_id, None)
        return False
