import logging

from fastapi.testclient import TestClient

from notes_service.app import create_app


def make_client(tmp_path):
    return TestClient(create_app(tmp_path / "notes.db"))


def test_crea_legge_elenca(tmp_path):
    client = make_client(tmp_path)
    r = client.post("/notes", json={"text": "report", "due_date": "2026-11-13"})
    assert r.status_code == 201
    note = r.json()
    assert note["id"] == 1
    r = client.get("/notes/1")
    assert r.status_code == 200
    assert r.json() == note
    r = client.get("/notes")
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["notes"] == [note]


def test_testo_vuoto_422(tmp_path):
    r = make_client(tmp_path).post("/notes", json={"text": ""})
    assert r.status_code == 422
    assert r.json()["detail"] == "Il testo della nota è vuoto."


def test_scadenza_non_valida_422(tmp_path):
    r = make_client(tmp_path).post("/notes", json={"text": "x", "due_date": "13/11/2026"})
    assert r.status_code == 422
    assert "AAAA-MM-GG" in r.json()["detail"]


def test_limit_fuori_intervallo_422(tmp_path):
    r = make_client(tmp_path).get("/notes?limit=0")
    assert r.status_code == 422
    assert "fra 1 e 50" in r.json()["detail"]


def test_nota_inesistente_404(tmp_path):
    client = make_client(tmp_path)
    for r in (client.get("/notes/99"), client.delete("/notes/99")):
        assert r.status_code == 404
        assert r.json()["detail"] == "Nessuna nota con ID 99."


def test_elimina(tmp_path):
    client = make_client(tmp_path)
    note = client.post("/notes", json={"text": "report"}).json()
    r = client.delete("/notes/1")
    assert r.status_code == 200
    assert r.json() == note
    assert client.get("/notes/1").status_code == 404


def test_log_creazione_ed_eliminazione(tmp_path, caplog):
    client = make_client(tmp_path)
    with caplog.at_level(logging.INFO, logger="notes_service"):
        client.post("/notes", json={"text": "report"})
        client.delete("/notes/1")
    assert "nota creata id=1" in caplog.text
    assert "nota eliminata id=1" in caplog.text


def test_persistenza_fra_istanze(tmp_path):
    make_client(tmp_path).post("/notes", json={"text": "report"})
    assert make_client(tmp_path).get("/notes/1").status_code == 200


def test_openapi(tmp_path):
    r = make_client(tmp_path).get("/openapi.json")
    assert r.status_code == 200
    assert "/notes" in r.text
