"""Avvio automatico del servizio agente (integrazione: processi veri, nessun LM Studio)."""

import os
import socket
import subprocess

import httpx
import pytest

from assistant.agent_client import AgentUnavailable, LocalAgentService
from assistant.notes import LocalNotesService


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def notes_url(tmp_path):
    service = LocalNotesService(port=free_port(), db=tmp_path / "n.db")
    url = service.start()
    yield url
    service.close()


@pytest.fixture
def agents(notes_url):
    """Fabbrica di LocalAgentService con ambiente di prova; a fine test chiude tutto, anche dopo un fallimento."""
    started = []

    def make(port=None, **env):
        # Il servizio note locale userebbe la 8000: se ne punta uno di prova; il modello è su una porta chiusa
        environment = {**os.environ, "NOTES_SERVICE_URL": notes_url, "LMSTUDIO_MODEL": "m",
                       "LMSTUDIO_BASE_URL": f"http://127.0.0.1:{free_port()}/v1", **env}
        service = LocalAgentService(port=port or free_port(), env=environment)
        started.append(service)
        return service

    yield make
    for service in started:
        proc = service._proc
        service.close()
        if proc is not None and proc.poll() is None and os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)


def test_start_serves_and_close_leaves_no_orphans(agents, notes_url, monkeypatch):
    killed = []
    real_kill = subprocess.Popen.kill
    monkeypatch.setattr(subprocess.Popen, "kill", lambda self: (killed.append(self.pid), real_kill(self))[1])
    port = free_port()
    service = agents(port)
    url = service.start()
    assert url == f"http://127.0.0.1:{port}"
    # Modello spento: l'agente c'è ma /stato dice 503
    response = httpx.get(f"{url}/stato", timeout=15.0)
    assert response.status_code == 503
    assert response.json()["modello"]["raggiungibile"] is False
    proc = service._proc
    service.close()
    # Chiusura ordinata: il finally dell'agente ha chiuso server MCP e client delle note, senza kill
    assert proc.returncode == 0
    assert killed == []
    with pytest.raises(httpx.TransportError):
        httpx.get(f"{url}/stato", timeout=1.0)
    # Il servizio note di prova non appartiene all'agente: resta del test
    assert httpx.get(f"{notes_url}/notes", timeout=2.0).status_code == 200
    service.close()


def test_port_in_use_is_reported(agents):
    first = agents()
    first.start()
    with pytest.raises(AgentUnavailable) as error:
        agents(first.port).start()
    assert "già in uso" in str(error.value)
    assert "docker compose down" in str(error.value)


def test_missing_scope_file_is_reported(agents):
    with pytest.raises(AgentUnavailable) as error:
        agents(SCOPE_FILE="config/inesistente.txt").start()
    assert str(error.value).startswith("L'agente non è partito: ")
    assert "SCOPE_FILE" in str(error.value)
