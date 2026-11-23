import subprocess
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from assistant.agent_http import AgentHTTPClient
from backend_service.app import create_app
from backend_service.errors import AGENT_DOWN, DB_DOWN
from tests.memory_chat_store import MemoryChatStore

AGENT_OK = {
    "agente": "ok",
    "modello": {"raggiungibile": True, "messaggio": "ok"},
    "strumenti": {"raggiungibile": True, "messaggio": "ok"},
}


def make_client(handler=None, store=None):
    if handler is None:
        def handler(request):
            return httpx.Response(200, json=AGENT_OK)
    store = store if store is not None else MemoryChatStore()
    agent = AgentHTTPClient("http://agente", transport=httpx.MockTransport(handler))
    return TestClient(create_app(store, agent)), store


def test_create_list_get_delete():
    client, _ = make_client()
    created = client.post("/chats")
    assert created.status_code == 201
    chat = created.json()
    assert chat["id"] == 1
    assert chat["titolo"] == "Nuova chat"
    assert [c["id"] for c in client.get("/chats").json()] == [1]
    detail = client.get("/chats/1").json()
    assert detail["messaggi"] == []
    assert detail["conferme"] == []
    assert client.delete("/chats/1").status_code == 204
    missing = client.get("/chats/1")
    assert missing.status_code == 404
    assert missing.json() == {"codice": "chat_non_trovata", "messaggio": "La chat 1 non esiste."}
    assert client.delete("/chats/1").status_code == 404


def test_detail_shows_pending_confirmations():
    client, store = make_client()
    chat = client.post("/chats", json={"titolo": "Prova"}).json()
    store.set_pending(chat["id"], {"conferme": [{"id_nota": 3, "domanda": "Elimino la nota 3?"}], "sospeso": {}})
    detail = client.get(f"/chats/{chat['id']}").json()
    assert detail["conferme"] == [{"id_nota": 3, "domanda": "Elimino la nota 3?"}]


def test_create_title_too_long_is_422():
    client, _ = make_client()
    response = client.post("/chats", json={"titolo": "x" * 101})
    assert response.status_code == 422
    assert "charset=utf-8" in response.headers["content-type"]


def test_json_charset():
    client, _ = make_client()
    assert "charset=utf-8" in client.get("/chats").headers["content-type"]


def test_status_ok():
    client, _ = make_client()
    response = client.get("/stato")
    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "ok"
    assert body["database"]["raggiungibile"] is True
    assert body["agente"]["raggiungibile"] is True
    assert body["agente"]["dettagli"] == AGENT_OK


def test_status_agent_down():
    def handler(request):
        raise httpx.ConnectError("no")

    client, _ = make_client(handler)
    response = client.get("/stato")
    assert response.status_code == 503
    body = response.json()
    assert body["agente"]["raggiungibile"] is False
    assert body["agente"]["messaggio"] == AGENT_DOWN
    assert body["database"]["raggiungibile"] is True


def test_status_agent_degraded():
    degraded = {**AGENT_OK, "modello": {"raggiungibile": False, "messaggio": "LM Studio non risponde"}}

    client, _ = make_client(lambda request: httpx.Response(503, json=degraded))
    response = client.get("/stato")
    assert response.status_code == 503
    assert response.json()["agente"]["raggiungibile"] is False
    assert response.json()["agente"]["dettagli"] == degraded


def test_status_database_down():
    client, store = make_client()
    store.down = True
    response = client.get("/stato")
    assert response.status_code == 503
    body = response.json()
    assert body["database"]["raggiungibile"] is False
    assert body["database"]["messaggio"] == DB_DOWN
    assert body["agente"]["raggiungibile"] is True


def test_database_down_is_503():
    client, store = make_client()
    store.down = True
    for response in (client.get("/chats"), client.post("/chats")):
        assert response.status_code == 503
        assert response.json() == {
            "codice": "database_non_raggiungibile",
            "messaggio": "Il database non risponde: controlla che PostgreSQL sia avviato.",
        }


def test_openapi_lists_paths():
    client, _ = make_client()
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/chats", "/chats/{chat_id}", "/stato"):
        assert path in paths


def test_backend_import_is_light():
    code = (
        "import sys, backend_service.app, backend_service.__main__; "
        "bad=[m for m in sys.modules if m.split('.')[0] in "
        "('langchain_core','langgraph','mcp','fastmcp','langchain_mcp_adapters','openai','agent_service')]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_main_exits_without_database(monkeypatch, capsys):
    from backend_service.__main__ import main

    monkeypatch.setenv("DATABASE_URL", "postgresql://lab:segretissima@127.0.0.1:1/lab")
    monkeypatch.setattr(sys, "argv", ["backend_service"])
    with pytest.raises(SystemExit) as info:
        main()
    assert info.value.code == 1
    err = capsys.readouterr().err
    assert "Il database non risponde" in err
    assert "segretissima" not in err


def test_main_exits_without_database_url(monkeypatch, capsys):
    from backend_service.__main__ import main

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr(sys, "argv", ["backend_service"])
    with pytest.raises(SystemExit) as info:
        main()
    assert info.value.code == 1
    assert "DATABASE_URL" in capsys.readouterr().err
