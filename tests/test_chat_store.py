import os
import uuid

import pytest

from backend_service.store import (
    DEFAULT_TITLE,
    PostgresChatStore,
    StoreUnavailable,
    title_from,
)
from tests.memory_chat_store import MemoryChatStore


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    if request.param == "memory":
        yield MemoryChatStore()
        return
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL non impostata")
    import psycopg

    schema = f"test_{uuid.uuid4().hex}"
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
    request.node.pg = (url, schema)
    try:
        yield PostgresChatStore(url, search_path=schema)
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")


def _turn(store, chat_id, question="Ciao", answer="Salve", **kw):
    args = dict(
        tools=[{"nome": "ora", "argomenti": {"fuso": "UTC"}, "esito": "ok", "errore": None}],
        lines=["riga"],
        history=[{"ruolo": "utente", "contenuto": question}],
        summary="riass",
    )
    args.update(kw)
    return store.save_turn(chat_id, question, answer, **args)


def test_create_and_get(store):
    chat = store.create_chat()
    assert chat["titolo"] == DEFAULT_TITLE
    assert chat["ultimo_messaggio"] is None
    got = store.get_chat(chat["id"])
    assert got["cronologia"] == []
    assert got["riassunto"] == ""
    assert got["in_sospeso"] is None


def test_create_with_title_cleaned(store):
    assert store.create_chat("  Python  ")["titolo"] == "Python"


def test_create_title_too_long(store):
    with pytest.raises(ValueError):
        store.create_chat("x" * 101)


def test_list_orders_by_activity(store):
    a = store.create_chat()
    b = store.create_chat()
    c = store.create_chat()
    assert [x["id"] for x in store.list_chats()] == [c["id"], b["id"], a["id"]]
    _turn(store, a["id"])
    assert [x["id"] for x in store.list_chats()] == [a["id"], c["id"], b["id"]]


def test_save_turn(store):
    chat = store.create_chat()
    store.set_pending(chat["id"], {"sospeso": {}, "domanda": "d", "conferme": []})
    user, assistant = _turn(store, chat["id"], "Che ore sono?", "Sono le 10")
    assert user["ruolo"] == "utente" and user["strumenti"] == [] and user["righe"] == []
    assert assistant["ruolo"] == "assistente"
    assert assistant["strumenti"][0]["nome"] == "ora"
    assert assistant["righe"] == ["riga"]
    msgs = store.get_messages(chat["id"])
    assert [m["ruolo"] for m in msgs] == ["utente", "assistente"]
    assert [m["contenuto"] for m in msgs] == ["Che ore sono?", "Sono le 10"]
    got = store.get_chat(chat["id"])
    assert got["cronologia"] == [{"ruolo": "utente", "contenuto": "Che ore sono?"}]
    assert got["riassunto"] == "riass"
    assert got["in_sospeso"] is None
    assert got["ultimo_messaggio"] is not None
    assert got["ultimo_messaggio"].tzinfo is not None
    assert got["titolo"] == title_from("Che ore sono?")
    _turn(store, chat["id"], "Altra domanda", "Altra")
    assert store.get_chat(chat["id"])["titolo"] == "Che ore sono?"
    assert len(store.get_messages(chat["id"])) == 4


def test_save_turn_unicode(store):
    chat = store.create_chat()
    text = "è «x» 😀\nriga"
    _turn(store, chat["id"], text, text)
    msgs = store.get_messages(chat["id"])
    assert msgs[0]["contenuto"] == text and msgs[1]["contenuto"] == text
    assert store.get_chat(chat["id"])["titolo"] == "è «x» 😀 riga"


def test_save_turn_missing_chat(store):
    assert _turn(store, 99999) is None


def test_pending_roundtrip(store):
    chat = store.create_chat()
    pending = {
        "sospeso": {"a": 1},
        "domanda": "Elimino?",
        "conferme": [{"id_nota": 3, "domanda": "Eliminare la nota 3?"}],
    }
    assert store.set_pending(chat["id"], pending) is True
    assert store.get_chat(chat["id"])["in_sospeso"] == pending
    assert store.set_pending(chat["id"], None) is True
    assert store.get_chat(chat["id"])["in_sospeso"] is None
    assert store.set_pending(99999, None) is False


def test_delete_cascades(store):
    chat = store.create_chat()
    _turn(store, chat["id"])
    assert store.delete_chat(chat["id"]) is True
    assert store.get_chat(chat["id"]) is None
    assert store.get_messages(chat["id"]) == []
    assert store.delete_chat(chat["id"]) is False


def test_persists_after_restart(store, request):
    if not isinstance(store, PostgresChatStore):
        pytest.skip("solo PostgreSQL")
    url, schema = request.node.pg
    chat = store.create_chat("Resta")
    _turn(store, chat["id"])
    again = PostgresChatStore(url, search_path=schema)
    assert again.get_chat(chat["id"])["titolo"] == "Resta"
    assert len(again.get_messages(chat["id"])) == 2


def test_title_from_rules():
    assert title_from("a" * 60) == "a" * 60
    assert title_from("a" * 61) == "a" * 59 + "…"
    assert title_from("uno\ndue\t\ttre") == "uno due tre"


def test_unreachable_database():
    with pytest.raises(StoreUnavailable):
        PostgresChatStore("postgresql://x:y@127.0.0.1:1/z")
