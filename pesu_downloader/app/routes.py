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
    go_to_my_courses, get_courses, get_units, click_unit,
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