from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.types import Scope

from app.config import WEB_DIR
from app.db import init_db
from app.routers import datasets, projects, tables, variables as variables_router

# `ready` drives the nav: a screen that isn't built yet renders as disabled
# rather than as a live link to an empty page.
SCREENS = [
    ("data", "Data", "Upload a dataset and check what came in", True),
    ("variables", "Variables", "Labels, value labels, multi-punch groups, nets", True),
    ("tables", "Tables", "Banners, statistics, significance testing", True),
    ("weighting", "Weighting", "Which weight your tables run on", True),
    ("models", "Models", "Regression and segmentation", False),
    ("exports", "Exports", "Excel workbooks and PowerPoint decks", False),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


class NoCacheStatic(StaticFiles):
    """Serve static files with caching switched off.

    Browsers cache ES modules hard, so without this a stylesheet or a JS module
    keeps running its old version after an edit -- which reads as "the feature
    is broken" rather than "you are looking at yesterday's code". Fonts are the
    one exception; they never change and are large.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        path = str(args[0]) if args else ""
        if not path.endswith((".otf", ".ttf", ".woff", ".woff2")):
            response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response


app = FastAPI(title="Survey analysis", lifespan=lifespan)
app.mount("/static", NoCacheStatic(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")

app.include_router(projects.router)
app.include_router(datasets.router)
app.include_router(variables_router.router)
app.include_router(tables.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# The Data screen is both the landing page and /data.
TEMPLATE_FOR_SCREEN = {"data": "index.html"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return _render(request, "data")


@app.get("/{screen}", response_class=HTMLResponse)
def screen(request: Request, screen: str):
    if screen not in {s[0] for s in SCREENS}:
        return HTMLResponse("Not found", status_code=404)
    return _render(request, screen)


def _render(request: Request, active: str) -> HTMLResponse:
    template = TEMPLATE_FOR_SCREEN.get(active, f"{active}.html")
    return templates.TemplateResponse(
        request, template, {"screens": SCREENS, "active": active}
    )
