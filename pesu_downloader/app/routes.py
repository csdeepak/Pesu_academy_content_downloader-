import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel

from session_manager import create_session, close_session
from automation.login import login

router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class LoginRequest(BaseModel):
    username: str
    password: str


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
