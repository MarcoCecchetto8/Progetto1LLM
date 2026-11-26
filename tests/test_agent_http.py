"""Test del client HTTP leggero dell'agente (senza modello e senza rete)."""

import json
import subprocess
import sys

import httpx
import pytest

from assistant.agent_http import KEEPALIVE_EVENT, AgentHTTPClient, AgentRequestError, AgentUnavailable, parse_sse


def test_import_is_light():
    code = (
        "import sys, assistant.agent_http; "
        "bad=[m for m in sys.modules if m.split('.')[0] in "
        "('langchain_core','langgraph','mcp','fastmcp','langchain_mcp_adapters','openai')]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_turn_returns_json_body():
    payload = {"messaggi": [{"ruolo": "utente", "contenuto": "ciao"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat"
        assert json.loads(request.content) == payload
        return httpx.Response(200, json={"esito": "completato", "risposta": "ok"})

    client = AgentHTTPClient("http://agent", transport=httpx.MockTransport(handler))
    assert client.turn(payload) == {"esito": "completato", "risposta": "ok"}


def test_turn_error_keeps_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"codice": "modello_non_raggiungibile", "messaggio": "LM Studio non risponde"})

    client = AgentHTTPClient("http://agent", transport=httpx.MockTransport(handler))
    with pytest.raises(AgentRequestError) as info:
        client.turn({})
    assert info.value.code == "modello_non_raggiungibile"
    assert info.value.message == "LM Studio non risponde"
    assert info.value.status == 503


def test_turn_connect_error_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("giù")

    client = AgentHTTPClient("http://agent", transport=httpx.MockTransport(handler))
    with pytest.raises(AgentUnavailable):
        client.turn({})


def test_parse_sse_keepalive_only_on_request():
    lines = [": ", "", "event: risposta", 'data: {"testo": "ok"}', "", ": "]
    assert list(parse_sse(lines)) == [("risposta", {"testo": "ok"})]
    assert list(parse_sse(lines, keepalive=True)) == [
        (KEEPALIVE_EVENT, {}), ("risposta", {"testo": "ok"}), (KEEPALIVE_EVENT, {})]
