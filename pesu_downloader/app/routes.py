import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel

from session_manager import create_session, get_session, close_session
from automation.login import login
from automation.navigator import get_semesters, get_subjects, get_units

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class LoginRequest(BaseModel):
    username: str
    password: str


class SessionRequest(BaseModel):
    session_id: str


class SemesterSubjectsRequest(BaseModel):
    session_id: str
    semester_value: str


class SubjectUnitsRequest(BaseModel):
    session_id: str
    subject_id: str


@router.get("/")
async def index(request: Request):
    """Render the main page."""
    return templates.TemplateResponse("index.html", {"request": request})


@router.post("/login")
async def login_endpoint(body: LoginRequest):
    """Authenticate against PESU Academy and return a session_id."""
    session_id = str(uuid.uuid4())

    try:
        # Create a new Playwright session
        session = await create_session(session_id)
        if session is None:
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": "Failed to create browser session"},
            )

        page = session["page"]

        # Attempt login
        success = await login(page, body.username, body.password)

        if success:
            return {"status": "success", "session_id": session_id}
        else:
            await close_session(session_id)
            return JSONResponse(
                status_code=401,
                content={"status": "error", "message": "Login failed"},
            )

    except Exception as e:
        # Clean up on unexpected errors
        await close_session(session_id)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


@router.post("/fetch_semesters")
async def fetch_semesters_endpoint(body: SessionRequest):
    """Return available semesters for the logged-in session."""
    try:
        session = await get_session(body.session_id)
        if session is None:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "Session not found"},
            )

        page = session["page"]
        semesters = await get_semesters(page)
        return {"status": "success", "semesters": semesters}

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


@router.post("/fetch_subjects")
async def fetch_subjects_endpoint(body: SemesterSubjectsRequest):
    """Return subjects for a given semester."""
    try:
        session = await get_session(body.session_id)
        if session is None:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "Session not found"},
            )

        page = session["page"]
        subjects = await get_subjects(page, body.semester_value)
        return {"status": "success", "subjects": subjects}

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


@router.post("/fetch_units")
async def fetch_units_endpoint(body: SubjectUnitsRequest):
    """Return units for a given subject."""
    try:
        session = await get_session(body.session_id)
        if session is None:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": "Session not found"},
            )

        page = session["page"]
        units = await get_units(page, body.subject_id)
        return {"status": "success", "units": units}

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )
