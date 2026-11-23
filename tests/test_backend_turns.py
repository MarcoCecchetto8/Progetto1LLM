import json

import httpx
import pytest
from fastapi.testclient import TestClient

from assistant.agent_http import AgentHTTPClient
from backend_service.app import create_app
from tests.memory_chat_store import MemoryChatStore

HISTORY = [{"ruolo": "utente", "contenuto": "Che ore sono?"}, {"ruolo": "assistente", "contenuto": "Sono le 14:32."}]
TOOLS = [{"nome": "get_current_time", "argomenti": {}, "esito": "ok", "errore": None}]


def completed(answer="Sono le 14:32.", history=None, summary="", tools=None, lines=None):
    return httpx.Response(200, json={
        "esito": "completato", "risposta": answer, "strumenti": TOOLS if tools is None else tools,
        "righe": ["[revisore] ok"] if lines is None else lines,
        "cronologia": HISTORY if history is None else history, "riassunto": summary})


def asking(note_id=3, suspended=None):
    return httpx.Response(200, json={
        "esito": "conferma_richiesta", "sospeso": suspended or {"x": 1},
        "conferme": [{"id_nota": note_id, "domanda": f"Elimino la nota {note_id}?"}]})


class Agent:
    """Agente simulato: risposte in coda (o eccezioni), corpi ricevuti registrati."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.bodies = []
        self.on_call = None

    def __call__(self, request):
        self.bodies.append(json.loads(request.content))
        if self.on_call:
            self.on_call()
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def make(*replies):
    agent = Agent(*replies)
    store = MemoryChatStore()
    http = AgentHTTPClient("http://agente", transport=httpx.MockTransport(agent))
    app = create_app(store, http)
    client = TestClient(app)
    chat_id = client.post("/chats").json()["id"]
    return client, store, agent, chat_id, app


def send(client, chat_id, text="Che ore sono?"):
    return client.post(f"/chats/{chat_id}/messaggi", json={"testo": text})


def test_send_completed_saves_both():
    client, _, agent, cid, _ = make(completed())
    response = send(client, cid)
    assert response.status_code == 200
    body = response.json()
    assert body["esito"] == "completato"
    assert body["domanda"]["contenuto"] == "Che ore sono?"
    assert body["domanda"]["ruolo"] == "utente"
    assert body["risposta"]["contenuto"] == "Sono le 14:32."
    assert body["risposta"]["strumenti"][0]["nome"] == "get_current_time"
    assert body["righe"] == ["[revisore] ok"]
    chat = client.get(f"/chats/{cid}").json()
    assert [m["ruolo"] for m in chat["messaggi"]] == ["utente", "assistente"]
    assert chat["titolo"] == "Che ore sono?"
    assert agent.bodies[0] == {"messaggi": [{"ruolo": "utente", "contenuto": "Che ore sono?"}],
                               "cronologia": [], "riassunto": ""}


def test_second_turn_sends_saved_history():
    client, _, agent, cid, _ = make(completed(summary="Riassunto."), completed("Ancora."))
    send(client, cid)
    send(client, cid, "E adesso?")
    assert agent.bodies[1]["cronologia"] == HISTORY
    assert agent.bodies[1]["riassunto"] == "Riassunto."


def test_agent_unreachable_saves_nothing():
    client, _, _, cid, _ = make(httpx.ConnectError("no"), completed())
    response = send(client, cid)
    assert response.status_code == 503
    assert response.json()["codice"] == "agente_non_raggiungibile"
    assert client.get(f"/chats/{cid}").json()["messaggi"] == []
    assert send(client, cid).status_code == 200


def test_agent_error_passthrough():
    error = httpx.Response(504, json={"codice": "modello_timeout", "messaggio": "Il modello è troppo lento."})
    client, _, _, cid, _ = make(error)
    response = send(client, cid)
    assert response.status_code == 504
    assert response.json() == {"codice": "modello_timeout", "messaggio": "Il modello è troppo lento."}
    assert client.get(f"/chats/{cid}").json()["messaggi"] == []


def test_invalid_agent_reply():
    client, _, _, cid, _ = make(httpx.Response(200, json={"esito": "boh"}))
    response = send(client, cid)
    assert response.status_code == 502
    assert response.json()["codice"] == "risposta_agente_non_valida"
    assert client.get(f"/chats/{cid}").json()["messaggi"] == []


def test_empty_text_is_422():
    client, _, agent, cid, _ = make()
    assert send(client, cid, "   ").status_code == 422
    assert agent.bodies == []


def test_missing_chat_is_404():
    client, _, _, _, _ = make()
    response = send(client, 99)
    assert response.status_code == 404
    assert response.json()["codice"] == "chat_non_trovata"


def test_confirmation_flow():
    client, _, agent, cid, _ = make(asking(), completed("Nota eliminata."))
    first = send(client, cid, "Elimina la nota 3")
    assert first.status_code == 200
    body = first.json()
    assert body["esito"] == "conferma_richiesta"
    assert body["conferme"] == [{"id_nota": 3, "domanda": "Elimino la nota 3?"}]
    assert "sospeso" not in json.dumps(body)
    chat = client.get(f"/chats/{cid}").json()
    assert chat["messaggi"] == []
    assert chat["conferme"] == body["conferme"]
    assert "sospeso" not in json.dumps(chat)
    blocked = send(client, cid, "altro")
    assert blocked.status_code == 409
    assert blocked.json()["codice"] == "conferma_in_attesa"
    done = client.post(f"/chats/{cid}/conferma", json={"decisioni": {"3": True}})
    assert done.status_code == 200
    assert agent.bodies[1] == {"ripresa": {"sospeso": {"x": 1}, "decisioni": {"3": True}}}
    assert done.json()["esito"] == "completato"
    chat = client.get(f"/chats/{cid}").json()
    assert [m["contenuto"] for m in chat["messaggi"]] == ["Elimina la nota 3", "Nota eliminata."]
    assert chat["conferme"] == []


@pytest.mark.parametrize("decisions", [{"4": True}, {}])
def test_confirmation_wrong_ids(decisions):
    client, _, agent, cid, _ = make(asking())
    send(client, cid)
    response = client.post(f"/chats/{cid}/conferma", json={"decisioni": decisions})
    assert response.status_code == 422
    assert response.json()["codice"] == "decisioni_non_valide"
    assert "3" in response.json()["messaggio"]
    assert len(agent.bodies) == 1
    assert client.get(f"/chats/{cid}").json()["conferme"] != []


def test_confirmation_error_keeps_pending():
    client, _, _, cid, _ = make(asking(), httpx.ConnectError("no"), completed("Fatto."))
    send(client, cid)
    failed = client.post(f"/chats/{cid}/conferma", json={"decisioni": {"3": False}})
    assert failed.status_code == 503
    assert client.get(f"/chats/{cid}").json()["conferme"] != []
    again = client.post(f"/chats/{cid}/conferma", json={"decisioni": {"3": False}})
    assert again.status_code == 200
    assert again.json()["esito"] == "completato"


def test_second_suspension_replaces_pending():
    client, store, _, cid, _ = make(asking(3), asking(5, {"y": 2}))
    send(client, cid, "Elimina 3 e 5")
    response = client.post(f"/chats/{cid}/conferma", json={"decisioni": {"3": True}})
    assert response.json()["esito"] == "conferma_richiesta"
    assert response.json()["conferme"] == [{"id_nota": 5, "domanda": "Elimino la nota 5?"}]
    pending = store.get_chat(cid)["in_sospeso"]
    assert pending["domanda"] == "Elimina 3 e 5"
    assert pending["sospeso"] == {"y": 2}
    assert [c["id_nota"] for c in client.get(f"/chats/{cid}").json()["conferme"]] == [5]


def test_no_pending_is_409():
    client, _, _, cid, _ = make()
    response = client.post(f"/chats/{cid}/conferma", json={"decisioni": {"3": True}})
    assert response.status_code == 409
    assert response.json()["codice"] == "nessuna_conferma"


def test_confirm_missing_chat_is_404():
    client, _, _, _, _ = make()
    assert client.post("/chats/9/conferma", json={"decisioni": {}}).status_code == 404


def test_busy_chat_is_409():
    client, _, _, cid, app = make(completed())
    other = client.post("/chats").json()["id"]
    with app.state.turns.busy(cid):
        response = send(client, cid)
        assert response.status_code == 409
        assert response.json()["codice"] == "turno_in_corso"
        assert send(client, other).status_code == 200
    # liberata all'uscita
    client2, _, _, cid2, _ = make(completed())
    assert send(client2, cid2).status_code == 200


def test_busy_released_after_error():
    client, _, _, cid, _ = make(httpx.ConnectError("no"), completed())
    assert send(client, cid).status_code == 503
    assert send(client, cid).status_code == 200


def test_chat_deleted_during_turn(caplog):
    client, store, agent, cid, _ = make(completed())
    agent.on_call = lambda: store.delete_chat(cid)
    with caplog.at_level("INFO", logger="backend_service"):
        response = send(client, cid)
    assert response.status_code == 404
    assert response.json()["codice"] == "chat_non_trovata"
    assert f"[backend] chat {cid} eliminata durante il turno: risposta non salvata" in caplog.text
    assert store.get_messages(cid) == []


def test_unexpected_error_is_500():
    class Broken(MemoryChatStore):
        def list_chats(self):
            raise RuntimeError("guasto")

    http = AgentHTTPClient("http://agente", transport=httpx.MockTransport(Agent()))
    client = TestClient(create_app(Broken(), http), raise_server_exceptions=False)
    response = client.get("/chats")
    assert response.status_code == 500
    assert response.json() == {"codice": "errore_imprevisto", "messaggio": "Errore imprevisto: guasto. Riprova."}


def test_integration_with_real_agent_api():
    from agent_service.app import create_app as create_agent_app
    from langchain_core.messages import AIMessage

    from assistant.graph import build_graph
    from tests.fakes import fake, fake_clock, tool_call
    from tests.test_agent_api import make_agent

    graph = build_graph(fake(tool_call({}, "c1"), AIMessage("Sono le 14:32."), AIMessage("Ancora le 14:32.")),
                        [fake_clock], 5)
    agent_client = TestClient(create_agent_app(make_agent(graph)))

    def to_agent(request):  # il trasporto di TestClient non ha un flusso sincrono compatibile con httpx.Client
        reply = agent_client.request(request.method, request.url.path, content=request.content,
                                     headers={"content-type": "application/json"})
        return httpx.Response(reply.status_code, content=reply.content,
                              headers={"content-type": reply.headers["content-type"]})

    http = AgentHTTPClient("http://testserver", transport=httpx.MockTransport(to_agent))
    client = TestClient(create_app(MemoryChatStore(), http))
    cid = client.post("/chats").json()["id"]
    first = send(client, cid, "Che ore sono?")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["esito"] == "completato"
    assert body["risposta"]["contenuto"] == "Sono le 14:32."
    assert body["risposta"]["strumenti"][0]["nome"] == "get_current_time"
    second = send(client, cid, "E adesso?")  # l'agente accetta la cronologia salvata
    assert second.status_code == 200, second.text
    assert second.json()["risposta"]["contenuto"] == "Ancora le 14:32."
