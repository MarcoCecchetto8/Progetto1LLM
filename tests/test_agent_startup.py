import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from agent_service import startup
from agent_service.startup import build_agent, model_status
from assistant.config import ConfigError, load_settings
from assistant.llm import LMStudioUnavailable
from assistant.mcp_client import MCPConnectionError
from assistant.notes import LocalNotesService

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_settings(**extra):
    env = {"LMSTUDIO_BASE_URL": f"http://127.0.0.1:{free_port()}/v1", "LMSTUDIO_MODEL": "modello-prova",
           "LMSTUDIO_TIMEOUT": "2", **extra}
    return load_settings(env)


def test_model_status_ok():
    settings = make_settings()
    status = model_status(settings, list_models=lambda url, timeout: ["altro", "modello-prova"])
    assert status == {"raggiungibile": True, "messaggio": "Modello modello-prova disponibile.",
                      "modello": "modello-prova"}


def test_model_status_lm_studio_down():
    settings = make_settings()

    def down(url, timeout):
        raise LMStudioUnavailable("spento")

    status = model_status(settings, list_models=down)
    assert status == {"raggiungibile": False,
                      "messaggio": f"LM Studio non è raggiungibile all'indirizzo {settings.base_url}. "
                                   "Controlla che sia attivo e riprova.",
                      "modello": "modello-prova"}


def test_model_status_model_missing():
    settings = make_settings()
    status = model_status(settings, list_models=lambda url, timeout: ["altro"])
    assert status == {"raggiungibile": False,
                      "messaggio": "Modello 'modello-prova' non trovato. Modelli disponibili: altro.",
                      "modello": "modello-prova"}


@pytest.fixture
def notes_url(tmp_path):
    service = LocalNotesService(port=free_port(), db=tmp_path / "n.db")
    url = service.start()
    yield url
    service.close()


def test_build_agent_with_model_down(notes_url, caplog):
    settings = make_settings(NOTES_SERVICE_URL=notes_url)
    agent, close = build_agent(settings, ROOT)
    try:
        assert "[modello] LM Studio non è raggiungibile" in caplog.text
        assert agent.settings is settings
        assert agent.system
        status = agent.status()
        assert status["modello"]["raggiungibile"] is False
        assert status["strumenti"]["raggiungibile"] is True
        assert status["strumenti"]["messaggio"].startswith("Server degli strumenti attivo (")
        assert status["note"] == {"raggiungibile": True, "messaggio": f"Servizio delle note attivo ({notes_url}).",
                                  "indirizzo": notes_url}
        assert {p.name for p in agent.list_prompts()} == {"riassumi_conversazione", "spiega"}
    finally:
        close()
    status = agent.status()
    assert status["strumenti"]["raggiungibile"] is False
    assert status["strumenti"]["messaggio"] == ("Il server degli strumenti non risponde: riavvia l'agente "
                                                "(in locale basta riavviare l'assistente).")


def test_closing_frees_local_notes_service(tmp_path, monkeypatch):
    port = free_port()
    monkeypatch.setattr(startup, "LocalNotesService",
                        lambda quiet: LocalNotesService(port=port, quiet=quiet, db=tmp_path / "n.db"))
    agent, close = build_agent(make_settings(), ROOT)
    url = f"http://127.0.0.1:{port}"
    assert agent.status()["note"]["raggiungibile"] is True
    close()
    with pytest.raises(httpx.TransportError):
        httpx.get(f"{url}/notes", timeout=1.0)
    assert agent.status()["note"]["raggiungibile"] is False


def test_missing_scope_file_raises_config_error(notes_url):
    with pytest.raises(ConfigError, match="SCOPE_FILE"):
        build_agent(make_settings(SCOPE_FILE="config/inesistente.txt", NOTES_SERVICE_URL=notes_url), ROOT)


def test_missing_mcp_command_raises_connection_error(notes_url, monkeypatch):
    monkeypatch.setattr(startup, "server_command", lambda: [sys.executable, "-m", "modulo_inesistente"])
    with pytest.raises(MCPConnectionError):
        build_agent(make_settings(NOTES_SERVICE_URL=notes_url), ROOT)


def test_connection_lost_reading_preferences_stops_startup_and_closes_client(monkeypatch):
    import types

    class FakeClient:
        closed = 0

        def __init__(self, *args, **kwargs):
            FakeClient.instance = self

        def start(self):
            return [types.SimpleNamespace(name="get_current_time")]

        def read_resource(self, uri):
            raise MCPConnectionError("connessione persa")

        def close(self):
            self.closed += 1

    monkeypatch.setattr(startup, "MCPClient", FakeClient)
    with pytest.raises(MCPConnectionError, match="connessione persa"):
        build_agent(make_settings(), ROOT)
    assert FakeClient.instance.closed == 1


def test_main_exits_with_1_on_startup_error():
    env = {**os.environ, "LMSTUDIO_BASE_URL": f"http://127.0.0.1:{free_port()}/v1", "LMSTUDIO_MODEL": "m",
           "SCOPE_FILE": "config/inesistente.txt"}
    result = subprocess.run([sys.executable, "-m", "agent_service", "--port", str(free_port())], cwd=ROOT, env=env,
                            capture_output=True, timeout=60)
    assert result.returncode == 1
    assert "SCOPE_FILE non valida: 'config/inesistente.txt' non esiste o è vuoto." in result.stderr.decode("utf-8")


