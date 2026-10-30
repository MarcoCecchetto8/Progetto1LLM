import logging
import signal
import subprocess
import sys

import pytest

from assistant.__main__ import configure_logging, main

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
    heavy = ("langgraph", "langchain_core", "langchain_openai", "openai", "dotenv")
    code = f"import sys, assistant.__main__; print([m for m in {heavy!r} if m in sys.modules])"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"


def test_late_ctrl_c_ignored_after_exit(restore_sigint):
    main(lambda: 0, print)
    assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
