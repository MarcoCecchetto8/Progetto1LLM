import asyncio
import json
import threading

import httpx
from fastapi.testclient import TestClient

from assistant.agent_http import AgentHTTPClient, parse_sse
from backend_service import streaming
from backend_service.app import create_app
from backend_service.streaming import sse, stream_turn_events
from backend_service.turns import ChatTurns
from tests.memory_chat_store import MemoryChatStore

WAIT = 5  # secondi massimi per ogni attesa dei test: nessun thread resta appeso

HISTORY = [{"ruolo": "utente", "contenuto": "Che ore sono?"}, {"ruolo": "assistente", "contenuto": "Sono le 14:32."}]
TOOLS = [{"nome": "get_current_time", "argomenti": {}, "esito": "ok", "errore": None}]
COMPLETED = {"esito": "completato", "risposta": "Sono le 14:32.", "strumenti": TOOLS, "righe": ["[revisore] ok"],
             "cronologia": HISTORY, "riassunto": ""}
ASKING = {"esito": "conferma_richiesta", "sospeso": {"x": 1},
          "conferme": [{"id_nota": 3, "domanda": "Elimino la nota 3?"}]}
STEPS = [
    ("ragionamento", {"testo": "Penso…"}),
    ("strumento", {"nome": "get_current_time", "argomenti": {}}),
    ("esito_strumento", {"nome": "get_current_time", "esito": "ok"}),
    ("riga", {"testo": "[revisore] ok"}),
    ("risposta", {"testo": "Sono le 14:32."}),
]


def sse_response(*events):
    body = "".join(sse(name, data) for name, data in events)
    return httpx.Response(200, content=body.encode("utf-8"), headers={"content-type": streaming.SSE_MEDIA_TYPE})


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
    client = TestClient(create_app(store, http))
    chat_id = client.post("/chats").json()["id"]
    return client, store, agent, chat_id


def events_of(response) -> list[tuple[str, dict]]:
    return list(parse_sse(response.text.split("\n")))


def stream_send(client, chat_id, text="Che ore sono?"):
    return client.post(f"/chats/{chat_id}/messaggi/stream", json={"testo": text})


def test_sse_format():
    assert sse("riga", {"testo": "è"}) == 'event: riga\ndata: {"testo": "è"}\n\n'


def test_stream_forwards_and_saves():
    client, store, agent, cid = make(sse_response(*STEPS, ("fine", COMPLETED)))
    response = stream_send(client, cid)
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    events = events_of(response)
    assert events[:5] == STEPS
    assert len(events) == 6
    name, fine = events[5]
    assert name == "fine"
    chat = client.get(f"/chats/{cid}").json()
    assert [m["ruolo"] for m in chat["messaggi"]] == ["utente", "assistente"]
    # Stesso corpo di POST /messaggi: messaggi salvati con id, niente cronologia
    assert fine == {"esito": "completato", "domanda": chat["messaggi"][0], "risposta": chat["messaggi"][1],
                    "righe": ["[revisore] ok"], "conferme": []}
    assert "cronologia" not in response.text
    assert agent.bodies[0] == {"messaggi": [{"ruolo": "utente", "contenuto": "Che ore sono?"}],
                               "cronologia": [], "riassunto": ""}
    # Stesse chiavi della risposta JSON
    json_client, _, _, other = make(httpx.Response(200, json=COMPLETED))
    plain = json_client.post(f"/chats/{other}/messaggi", json={"testo": "Che ore sono?"}).json()
    assert set(plain) == set(fine)


def test_stream_confirmation_hides_suspended():
    client, store, agent, cid = make(sse_response(("fine", ASKING)),
                                     sse_response(("risposta", {"testo": "Fatto."}),
                                                  ("fine", {**COMPLETED, "risposta": "Nota eliminata."})))
    response = stream_send(client, cid, "Elimina la nota 3")
    events = events_of(response)
    assert events == [("fine", {"esito": "conferma_richiesta", "domanda": None, "risposta": None, "righe": [],
                                "conferme": ASKING["conferme"]})]
    assert "sospeso" not in response.text
    pending = store.get_chat(cid)["in_sospeso"]
    assert pending == {"sospeso": {"x": 1}, "domanda": "Elimina la nota 3", "conferme": ASKING["conferme"]}
    done = client.post(f"/chats/{cid}/conferma/stream", json={"decisioni": {"3": True}})
    assert done.status_code == 200
    assert agent.bodies[1] == {"ripresa": {"sospeso": {"x": 1}, "decisioni": {"3": True}}}
    events = events_of(done)
    assert [name for name, _ in events] == ["risposta", "fine"]
    assert events[1][1]["esito"] == "completato"
    chat = client.get(f"/chats/{cid}").json()
    assert [m["contenuto"] for m in chat["messaggi"]] == ["Elimina la nota 3", "Nota eliminata."]
    assert chat["conferme"] == []


def test_stream_agent_error_event():
    error = {"codice": "modello_timeout", "messaggio": "Il modello non ha risposto in tempo."}
    client, store, _, cid = make(sse_response(("risposta", {"testo": "Sono"}), ("errore", error)))
    events = events_of(stream_send(client, cid))
    assert events == [("risposta", {"testo": "Sono"}), ("errore", error)]
    assert store.get_messages(cid) == []
    assert store.get_chat(cid)["cronologia"] == []


def test_stream_agent_drops_without_fine():
    client, store, _, cid = make(sse_response(("risposta", {"testo": "Sono"})),
                                 sse_response(("fine", COMPLETED)))
    events = events_of(stream_send(client, cid))
    assert events[0] == ("risposta", {"testo": "Sono"})
    assert events[-1][0] == "errore"
    assert events[-1][1]["codice"] == "agente_non_raggiungibile"
    assert store.get_messages(cid) == []
    again = stream_send(client, cid)
    assert again.status_code == 200
    assert events_of(again)[-1][1]["esito"] == "completato"


def test_stream_agent_unreachable():
    client, store, _, cid = make(httpx.ConnectError("no"))
    events = events_of(stream_send(client, cid))
    assert [(n, d["codice"]) for n, d in events] == [("errore", "agente_non_raggiungibile")]
    assert store.get_messages(cid) == []


def test_stream_agent_http_error():
    client, _, _, cid = make(httpx.Response(422, json={"codice": "richiesta_non_valida", "messaggio": "No."}))
    events = events_of(stream_send(client, cid))
    assert events == [("errore", {"codice": "richiesta_non_valida", "messaggio": "No."})]


def test_stream_prechecks_are_http_errors():
    client, store, agent, cid = make(sse_response(("fine", ASKING)))
    missing = stream_send(client, 99)
    assert missing.status_code == 404
    assert missing.json()["codice"] == "chat_non_trovata"
    assert client.post("/chats/99/conferma/stream", json={"decisioni": {}}).status_code == 404
    empty = stream_send(client, cid, "   ")
    assert empty.status_code == 422
    no_pending = client.post(f"/chats/{cid}/conferma/stream", json={"decisioni": {"3": True}})
    assert no_pending.status_code == 409
    assert no_pending.json()["codice"] == "nessuna_conferma"
    stream_send(client, cid, "Elimina la nota 3")
    pending = stream_send(client, cid, "altro")
    assert pending.status_code == 409
    assert pending.json()["codice"] == "conferma_in_attesa"
    wrong = client.post(f"/chats/{cid}/conferma/stream", json={"decisioni": {"4": True}})
    assert wrong.status_code == 422
    assert wrong.json()["codice"] == "decisioni_non_valide"
    store.down = True
    down = stream_send(client, cid)
    assert down.status_code == 503
    assert down.json()["codice"] == "database_non_raggiungibile"
    store.down = False
    assert len(agent.bodies) == 1  # nessuno stream aperto verso l'agente dopo il primo
    # i controlli falliti non lasciano la chat occupata
    assert client.post(f"/chats/{cid}/conferma/stream", json={"decisioni": {"3": True}}).status_code == 200


