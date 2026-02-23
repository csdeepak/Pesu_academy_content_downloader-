import uuid
import traceback

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel

from app.session_manager import create_session, get_session, close_session, run_in_pw_loop
from app.automation.login import login
from app.automation.navigator import (
    go_to_my_courses, get_courses, get_units, click_unit, debug_page,
)
from app.automation.extractor import extract_content_from_table
from app.automation.downloader import download_files

# Column names we care about (subset — the table may have more)
ALL_CONTENT_TYPES = [
    "Slides", "Notes", "Assignments", "QB", "QA", "MCQs", "References",
    "AV Summary", "Live Videos",
]

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ── Pydantic request models ─────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class SessionRequest(BaseModel):
    session_id: str


class CourseRequest(BaseModel):
    session_id: str
    course_id: str


class UnitRequest(BaseModel):
    session_id: str
    unit_index: int


class DownloadRequest(BaseModel):
    session_id: str
    course_name: str
    unit_name: str
    content_types: list[str] = []
    mode: str = "selective"


# ── Endpoints ────────────────────────────────────────────────

@router.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.post("/login")
async def login_endpoint(body: LoginRequest):
    """Authenticate and return session_id."""
    session_id = str(uuid.uuid4())
    try:
        print(f"[routes] /login — creating session {session_id}…", flush=True)
        try:
            session = await create_session(session_id)
        except Exception as e:
            traceback.print_exc()
            return JSONResponse(status_code=500, content={
                "status": "error",
                "message": f"Browser session failed: {type(e).__name__}: {e}",
            })

        page = session["page"]
        success = await run_in_pw_loop(login(page, body.username, body.password))

        if success:
            print(f"[routes] /login — success", flush=True)
            return {"status": "success", "session_id": session_id}
        else:
            print(f"[routes] /login — failed", flush=True)
            await close_session(session_id)
            return JSONResponse(status_code=401, content={
                "status": "error",
                "message": "Invalid credentials. Please check your SRN and password.",
            })
    except Exception as e:
        traceback.print_exc()
        await close_session(session_id)
        return JSONResponse(status_code=500, content={
            "status": "error", "message": f"{type(e).__name__}: {e}",
        })


@router.post("/fetch_courses")
async def fetch_courses_endpoint(body: SessionRequest):
    """Navigate to My Courses and return the list of enrolled courses."""
    try:
        session = get_session(body.session_id)
        if not session:
            return JSONResponse(status_code=404, content={
                "status": "error", "message": "Session not found",
            })

        page = session["page"]

        async def _go():
            await go_to_my_courses(page)
            return await get_courses(page)

        courses = await run_in_pw_loop(_go())
        return {"status": "success", "courses": courses}

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "status": "error", "message": str(e),
        })


@router.post("/fetch_units")
async def fetch_units_endpoint(body: CourseRequest):
    """Click a course and return its unit tabs."""
    try:
        session = get_session(body.session_id)
        if not session:
            return JSONResponse(status_code=404, content={
                "status": "error", "message": "Session not found",
            })

        page = session["page"]
        units = await run_in_pw_loop(get_units(page, body.course_id))
        return {"status": "success", "units": units}

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "status": "error", "message": str(e),
        })


@router.post("/click_unit")
async def click_unit_endpoint(body: UnitRequest):
    """Click a unit tab and return its content-table column mapping."""
    try:
        session = get_session(body.session_id)
        if not session:
            return JSONResponse(status_code=404, content={
                "status": "error", "message": "Session not found",
            })

        page = session["page"]
        col_map = await run_in_pw_loop(click_unit(page, body.unit_index))
        # Store the col_map and unit_index in the session so /download can reuse it
        session["col_map"] = col_map
        session["unit_index"] = body.unit_index
        return {"status": "success", "columns": col_map}

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "status": "error", "message": str(e),
        })


