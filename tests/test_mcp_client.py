import os
import sys

import pytest
from langchain_core.tools import ToolException

from assistant.config import load_settings
from assistant.mcp_client import MCPClient, MCPConnectionError, server_env

TEST_SERVER = [sys.executable, "-m", "tests.mcp_test_server"]


@pytest.fixture(scope="module")
def tools():
    # Una sola istanza per i test che non fermano il server: l'avvio richiede alcuni secondi
    with MCPClient(TEST_SERVER, os.environ) as tools:
        yield {t.name: t for t in tools}


@pytest.fixture
def own_tools():
    with MCPClient(TEST_SERVER, os.environ) as tools:
        yield {t.name: t for t in tools}


def test_catalog_from_server(tools):
    assert set(tools) == {"echo", "fail", "die"}
    assert "text" in tools["echo"].args_schema["properties"]


def test_call_returns_text(tools):
    assert tools["echo"].invoke({"text": "ciao"}) == "ciao"


def test_tool_error_raises_tool_exception(tools):
    with pytest.raises(ToolException, match="errore di prova"):
        tools["fail"].invoke({})


def test_dead_server_raises_connection_error(own_tools):
    with pytest.raises(MCPConnectionError):
        own_tools["die"].invoke({})
    with pytest.raises(MCPConnectionError):
        own_tools["echo"].invoke({"text": "ciao"})


def test_close_is_idempotent_and_final():
    client = MCPClient(TEST_SERVER, os.environ)
    echo = {t.name: t for t in client.start()}["echo"]
    client.close()
    client.close()
    with pytest.raises(MCPConnectionError):
        echo.invoke({"text": "ciao"})


def test_server_not_found():
    client = MCPClient([sys.executable, "-m", "modulo_inesistente"], os.environ, timeout=10)
    with pytest.raises(MCPConnectionError):
        client.start()
    client.close()


def settings(level):
    return load_settings({"LMSTUDIO_BASE_URL": "http://x/v1", "LMSTUDIO_MODEL": "m", "LOG_LEVEL": level,
                          "DEFAULT_TIMEZONE": "Asia/Tokyo"})


def test_server_env_info():
    env = server_env(settings("INFO"))
    assert env["FASTMCP_LOG_LEVEL"] == "CRITICAL"
    assert env["DEFAULT_TIMEZONE"] == "Asia/Tokyo" and env["LOG_LEVEL"] == "INFO"


def test_server_env_debug():
    assert server_env(settings("DEBUG"))["FASTMCP_LOG_LEVEL"] == "DEBUG"


def test_tool_error_is_silent_on_stderr_without_debug(tmp_path):
    errlog = (tmp_path / "stderr.txt").open("w+", encoding="utf-8")
    env = {**os.environ, "FASTMCP_LOG_LEVEL": server_env(settings("INFO"))["FASTMCP_LOG_LEVEL"]}
    with MCPClient(TEST_SERVER, env, errlog=errlog) as tools:
        with pytest.raises(ToolException):
            {t.name: t for t in tools}["fail"].invoke({})
    errlog.seek(0)
    assert errlog.read() == ""
