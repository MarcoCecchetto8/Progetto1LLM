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
           "SCOPE_FILE": str(tmp_path / "manca.txt")}
    result = subprocess.run([sys.executable, "-m", "assistant"], capture_output=True, text=True,
                            env=env, input="quit\n", timeout=60)
    assert result.returncode == 1
    assert "SCOPE_FILE non valida" in result.stderr
    assert "Traceback" not in result.stderr
    assert "[mcp]" not in result.stderr


def test_library_serializer_warnings_silenced():
    import warnings
    from assistant.__main__ import quiet_library_warnings
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        quiet_library_warnings()
        warnings.warn("Pydantic serializer warnings:\n  PydanticSerializationUnexpectedValue(...)", UserWarning)
        warnings.warn("altro avviso", UserWarning)
    assert [str(w.message) for w in caught] == ["altro avviso"]
