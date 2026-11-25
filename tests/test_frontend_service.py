"""Test del servizio del front-end e del contratto con l'OpenAPI del back-end."""

import json
import re
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from assistant.agent_http import AgentHTTPClient
from backend_service.app import create_app as create_backend_app
from frontend_service.app import create_app
from tests.memory_chat_store import MemoryChatStore

# Coppie (metodo, percorso OpenAPI) usate da static/app.js: il front-end non usa altri endpoint.
FRONTEND_CALLS = [
    ("get", "/chats"),
    ("post", "/chats"),
    ("get", "/chats/{chat_id}"),
    ("delete", "/chats/{chat_id}"),
    ("post", "/chats/{chat_id}/messaggi/stream"),
    ("post", "/chats/{chat_id}/conferma/stream"),
]

APP_JS = Path(__file__).resolve().parent.parent / "frontend_service" / "static" / "app.js"


def test_index_served():
    response = TestClient(create_app("http://127.0.0.1:8002")).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/config.js" in response.text
    assert "/static/app.js" in response.text


def test_static_files_served():
    client = TestClient(create_app("http://127.0.0.1:8002"))
    js = client.get("/static/app.js")
    css = client.get("/static/style.css")
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]
    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")


def test_page_and_static_files_are_revalidated():
    # Dopo un aggiornamento il browser non deve riusare app.js o style.css vecchi dalla cache
    client = TestClient(create_app("http://127.0.0.1:8002"))
    for path in ("/", "/static/app.js", "/static/style.css"):
        assert client.get(path).headers.get("cache-control") == "no-cache", path


def test_config_js_contains_backend_url():
    response = TestClient(create_app("http://127.0.0.1:8002")).get("/config.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-store"
    assert response.text == 'window.APP_CONFIG = {"backendUrl": "http://127.0.0.1:8002"};\n'


def test_config_js_escapes_dangerous_url():
    url = 'http://x/"</script><script>alert(1)//'
    body = TestClient(create_app(url)).get("/config.js").text
    assert "</script>" not in body
    assert '"</' not in body
    prefix, suffix = "window.APP_CONFIG = ", ";\n"
    assert body.startswith(prefix) and body.endswith(suffix)
    assert json.loads(body[len(prefix):-len(suffix)])["backendUrl"] == url


def test_backend_url_from_env():
    from frontend_service.__main__ import backend_url_from_env

    assert backend_url_from_env("") == "http://127.0.0.1:8002"
    assert backend_url_from_env("http://host:9/") == "http://host:9"
    with pytest.raises(ValueError, match="FRONTEND_BACKEND_URL non valida"):
        backend_url_from_env("host:9")


def test_main_exits_on_invalid_url(monkeypatch, capsys):
    from frontend_service.__main__ import main

    monkeypatch.setattr("frontend_service.__main__.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("FRONTEND_BACKEND_URL", "host:9")
    monkeypatch.setattr(sys, "argv", ["frontend_service"])
    with pytest.raises(SystemExit) as info:
        main()
    assert info.value.code == 1
    assert "FRONTEND_BACKEND_URL non valida" in capsys.readouterr().err


def test_frontend_calls_exist_in_backend_openapi():
    agent = AgentHTTPClient("http://agente", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    paths = create_backend_app(MemoryChatStore(), agent).openapi()["paths"]
    for method, path in FRONTEND_CALLS:
        assert path in paths, path
        assert method in paths[path], (method, path)


def app_js_paths(text: str) -> set[str]:
    """Percorsi letterali interi ("/..." o `/...`) usati in app.js, con ${...} sostituito da {chat_id}."""
    found = re.findall(r"""["`](/[^"`\s]*)["`]""", text)
    return {re.sub(r"\$\{[^}]+\}", "{chat_id}", path) for path in found}


def test_app_js_uses_only_known_paths():
    known = {path for _, path in FRONTEND_CALLS}
    used = app_js_paths(APP_JS.read_text(encoding="utf-8"))
    assert used, "nessun percorso trovato in app.js"
    assert used <= known, used - known


def test_app_js_paths_check_rejects_unknown_paths():
    # Il controllo non deve accorciare un percorso sconosciuto fino a un prefisso noto
    known = {path for _, path in FRONTEND_CALLS}
    for bad in ('api("GET", "/chats/export")', "request(`/chats/${id}/rinomina`)", 'api("GET", "/stato")',
                "`/chats/${id}/messaggi`"):
        assert not app_js_paths(bad) <= known, bad
