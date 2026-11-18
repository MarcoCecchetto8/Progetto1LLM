import os
import logging
import signal
import subprocess
import sys

import pytest

from assistant.__main__ import close_quietly, configure_logging, main

LIBRARIES = ("httpx", "httpx2", "openai", "httpcore")


@pytest.fixture
def restore_sigint():
    old = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGINT, old)


@pytest.fixture
def restore_logging():
    root = logging.getLogger()
    old = (root.level, root.handlers[:], {name: logging.getLogger(name).level for name in LIBRARIES})
    yield
    root.setLevel(old[0])
    root.handlers[:] = old[1]
    for name, level in old[2].items():
        logging.getLogger(name).setLevel(level)


def test_logging_info_plain_and_libraries_quiet(restore_logging):
    configure_logging("INFO")
    root = logging.getLogger()
    assert root.level == logging.INFO
    assert [h.stream for h in root.handlers] == [sys.stderr]
    assert root.handlers[0].formatter._fmt == "%(message)s"
    assert all(logging.getLogger(name).level == logging.WARNING for name in LIBRARIES)


def test_logging_debug_detailed_and_libraries_visible(restore_logging):
    for name in LIBRARIES:
        logging.getLogger(name).setLevel(logging.NOTSET)
    configure_logging("DEBUG")
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert "%(asctime)s" in root.handlers[0].formatter._fmt and "%(name)s" in root.handlers[0].formatter._fmt
    assert all(logging.getLogger(name).level == logging.NOTSET for name in LIBRARIES)


def test_logging_replaces_previous_handlers(restore_logging):
    configure_logging("INFO")
    configure_logging("WARNING")
    root = logging.getLogger()
    assert len(root.handlers) == 1 and root.level == logging.WARNING


def test_ctrl_c_at_startup(restore_sigint):
    out = []

    def start():
        raise KeyboardInterrupt

    assert main(start, out.append) == 0
    assert out == ["Arrivederci!"]


def test_exit_code_from_start(restore_sigint):
    assert main(lambda: 1, print) == 1


def test_heavy_imports_happen_inside_main():
    # Le librerie richiedono qualche secondo: caricate in main(), un Ctrl+C lì dà il saluto, non un traceback
    heavy = ("langgraph", "langchain_core", "langchain_openai", "openai", "dotenv",
             "assistant.mcp_client", "langchain_mcp_adapters", "mcp", "fastmcp",
             "assistant.notes", "fastapi", "notes_service")
    code = f"import sys, assistant.__main__; print([m for m in {heavy!r} if m in sys.modules])"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"


def test_late_ctrl_c_ignored_after_exit(restore_sigint):
    main(lambda: 0, print)
    assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN


def test_mcp_client_closed_with_ctrl_c_ignored(restore_sigint):
    # Su Windows un Ctrl+C a input() può arrivare dopo il saluto: durante la chiusura del server va ignorato
    seen = []

    class Client:
        def close(self):
            seen.append(signal.getsignal(signal.SIGINT))

    close_quietly(Client())
    assert seen == [signal.SIG_IGN]


def test_missing_scope_file_stops_startup_with_clear_message(tmp_path):
    # Senza traceback e prima di avviare server MCP e servizio delle note
    env = {**os.environ, "LMSTUDIO_BASE_URL": "http://127.0.0.1:9/v1", "LMSTUDIO_MODEL": "x",
           "SCOPE_FILE": str(tmp_path / "manca.txt"),
           "AGENT_SERVICE_URL": ""}
    result = subprocess.run([sys.executable, "-m", "assistant"], capture_output=True, text=True,
                            env=env, input="quit\n", timeout=60)
    assert result.returncode == 1
    assert "SCOPE_FILE non valida" in result.stderr
    assert "Traceback" not in result.stderr
    assert "[mcp]" not in result.stderr


