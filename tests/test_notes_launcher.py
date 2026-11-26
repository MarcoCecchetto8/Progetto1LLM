import os
import socket
import subprocess

import httpx
import pytest

from assistant.notes import LocalNotesService, NotesConnectionError, wait_until_ready


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def services(tmp_path):
    started = []

    def make(port, name="n.db"):
        service = LocalNotesService(port=port, db=tmp_path / name)
        started.append(service)
        return service

    yield make
    for service in started:
        service.close()


def test_start_serves_and_close_frees_port(services):
    port = free_port()
    service = services(port)
    url = service.start()
    assert url == f"http://127.0.0.1:{port}"
    assert httpx.get(f"{url}/notes").status_code == 200
    service.close()
    with pytest.raises(httpx.TransportError):
        httpx.get(f"{url}/notes", timeout=1)
    service.close()


def test_port_in_use_is_reported(services):
    port = free_port()
    services(port).start()
    with pytest.raises(NotesConnectionError) as error:
        services(port, "m.db").start()
    assert "già in uso" in str(error.value)
    assert "docker compose down" in str(error.value)


def test_wait_until_ready_times_out():
    with pytest.raises(NotesConnectionError):
        wait_until_ready("http://127.0.0.1:9", timeout=0.5)


def test_service_started_in_own_process_group(monkeypatch):
    # Verifica il ramo della piattaforma corrente: l'altro ramo non è eseguibile qui senza finti flag
    calls = []

    class FakeProc:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            pass

    def fake_popen(command, **kwargs):
        calls.append(kwargs)
        return FakeProc()

    monkeypatch.setattr("assistant.notes.subprocess.Popen", fake_popen)
    monkeypatch.setattr("assistant.notes._responds", lambda url: False)
    monkeypatch.setattr("assistant.notes.wait_until_ready", lambda url, alive=None: None)
    service = LocalNotesService(port=free_port())
    service.start()
    service.close()
    if os.name == "nt":
        assert calls == [{"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}]
    else:
        assert calls == [{"start_new_session": True}]