def test_stream_busy_chat_is_409():
    client, _, _, cid = make(sse_response(("fine", COMPLETED)))
    app_turns = client.app.state.turns
    app_turns.acquire(cid)
    try:
        response = stream_send(client, cid)
        assert response.status_code == 409
        assert response.json()["codice"] == "turno_in_corso"
    finally:
        app_turns.release(cid)
    assert stream_send(client, cid).status_code == 200


def test_stream_chat_deleted_during_turn():
    client, store, agent, cid = make(sse_response(("fine", COMPLETED)))
    agent.on_call = lambda: store.delete_chat(cid)
    events = events_of(stream_send(client, cid))
    assert events[-1][0] == "errore"
    assert events[-1][1]["codice"] == "chat_non_trovata"
    assert store.get_messages(cid) == []


# --- generatore chiamato direttamente: disconnessione del client ---

def setup_direct(store=None):
    store = store if store is not None else MemoryChatStore()
    cid = store.create_chat()["id"]
    return store, ChatTurns(store), cid


class FakeAgent:
    def __init__(self, make_stream):
        self.make_stream = make_stream

    def stream_turn(self, payload):
        return self.make_stream()


def test_saved_when_client_leaves_after_fine(monkeypatch):
    monkeypatch.setattr(streaming, "KEEPALIVE_SECONDS", 0.01)
    saving, gate, released = threading.Event(), threading.Event(), threading.Event()

    class SlowStore(MemoryChatStore):
        def save_turn(self, *args):
            saving.set()
            gate.wait(WAIT)
            return super().save_turn(*args)

    store, turns, cid = setup_direct(SlowStore())

    def agent_stream():
        yield "fine", COMPLETED

    async def leave_during_save():
        gen = stream_turn_events(turns, FakeAgent(agent_stream), cid, {}, "Che ore sono?", released.set)
        assert await asyncio.to_thread(saving.wait, WAIT)
        first = await gen.__anext__()  # il salvataggio è in corso: arriva un keepalive
        assert first == streaming.KEEPALIVE
        await gen.aclose()  # il client se ne va

    asyncio.run(leave_during_save())
    gate.set()
    assert released.wait(WAIT)
    assert [m["contenuto"] for m in store.get_messages(cid)] == ["Che ore sono?", "Sono le 14:32."]


def test_cancel_before_fine_saves_nothing():
    store, turns, cid = setup_direct()
    gate, closed, released = threading.Event(), threading.Event(), threading.Event()

    def agent_stream():
        try:
            yield "risposta", {"testo": "Sono"}
            gate.wait(WAIT)
            yield "fine", COMPLETED
        except GeneratorExit:
            closed.set()
            raise

    async def leave_early():
        gen = stream_turn_events(turns, FakeAgent(agent_stream), cid, {}, "Che ore sono?", released.set)
        first = await gen.__anext__()
        while first == streaming.KEEPALIVE:
            first = await gen.__anext__()
        assert first == sse("risposta", {"testo": "Sono"})
        await gen.aclose()

    asyncio.run(leave_early())
    gate.set()
    assert released.wait(WAIT)
    assert closed.wait(WAIT)
    assert store.get_messages(cid) == []
    assert store.get_chat(cid)["cronologia"] == []


def test_released_even_if_stream_never_read():
    store, turns, cid = setup_direct()
    released = threading.Event()

    def agent_stream():
        yield "fine", COMPLETED

    stream_turn_events(turns, FakeAgent(agent_stream), cid, {}, "Che ore sono?", released.set)
    assert released.wait(WAIT)


def test_unexpected_error_becomes_event():
    store, turns, cid = setup_direct()
    released = threading.Event()

    def agent_stream():
        raise RuntimeError("guasto")
        yield  # pragma: no cover

    async def collect():
        gen = stream_turn_events(turns, FakeAgent(agent_stream), cid, {}, "Che ore sono?", released.set)
        return [item async for item in gen if item != streaming.KEEPALIVE]

    items = asyncio.run(collect())
    assert len(items) == 1
    assert items[0].startswith("event: errore\n")
    assert '"codice": "errore_imprevisto"' in items[0]
    assert released.wait(WAIT)