@router.post("/download")
async def download_endpoint(body: DownloadRequest):
    """Extract links from the current content table and download files."""
    try:
        session = get_session(body.session_id)
        if not session:
            return JSONResponse(status_code=404, content={
                "status": "error", "message": "Session not found",
            })

        page = session["page"]
        col_map = session.get("col_map", {})

        if not col_map:
            return JSONResponse(status_code=400, content={
                "status": "error",
                "message": "No content table loaded. Click a unit first.",
            })

        content_types = ALL_CONTENT_TYPES if body.mode == "full" else body.content_types
        if not content_types:
            return JSONResponse(status_code=400, content={
                "status": "error", "message": "No content types specified.",
            })

        unit_index = session.get("unit_index", 0)

        # Extract links from the visible table
        extracted = await run_in_pw_loop(
            extract_content_from_table(page, col_map, content_types, unit_index)
        )

        # Get cookies from browser context for authenticated downloads
        context = session.get("context")
        cookies = []
        if context:
            cookies = await run_in_pw_loop(context.cookies())

        # Download files via HTTP
        summary = await download_files(extracted, body.course_name, body.unit_name, cookies)

        return {"status": "success", "summary": summary}

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "status": "error", "message": str(e),
        })


# ── Debug endpoints (keep for development) ──────────────────

@router.post("/debug_page")
async def debug_page_endpoint(body: SessionRequest):
    """Dump current page state for debugging."""
    try:
        session = get_session(body.session_id)
        if not session:
            return JSONResponse(status_code=404, content={
                "status": "error", "message": "Session not found",
            })

        page = session["page"]

        async def _dump():
            url = page.url
            title = await page.title()
            links = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a'))
                    .filter(a => a.offsetParent !== null)
                    .map(a => ({
                        text: a.innerText.trim().substring(0, 80),
                        href: a.getAttribute('href') || '',
                    }))
                    .filter(x => x.text.length > 0);
            }""")
            selects = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('select')).map(s => ({
                    id: s.id, name: s.name,
                    options: Array.from(s.options).map(o => ({ value: o.value, text: o.textContent.trim() }))
                }));
            }""")
            return {"url": url, "title": title, "links": links[:50], "selects": selects}

        data = await run_in_pw_loop(_dump())
        return {"status": "success", "debug": data}

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "status": "error", "message": str(e),
        })


@router.post("/debug_dom")
async def debug_dom_endpoint(body: SessionRequest):
    """Inspect the content table cells to understand their structure."""
    try:
        session = get_session(body.session_id)
        if not session:
            return JSONResponse(status_code=404, content={
                "status": "error", "message": "Session not found",
            })

        page = session["page"]

        async def _inspect():
            data = await page.evaluate("""() => {
                // Find the content table (the one with >2 header columns)
                const tables = document.querySelectorAll('table');
                let contentTable = null;
                for (const table of tables) {
                    const ths = table.querySelectorAll('thead th, tr:first-child th');
                    if (ths.length > 2) {
                        contentTable = table;
                        break;
                    }
                }
                if (!contentTable) return { error: 'No content table found' };

                // Get headers
                const headers = Array.from(contentTable.querySelectorAll('thead th'))
                    .map((th, i) => ({ index: i, text: (th.innerText || '').trim() }));

                // Get first 3 rows with cell details
                const rows = contentTable.querySelectorAll('tbody tr');
                const rowDetails = [];
                for (let r = 0; r < Math.min(rows.length, 3); r++) {
                    const cells = rows[r].querySelectorAll('td');
                    const cellDetails = [];
                    for (let c = 0; c < cells.length; c++) {
                        const cell = cells[c];
                        const text = (cell.innerText || '').trim();
                        const innerHTML = cell.innerHTML.substring(0, 500);
                        const links = Array.from(cell.querySelectorAll('a')).map(a => ({
                            href: a.getAttribute('href') || '',
                            onclick: a.getAttribute('onclick') || '',
                            text: (a.innerText || '').trim(),
                            outerHTML: a.outerHTML.substring(0, 300)
                        }));
                        const clickables = Array.from(cell.querySelectorAll('i, span, button, img')).map(el => ({
                            tag: el.tagName,
                            className: el.className || '',
                            onclick: el.getAttribute('onclick') || '',
                            outerHTML: el.outerHTML.substring(0, 300)
                        }));
                        cellDetails.push({
                            colIndex: c,
                            text: text.substring(0, 100),
                            innerHTML: innerHTML,
                            links: links,
                            clickables: clickables,
                            isEmpty: text === '-' || text === ''
                        });
                    }
                    rowDetails.push({ rowIndex: r, cells: cellDetails });
                }

                return { headers, rowCount: rows.length, rows: rowDetails };
            }""")
            return data

        result = await run_in_pw_loop(_inspect())
        return {"status": "success", "debug": result}

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "status": "error", "message": str(e),
        })


