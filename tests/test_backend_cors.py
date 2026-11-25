import httpx
from fastapi.testclient import TestClient

from assistant.agent_http import AgentHTTPClient
from backend_service.__main__ import parse_cors_origins
from backend_service.app import create_app
from tests.memory_chat_store import MemoryChatStore

ORIGIN = "http://127.0.0.1:8003"


def make_client(cors_origins=None):
    agent = AgentHTTPClient("http://agente", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    return TestClient(create_app(MemoryChatStore(), agent, cors_origins))


def preflight(client, path, method, origin=ORIGIN):
    return client.options(path, headers={
        "Origin": origin,
        "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "content-type",
    })


def test_allowed_origin_gets_cors_header():
    response = make_client([ORIGIN]).get("/chats", headers={"Origin": ORIGIN})
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_preflight_for_json_post():
    response = preflight(make_client([ORIGIN]), "/chats/1/messaggi/stream", "POST")
    assert response.status_code == 200
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_preflight_for_delete():
    response = preflight(make_client([ORIGIN]), "/chats/1", "DELETE")
    assert response.status_code == 200
    assert "DELETE" in response.headers["access-control-allow-methods"]


def test_other_origin_gets_no_cors_header():
    response = make_client([ORIGIN]).get("/chats", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_no_origins_no_middleware():
    response = make_client().get("/chats", headers={"Origin": ORIGIN})
    assert "access-control-allow-origin" not in response.headers


def test_parse_cors_origins():
    assert parse_cors_origins("  http://a:1/ , ,http://b:2") == ["http://a:1", "http://b:2"]
    assert parse_cors_origins("") == ["http://127.0.0.1:8003", "http://localhost:8003"]
