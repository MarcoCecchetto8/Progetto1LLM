"""Client HTTP dell'agente: SSE, errori e integrazione con l'API vera (modello finto)."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent_service.app import create_app
from assistant.agent_client import AgentClient, AgentRequestError, AgentUnavailable, parse_sse
from assistant.graph import build_graph
from assistant.mcp_client import MCPConnectionError, MCPPromptError, PromptArgument, PromptInfo
from tests.fakes import fake, fake_clock, tool_call
from tests.test_agent_api import ask, make_agent


def sse(name, data):
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def test_parse_sse_italian_text_and_newlines():
    body = sse("risposta", {"testo": "è «x» ⚠\nriga"}) + sse("fine", {"esito": "completato"})
    assert list(parse_sse(body.splitlines(keepends=True))) == [
        ("risposta", {"testo": "è «x» ⚠\nriga"}), ("fine", {"esito": "completato"})]


def test_parse_sse_joins_data_lines():
    lines = ["event: riga", 'data: {"a":', "data: 1}", ""]
    assert list(parse_sse(lines)) == [("riga", {"a": 1})]


def test_parse_sse_last_event_without_blank_line():
    assert list(parse_sse(["event: fine", 'data: {"x": 1}'])) == [("fine", {"x": 1})]


def mock_client(handler):
    return AgentClient("http://agente", transport=httpx.MockTransport(handler))


def test_stream_turn_yields_events():
    body = sse("risposta", {"testo": "ciao"}) + sse("fine", {"esito": "completato"})
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=body.encode("utf-8"),
                              headers={"content-type": "text/event-stream; charset=utf-8"})

    client = mock_client(handler)
    assert list(client.stream_turn({"messaggi": []})) == [("risposta", {"testo": "ciao"}),
                                                           ("fine", {"esito": "completato"})]
    assert seen == [{"messaggi": []}]


def test_stream_turn_error_body():
    error = {"codice": "sospeso_non_valido", "messaggio": "stato sospeso non valido"}
    client = mock_client(lambda request: httpx.Response(422, json=error))
    with pytest.raises(AgentRequestError) as raised:
        list(client.stream_turn({}))
    assert raised.value.code == "sospeso_non_valido"
    assert raised.value.message == "stato sospeso non valido"


def test_stream_turn_validation_error_without_code():
    client = mock_client(lambda request: httpx.Response(422, json={"detail": []}))
    with pytest.raises(AgentRequestError) as raised:
        list(client.stream_turn({}))
    assert raised.value.code == "richiesta_non_valida"


def test_connect_error_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("rifiutata")

    client = mock_client(handler)
    with pytest.raises(AgentUnavailable, match="L'agente non risponde: esci e riavvia l'assistente."):
        list(client.stream_turn({}))
    with pytest.raises(AgentUnavailable):
        client.status()


def test_read_timeout_is_unlimited():
    client = AgentClient("http://agente")
    assert client._http.timeout.read is None
    assert client._http.timeout.connect == 10.0


def test_status_accepts_503():
    client = mock_client(lambda request: httpx.Response(503, json={"agente": "ok"}))
    assert client.status() == {"agente": "ok"}
    client = mock_client(lambda request: httpx.Response(500, json={"codice": "errore_imprevisto", "messaggio": "x"}))
    with pytest.raises(AgentRequestError):
        client.status()


def test_prompts_and_get_prompt_mapping():
    def handler(request):
        if request.url.path == "/prompts":
            return httpx.Response(200, json=[{"nome": "spiega", "descrizione": "Spiega", "argomenti": [
                {"nome": "argomento", "descrizione": "Cosa", "obbligatorio": True}]}])
        nome = json.loads(request.content)["argomenti"].get("argomento")
        if nome == "rifiuta":
            return httpx.Response(422, json={"codice": "prompt_rifiutato",
                                             "messaggio": "Il server ha rifiutato il prompt: argomento non valido"})
        if nome == "caduto":
            return httpx.Response(503, json={"codice": "strumenti_non_raggiungibili", "messaggio": "giù"})
        return httpx.Response(200, json={"messaggi": [{"ruolo": "utente", "contenuto": "Spiega x"},
                                                      {"ruolo": "assistente", "contenuto": "Ok"}]})

    client = mock_client(handler)
    assert client.prompts() == [PromptInfo("spiega", "Spiega", (PromptArgument("argomento", "Cosa", True),))]
    assert client.get_prompt("spiega", {"argomento": "x"}) == [("user", "Spiega x"), ("assistant", "Ok")]
    with pytest.raises(MCPPromptError) as refused:
        client.get_prompt("spiega", {"argomento": "rifiuta"})
    assert str(refused.value) == "argomento non valido"
    with pytest.raises(MCPConnectionError):
        client.get_prompt("spiega", {"argomento": "caduto"})


class TestClientTransport(httpx.BaseTransport):
    """Instrada le richieste verso l'app di TestClient senza rete (il suo trasporto non è di tipo sync)."""

    __test__ = False

    def __init__(self, api: TestClient):
        self.api = api

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        # TestClient usa un'altra libreria HTTP: la richiesta va ricostruita, non inoltrata
        response = self.api.request(request.method, str(request.url), headers=dict(request.headers),
                                    content=request.read())
        return httpx.Response(response.status_code, headers=dict(response.headers), content=response.content)


def test_integration_with_real_api_tool_turn():
    graph = build_graph(fake(tool_call({}, "c1"), AIMessage("Sono le 14:32 ⚠")), [fake_clock], 5)
    api = TestClient(create_app(make_agent(graph)))
    client = AgentClient("http://testserver", transport=TestClientTransport(api))
    events = list(client.stream_turn(ask("che ore sono?")))
    assert [name for name, _ in events] == ["strumento", "esito_strumento", "risposta", "fine"]
    assert events[2][1] == {"testo": "Sono le 14:32 ⚠"}
    assert events[-1][1]["esito"] == "completato"
    assert events[-1][1]["risposta"] == "Sono le 14:32 ⚠"
    assert client.status()["agente"] == "ok"
    assert client.prompts()[0].name == "spiega"
    assert client.get_prompt("spiega", {"argomento": "x"})[0] == ("user", "Spiega x")