class EvalJS(BaseModel):
    session_id: str
    js: str


@router.post("/eval_js")
async def eval_js_endpoint(body: EvalJS):
    """Evaluate arbitrary JS in the Playwright page and return the result."""
    try:
        session = get_session(body.session_id)
        if not session:
            return JSONResponse(status_code=404, content={
                "status": "error", "message": "Session not found",
            })
        page = session["page"]

        async def _eval():
            return await page.evaluate(body.js)

        result = await run_in_pw_loop(_eval())
        return {"status": "success", "result": result}
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "status": "error", "message": str(e),
        })


class DebugClickCell(BaseModel):
    session_id: str
    onclick_js: str


@router.post("/debug_click_cell")
async def debug_click_cell_endpoint(body: DebugClickCell):
    """Call a cell's onclick JS and inspect the resulting page state."""
    try:
        session = get_session(body.session_id)
        if not session:
            return JSONResponse(status_code=404, content={
                "status": "error", "message": "Session not found",
            })

        page = session["page"]

        async def _click_and_inspect():
            import asyncio as _asyncio
            await page.evaluate(body.onclick_js)
            await _asyncio.sleep(3)
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass

            from app.automation.navigator import debug_page as _dbg
            await _dbg(page, "after_cell_click")

            data = await page.evaluate("""() => {
                // Get visible text of the page
                var bodyText = document.body.innerText.substring(0, 3000);

                // All visible links
                var visibleLinks = Array.from(document.querySelectorAll('a')).filter(a => a.offsetParent !== null).map(a => ({
                    href: a.getAttribute('href') || '',
                    text: (a.innerText || '').trim().substring(0, 80),
                    onclick: (a.getAttribute('onclick') || '').substring(0, 200)
                })).filter(x => x.text.length > 0).slice(0, 40);

                // Check for iframes
                var iframes = Array.from(document.querySelectorAll('iframe')).map(f => ({
                    src: f.src || '',
                    visible: f.offsetParent !== null
                }));

                // Any Google Docs viewer or PDF links
                var pdfLinks = Array.from(document.querySelectorAll('a[href*="pdf"], a[href*="drive.google"], a[href*="ViewContent"], a[href*="docs.google"], iframe[src*="docs.google"], iframe[src*="pdf"]')).map(el => ({
                    tag: el.tagName,
                    href: el.getAttribute('href') || el.getAttribute('src') || ''
                }));

                // Check for file download anchors with specific patterns
                var allAnchors = Array.from(document.querySelectorAll('a')).map(a => ({
                    href: a.getAttribute('href') || '',
                    text: (a.innerText || '').trim().substring(0, 80)
                })).filter(a => a.href && !a.href.startsWith('javascript:') && a.href !== '#' && a.href.length > 10);

                // Content panes (coursvideoseMaterial_*)
                var panes = document.querySelectorAll('[id^="coursvideoseMaterial_"]');
                var contentPanes = Array.from(panes).map(function(p) {
                    return {
                        id: p.id,
                        visible: p.offsetParent !== null,
                        className: p.className,
                        htmlLen: p.innerHTML.length,
                        snippet: p.innerHTML.substring(0, 2000)
                    };
                });

                return { bodyText, visibleLinks, iframes, pdfLinks, allAnchorsCount: allAnchors.length, sampleAnchors: allAnchors.slice(0, 20), contentPanes };
            }""")
            return data

        result = await run_in_pw_loop(_click_and_inspect())
        return {"status": "success", "debug": result}

    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "status": "error", "message": str(e),
        })