# PESU Vault

> Automate downloading course content (slides, notes, assignments, etc.) from [PESU Academy](https://www.pesuacademy.com/Academy/).

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-1.44+-2EAD33?logo=playwright&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## What It Does

PESU Vault uses browser automation (Playwright) to log into PESU Academy on your behalf, navigate to your enrolled courses, and batch-download all selected content types into organised folders on your machine.

**Supported content types:** Slides, Notes, Assignments, Question Banks (QB), Question & Answers (QA), MCQs, References, AV Summaries, Live Videos.

---

## Screenshots

The web interface features a cyberpunk-themed UI built with Three.js. After logging in with your PESU credentials, you can browse courses, select units, choose which content types to download, and let the tool handle the rest.

---

## Quick Start

### Prerequisites

| Requirement | Version |
|-------------|---------|
| Python      | 3.11+   |
| pip         | latest  |

### 1. Clone the Repository

```bash
git clone https://github.com/<your-username>/pesu-vault.git
cd pesu-vault
```

### 2. Create a Virtual Environment

```bash
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install Dependencies

```bash
cd pesu_downloader
pip install -r requirements.txt
```

### 4. Install Playwright Browsers

```bash
playwright install chromium
```

### 5. Run the Server

```bash
# From the pesu_downloader/ directory
uvicorn app.main:app --port 8001
```

Open [http://localhost:8001](http://localhost:8001) in your browser.

---

## Usage

1. **Login** — Enter your PESU Academy SRN and password.
2. **Select Course** — Choose from your enrolled courses for the current semester.
3. **Select Unit** — Pick a unit within the course.
4. **Choose Content Types** — Select which types to download (Slides, Notes, etc.).
5. **Download** — Files are saved to `~/Downloads/PESU_Downloads/<Course>/<Unit>/<Type>/`.

---

## Configuration

Environment variables you can set:

| Variable    | Default | Description                                     |
|-------------|---------|-------------------------------------------------|
| `HEADLESS`  | `true`  | Set to `false` to see the browser window        |
| `LOG_LEVEL` | `INFO`  | Logging level (`DEBUG`, `INFO`, `WARNING`, etc.) |

Example:
```bash
HEADLESS=false LOG_LEVEL=DEBUG uvicorn app.main:app --port 8001
```

On Windows:
```powershell
$env:HEADLESS="false"; $env:LOG_LEVEL="DEBUG"; uvicorn app.main:app --port 8001
```

---

## Docker

```bash
docker build -t pesu-vault .
docker run -p 8001:8001 pesu-vault
```

> **Note:** Docker runs in headless mode. Downloaded files stay inside the container unless you mount a volume:
> ```bash
> docker run -p 8001:8001 -v ~/Downloads/PESU_Downloads:/root/Downloads/PESU_Downloads pesu-vault
> ```

---

## Project Structure

```
pesu_downloader/
├── app/
│   ├── main.py              # FastAPI application entry point
│   ├── routes.py             # API endpoints
│   ├── session_manager.py    # Playwright browser session management
│   ├── automation/
│   │   ├── login.py          # PESU Academy login automation
│   │   ├── navigator.py      # Course/unit navigation
│   │   ├── extractor.py      # Content link extraction
│   │   └── downloader.py     # File download handler
│   ├── templates/
│   │   └── index.html        # Cyberpunk-themed frontend
│   └── static/
│       └── .gitkeep
├── downloads/
│   └── .gitkeep
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## Deployment Notes

This application **cannot be deployed on Vercel** or similar serverless platforms because:
- Playwright requires a Chromium binary (~400 MB)
- Browser sessions must persist across multiple API calls
- Serverless functions have size and timeout limits

**Recommended hosting options:**
- **Self-hosted** — Run locally or on a VPS (DigitalOcean, AWS EC2, Linode)
- **Railway** — Container-based, supports Playwright
- **Render** — Docker deployment with persistent containers
- **Fly.io** — Edge-deployed containers

---

## Tech Stack

- **Backend:** [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/)
- **Browser Automation:** [Playwright](https://playwright.dev/python/) (Chromium)
- **HTTP Downloads:** [aiohttp](https://docs.aiohttp.org/)
- **Frontend:** Vanilla JS + [Three.js](https://threejs.org/) (cyberpunk theme)
- **Templating:** [Jinja2](https://jinja.palletsprojects.com/)

---

## Disclaimer

This tool is intended for personal academic use only. It automates the same actions a student would perform manually in their browser. Always comply with PESU Academy's terms of service. The developers are not responsible for any misuse.

---

## License

[MIT](LICENSE)