def test_model_status_uses_short_timeout():
    timeouts = []
    model_status(make_settings(LMSTUDIO_TIMEOUT="120"), list_models=lambda url, timeout: timeouts.append(timeout) or [])
    model_status(make_settings(LMSTUDIO_TIMEOUT="2"), list_models=lambda url, timeout: timeouts.append(timeout) or [])
    assert timeouts == [5.0, 2.0]


# Il servizio note locale usa sempre la porta 8000: nel sottoprocesso lo sostituisco con uno su porta di prova
WRAPPER = """
import sys
from pathlib import Path
from agent_service import startup
from assistant.notes import LocalNotesService
port, db = int(sys.argv.pop(1)), Path(sys.argv.pop(1))
startup.LocalNotesService = lambda quiet: LocalNotesService(port=port, quiet=quiet, db=db)
from agent_service.__main__ import main
sys.exit(main())
"""


def kill_port(port):
    """Termina chi ascolta sulla porta di prova: un padre già uscito non lascia il nipote al taskkill /T."""
    if os.name == "nt":
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
        pids = {line.split()[-1] for line in out.splitlines()
                if f"127.0.0.1:{port} " in line and "LISTENING" in line}
        for pid in pids:
            subprocess.run(["taskkill", "/T", "/F", "/PID", pid], capture_output=True)
    else:
        out = subprocess.run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
        for pid in out.split():
            subprocess.run(["kill", "-9", pid], capture_output=True)


def kill_tree(proc):
    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.kill()
        proc.wait()


def agent_env():
    return {**os.environ, "LMSTUDIO_BASE_URL": f"http://127.0.0.1:{free_port()}/v1", "LMSTUDIO_MODEL": "m",
            "NOTES_SERVICE_URL": "", "LOG_LEVEL": "INFO", "PYTHONUNBUFFERED": "1"}


def stop_options():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}, signal.CTRL_BREAK_EVENT
    return {"start_new_session": True}, signal.SIGTERM


def notes_up(port):
    try:
        return httpx.get(f"http://127.0.0.1:{port}/notes", timeout=2.0).status_code == 200
    except httpx.TransportError:
        return False


def test_main_closes_local_services_on_stop_signal(tmp_path):
    port, notes_port = free_port(), free_port()
    options, stop = stop_options()
    log = tmp_path / "agent.log"
    command = [sys.executable, "-c", WRAPPER, str(notes_port), str(tmp_path / "n.db"), "--port", str(port)]
    with open(log, "wb") as stderr:
        proc = subprocess.Popen(command, cwd=ROOT, env=agent_env(), stdout=subprocess.DEVNULL, stderr=stderr,
                                **options)
        try:
            deadline = time.monotonic() + 90
            while True:
                try:
                    httpx.get(f"http://127.0.0.1:{port}/stato", timeout=15.0)
                    break
                except httpx.TransportError:
                    assert proc.poll() is None and time.monotonic() < deadline, log.read_text("utf-8")
                    time.sleep(0.2)
            assert notes_up(notes_port)
            proc.send_signal(stop)
            code = proc.wait(timeout=30)
            time.sleep(1)
            # Nessun orfano: il servizio note avviato dall'agente deve aver liberato la porta
            assert not notes_up(notes_port)
        finally:
            kill_tree(proc)
            kill_port(notes_port)
    text = log.read_text("utf-8")
    assert code == 0, text
    assert "Traceback" not in text


# Avvio rallentato dopo le note: simula lo stop dell'agente mentre build_agent è in corso
SLOW_WRAPPER = WRAPPER.replace("from agent_service.__main__ import main", """import time
# Pause brevi: i gestori Python dei segnali girano solo tra un'istruzione e l'altra
startup.build_graph = lambda *args, **kwargs: [time.sleep(0.1) for _ in range(1200)]
from agent_service.__main__ import main""")


def test_main_closes_local_services_on_stop_signal_during_startup(tmp_path):
    port, notes_port = free_port(), free_port()
    options, stop = stop_options()
    log = tmp_path / "agent.log"
    command = [sys.executable, "-c", SLOW_WRAPPER, str(notes_port), str(tmp_path / "n.db"), "--port", str(port)]
    with open(log, "wb") as stderr:
        proc = subprocess.Popen(command, cwd=ROOT, env=agent_env(), stdout=subprocess.DEVNULL, stderr=stderr,
                                **options)
        try:
            deadline = time.monotonic() + 90
            while not notes_up(notes_port):
                assert proc.poll() is None and time.monotonic() < deadline, log.read_text("utf-8")
                time.sleep(0.2)
            time.sleep(1.5)  # il processo è dentro build_graph (in pausa)
            proc.send_signal(stop)
            code = proc.wait(timeout=30)
            time.sleep(1)
            assert not notes_up(notes_port)
        finally:
            kill_tree(proc)
            kill_port(notes_port)
    text = log.read_text("utf-8")
    assert code == 0, text
    assert "Traceback" not in text
