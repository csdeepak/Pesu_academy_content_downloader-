"""
session_manager.py — Manages Playwright browser sessions keyed by UUID.

Playwright's async API doesn't work inside uvicorn's event loop on Windows
(NotImplementedError from greenlet bridge).  We work around this by running
a **dedicated asyncio event loop** in a background daemon thread and
dispatching every Playwright coroutine there via `run_in_pw_loop()`.
"""

import asyncio
import threading
import traceback

from playwright.async_api import async_playwright

# ---------------------------------------------------------------------------
# Dedicated Playwright event-loop (runs in its own daemon thread)
# ---------------------------------------------------------------------------
_pw_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()


def _start_pw_loop() -> None:
    """Thread target: run the Playwright event-loop forever."""
    asyncio.set_event_loop(_pw_loop)
    _pw_loop.run_forever()


_pw_thread = threading.Thread(target=_start_pw_loop, daemon=True, name="playwright-loop")
_pw_thread.start()

# ---------------------------------------------------------------------------
# Public helper – call from any async context (e.g. FastAPI route)
# ---------------------------------------------------------------------------

async def run_in_pw_loop(coro):
    """Schedule *coro* on the Playwright loop and await the result from the
    caller's loop (i.e. uvicorn's loop).  Exceptions propagate normally."""
    future = asyncio.run_coroutine_threadsafe(coro, _pw_loop)
    return await asyncio.wrap_future(future)


# ---------------------------------------------------------------------------
# Session storage
# ---------------------------------------------------------------------------
active_sessions: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Internal coroutines (run on _pw_loop)
# ---------------------------------------------------------------------------

async def _create_session_impl(session_id: str) -> dict:
    print(f"[session_manager] Creating session {session_id} ...", flush=True)

    playwright = await async_playwright().start()
    print(f"[session_manager] Playwright started.", flush=True)

    browser = await playwright.chromium.launch(
        headless=False,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    print(f"[session_manager] Chromium launched.", flush=True)

    context = await browser.new_context()
    page = await context.new_page()

    session = {
        "playwright": playwright,
        "browser": browser,
        "context": context,
        "page": page,
    }
    active_sessions[session_id] = session
    print(f"[session_manager] Session {session_id} ready.", flush=True)
    return session


async def _close_session_impl(session_id: str) -> bool:
    session = active_sessions.get(session_id)
    if session is None:
        print(f"[session_manager] Session {session_id} not found.", flush=True)
        return False

    try:
        await session["browser"].close()
        await session["playwright"].stop()
    except Exception as exc:
        print(f"[session_manager] Cleanup error: {exc}", flush=True)
    finally:
        active_sessions.pop(session_id, None)

    print(f"[session_manager] Session {session_id} closed.", flush=True)
    return True


# ---------------------------------------------------------------------------
# Public API (called from FastAPI routes on uvicorn's loop)
# ---------------------------------------------------------------------------

async def create_session(session_id: str) -> dict:
    """Create a new Playwright browser session.  Raises on failure."""
    return await run_in_pw_loop(_create_session_impl(session_id))


def get_session(session_id: str) -> dict | None:
    """Return the session dict (plain dict lookup, no async needed)."""
    return active_sessions.get(session_id)


async def close_session(session_id: str) -> bool:
    """Close and remove a session."""
    return await run_in_pw_loop(_close_session_impl(session_id))