class FakeService:
    """Servizio locale finto: registra start e close."""

    def __init__(self, *args, start=None, **kwargs):
        self.start_effect = start
        self.closed = 0
        FakeService.instance = self

    def start(self):
        if isinstance(self.start_effect, BaseException):
            raise self.start_effect
        return "http://127.0.0.1:8001"

    def close(self):
        self.closed += 1


GOOD_STATUS = {"agente": "ok",
               "modello": {"raggiungibile": True, "messaggio": "Modello m disponibile.", "modello": "m"},
               "strumenti": {"raggiungibile": True, "messaggio": "ok", "strumenti": 3},
               "note": {"raggiungibile": True, "messaggio": "ok", "indirizzo": "x"}}


class FakeAgentClient:
    status_value = GOOD_STATUS
    prompts_value = []

    def __init__(self, url, *args, **kwargs):
        self.url = url
        self.closed = 0
        FakeAgentClient.instance = self

    def status(self):
        if isinstance(self.status_value, BaseException):
            raise self.status_value
        return self.status_value

    def prompts(self):
        if isinstance(self.prompts_value, BaseException):
            raise self.prompts_value
        return self.prompts_value

    def close(self):
        self.closed += 1


@pytest.fixture
def start_env(monkeypatch, restore_sigint, restore_logging):
    """Ambiente di _start con servizio e client finti; restituisce la lista delle chiamate a run."""
    import assistant.agent_client
    import assistant.cli

    FakeAgentClient.status_value = GOOD_STATUS
    FakeAgentClient.prompts_value = []
    runs = []
    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LMSTUDIO_MODEL", "x")
    monkeypatch.delenv("AGENT_SERVICE_URL", raising=False)
    # _start importa load_dotenv al suo interno: senza questo copierebbe il vero .env in os.environ
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr(assistant.agent_client, "LocalAgentService", FakeService)
    monkeypatch.setattr(assistant.agent_client, "AgentClient", FakeAgentClient)
    monkeypatch.setattr(assistant.cli, "run", lambda *a, **k: runs.append((a, k)) or 0)
    return runs


def test_agent_unreachable_at_startup_stops_with_message(start_env, monkeypatch, capsys):
    from assistant.__main__ import _start
    from assistant.agent_client import AgentUnavailable

    import assistant.agent_client
    monkeypatch.setattr(assistant.agent_client, "LocalAgentService",
                        lambda **k: FakeService(start=AgentUnavailable("L'agente non è partito.")))
    assert _start() == 1
    err = capsys.readouterr().err
    assert "L'agente non è partito." in err
    assert "Traceback" not in err
    assert FakeService.instance.closed == 1
    assert start_env == []


def test_status_with_unreachable_model_stops_with_model_message(start_env, monkeypatch, capsys):
    from assistant.__main__ import _start

    FakeAgentClient.status_value = {**GOOD_STATUS, "modello": {
        "raggiungibile": False, "messaggio": "LM Studio non è raggiungibile all'indirizzo x.", "modello": "m"}}
    assert _start() == 1
    assert "LM Studio non è raggiungibile all'indirizzo x." in capsys.readouterr().err
    assert FakeAgentClient.instance.closed == 1 and FakeService.instance.closed == 1
    assert start_env == []


def test_status_with_unreachable_tools_stops_with_tools_message(start_env, capsys):
    from assistant.__main__ import _start

    FakeAgentClient.status_value = {**GOOD_STATUS, "strumenti": {
        "raggiungibile": False, "messaggio": "Il server degli strumenti non risponde: x", "strumenti": 0}}
    assert _start() == 1
    assert "Il server degli strumenti non risponde: x" in capsys.readouterr().err
    assert start_env == []


def test_agent_unavailable_on_status_stops_with_message(start_env, capsys):
    from assistant.__main__ import _start
    from assistant.agent_client import UNAVAILABLE, AgentUnavailable

    FakeAgentClient.status_value = AgentUnavailable(UNAVAILABLE)
    assert _start() == 1
    assert UNAVAILABLE in capsys.readouterr().err


