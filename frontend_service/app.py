"""Servizio del front-end: pagina statica della chat e config.js con l'indirizzo del back-end."""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"


def config_script(backend_url: str) -> str:
    """Script con la configurazione; <, > e & sono escapati perché il testo non chiuda mai un tag <script>."""
    text = json.dumps({"backendUrl": backend_url})
    text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return "window.APP_CONFIG = " + text + ";\n"


def create_app(backend_url: str) -> FastAPI:
    app = FastAPI(title="Front-end della chat")
    script = config_script(backend_url)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/config.js", include_in_schema=False)
    def config_js() -> Response:
        return Response(script, media_type="text/javascript; charset=utf-8", headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