def test_agent_request_error_on_status_stops_with_message(start_env, capsys):
    from assistant.__main__ import _start
    from assistant.agent_client import AgentRequestError

    FakeAgentClient.status_value = AgentRequestError("richiesta_non_valida", "Richiesta rifiutata dall'agente (HTTP 404).")
    assert _start() == 1
    err = capsys.readouterr().err
    assert "Richiesta rifiutata dall'agente (HTTP 404)." in err
    assert "Traceback" not in err
    assert start_env == []


def test_remote_agent_url_waits_until_agent_responds(start_env, monkeypatch):
    import time

    import assistant.agent_client
    from assistant.__main__ import _start

    answers = iter([False, False, True])
    monkeypatch.setattr(assistant.agent_client, "_responds", lambda url: next(answers))
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    monkeypatch.setenv("AGENT_SERVICE_URL", "http://agent:8001")
    assert _start() == 0
    assert next(answers, "finito") == "finito"  # tre tentativi consumati prima di status()
    assert len(start_env) == 1


def test_remote_agent_url_never_responding_stops_with_message(start_env, monkeypatch, capsys):
    import assistant.agent_client
    from assistant.__main__ import _start

    monkeypatch.setattr(assistant.agent_client, "_responds", lambda url: False)
    monkeypatch.setattr(assistant.agent_client, "START_TIMEOUT", 0.3)
    monkeypatch.setenv("AGENT_SERVICE_URL", "http://agent:8001")
    assert _start() == 1
    err = capsys.readouterr().err
    assert "http://agent:8001" in err and "Traceback" not in err
    assert start_env == []


def test_prompt_list_error_is_warning_and_startup_continues(start_env, capsys):
    import assistant.mcp_client
    from assistant.__main__ import _start

    FakeAgentClient.prompts_value = assistant.mcp_client.MCPPromptError("il server non ha prompt")
    assert _start() == 0
    # configure_logging(force=True) sostituisce gli handler: l'avviso si legge su stderr
    assert "[mcp] prompt non disponibili (il server non ha prompt): nessun prompt" in capsys.readouterr().err
    (args, kwargs), = start_env
    assert list(kwargs["prompt_list"]) == [] and kwargs["model"] == "m"
    assert FakeAgentClient.instance.closed == 1 and FakeService.instance.closed == 1


def test_remote_agent_url_skips_local_service(start_env, monkeypatch):
    import assistant.agent_client
    from assistant.__main__ import _start

    monkeypatch.setattr(assistant.agent_client, "_responds", lambda url: True)
    monkeypatch.setenv("AGENT_SERVICE_URL", "http://agent:8001/")
    FakeService.instance = None
    assert _start() == 0
    assert FakeAgentClient.instance.url == "http://agent:8001"
    assert FakeService.instance is None


def test_ctrl_c_while_service_starts_closes_it(start_env, monkeypatch, restore_sigint):
    import assistant.agent_client
    from assistant.__main__ import _start

    monkeypatch.setattr(assistant.agent_client, "LocalAgentService",
                        lambda **k: FakeService(start=KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        _start()
    assert FakeService.instance.closed == 1


def test_ctrl_c_after_start_closes_service_and_client(start_env, restore_sigint):
    from assistant.__main__ import _start

    FakeAgentClient.status_value = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        _start()
    assert FakeService.instance.closed == 1 and FakeAgentClient.instance.closed == 1


def test_unexpected_error_after_start_closes_service(start_env, restore_sigint):
    from assistant.__main__ import _start

    FakeAgentClient.prompts_value = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        _start()
    assert FakeService.instance.closed == 1 and FakeAgentClient.instance.closed == 1


def test_library_serializer_warnings_silenced():
    import warnings
    from assistant.__main__ import quiet_library_warnings
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        quiet_library_warnings()
        warnings.warn("Pydantic serializer warnings:\n  PydanticSerializationUnexpectedValue(...)", UserWarning)
        warnings.warn("altro avviso", UserWarning)
    assert [str(w.message) for w in caught] == ["altro avviso"]
